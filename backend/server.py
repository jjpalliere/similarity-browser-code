"""
FastAPI server with WebSocket streaming for step-by-step clustering.
"""

import os
import re
import uuid
import json
import io
import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, Any

RUN_ID_PATTERN = re.compile(r"^[a-f0-9]{8}$")

import numpy as np
import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from openai import OpenAI

from clustering import StepClusterer
from projector import project_3d

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

app = FastAPI(title="Similarity Browser API")

# CORS: restrict origins (allow_origins=["*"] + credentials is invalid per spec)
_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
CORS_ORIGINS = [o.strip() for o in _cors_origins.split(",") if o.strip()] or ["http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Persistence
DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "runs")
os.makedirs(DATA_DIR, exist_ok=True)

UPLOAD_PASSWORD = os.getenv("UPLOAD_PASSWORD", "")

# In-memory store for active runs
runs: Dict[str, Dict[str, Any]] = {}
# Index of saved runs (metadata only, loaded from disk on startup)
runs_index: Dict[str, Dict[str, Any]] = {}

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def save_run(run_id: str, run: dict):
    """Save a completed run to disk as JSON."""
    payload = {
        "run_id": run_id,
        "name": run.get("name", run_id),
        "created_at": run.get("created_at", datetime.now(timezone.utc).isoformat()),
        "row_count": len(run["texts"]),
        "text_col": run["text_col"],
        "metric_col": run["metric_col"],
        "events": run["events"],
    }
    path = os.path.join(DATA_DIR, f"{run_id}.json")
    with open(path, "w") as f:
        json.dump(payload, f)


def load_run_index() -> Dict[str, Dict[str, Any]]:
    """Scan data/runs/ and load metadata (not events) for all saved runs."""
    index = {}
    for fname in os.listdir(DATA_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(DATA_DIR, fname)
        try:
            with open(path, "r") as f:
                data = json.load(f)
            rid = data["run_id"]
            index[rid] = {
                "name": data.get("name", rid),
                "created_at": data.get("created_at", ""),
                "row_count": data.get("row_count", 0),
                "text_col": data.get("text_col", ""),
                "metric_col": data.get("metric_col", ""),
            }
        except Exception as e:
            print(f"Warning: could not load {fname}: {e}")
    return index


@app.on_event("startup")
async def startup():
    global runs_index
    runs_index = load_run_index()
    print(f"Loaded {len(runs_index)} saved run(s) from disk")
    if not UPLOAD_PASSWORD:
        print("WARNING: UPLOAD_PASSWORD not set — uploads accept any password. Set it in .env for production.")


def get_embeddings(texts: list[str], log_fn=None) -> np.ndarray:
    """Get embeddings from OpenAI in batches, with retry on transient failures."""
    all_embs = []
    batch_size = 100
    total_batches = (len(texts) + batch_size - 1) // batch_size
    max_retries = 3

    if log_fn:
        log_fn(f"Embedding {len(texts)} texts in {total_batches} batch(es) of {batch_size}")

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        batch_num = i // batch_size + 1
        t0 = time.time()

        for attempt in range(max_retries):
            try:
                resp = openai_client.embeddings.create(model="text-embedding-3-small", input=batch)
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                wait = 2 ** attempt
                if log_fn:
                    log_fn(f"  Batch {batch_num} failed ({e}), retrying in {wait}s...")
                time.sleep(wait)

        elapsed = time.time() - t0
        all_embs.extend([item.embedding for item in resp.data])
        if log_fn:
            log_fn(f"  Batch {batch_num}/{total_batches}: {len(batch)} texts embedded ({elapsed:.1f}s)")

    dims = len(all_embs[0]) if all_embs else 0
    if log_fn:
        log_fn(f"Embeddings complete: {len(all_embs)} vectors × {dims} dimensions")
    return np.array(all_embs)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/runs")
async def list_runs():
    """List all saved runs (metadata only, no events)."""
    runs_list = []
    for rid, meta in runs_index.items():
        runs_list.append({"run_id": rid, **meta})
    runs_list.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return {"runs": runs_list}


@app.post("/api/upload")
async def upload_csv(file: UploadFile = File(...), password: str = Form("")):
    """Accept a 2-column CSV (text + numeric metric), return a run_id."""
    # Password check
    if UPLOAD_PASSWORD and password != UPLOAD_PASSWORD:
        raise HTTPException(status_code=403, detail="Invalid password")

    content = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid CSV: {e}")

    # Detect headerless CSVs: if first row looks like data (second col is numeric string),
    # re-read without header
    if len(df.columns) >= 2:
        col1_name = str(df.columns[1])
        try:
            float(col1_name)
            # Second column name looks like a number — likely no header
            df = pd.read_csv(io.BytesIO(content), header=None, names=["text", "metric"])
        except (ValueError, TypeError):
            pass

    # Auto-detect columns: first string-like column = text, first numeric = metric
    text_col = None
    metric_col = None
    for col in df.columns:
        if text_col is None and (df[col].dtype == object or df[col].dtype.name in ("string", "str")):
            text_col = col
        if metric_col is None and pd.api.types.is_numeric_dtype(df[col]):
            metric_col = col

    # Fallback: if no object/string col found, use first column as text
    if text_col is None:
        text_col = df.columns[0]

    # Single-column CSV (or no numeric column): count duplicates as metric
    if metric_col is None:
        df[text_col] = df[text_col].astype(str).str.strip()
        df = df[df[text_col] != ""]
        # Case-insensitive dedup: lowercase for grouping, keep first-seen casing
        df["_lower"] = df[text_col].str.lower()
        # Keep the first occurrence's casing, count occurrences
        first_case = df.drop_duplicates(subset="_lower", keep="first")[[text_col, "_lower"]]
        counts = df.groupby("_lower").size().reset_index(name="count")
        deduped = first_case.merge(counts, on="_lower")
        texts = deduped[text_col].tolist()
        metrics = deduped["count"].tolist()
        metric_col = "count"
    else:
        # Two-column CSV: clean, then dedup case-insensitive and sum metrics
        df = df[[text_col, metric_col]].dropna()
        df[text_col] = df[text_col].astype(str).str.strip()
        df = df[df[text_col] != ""]
        df[metric_col] = pd.to_numeric(df[metric_col], errors="coerce").fillna(0)

        # Case-insensitive dedup: lowercase for grouping, keep first-seen casing, sum metrics
        df["_lower"] = df[text_col].str.lower()
        first_case = df.drop_duplicates(subset="_lower", keep="first")[[text_col, "_lower"]]
        summed = df.groupby("_lower")[metric_col].sum().reset_index()
        deduped = first_case.merge(summed, on="_lower")

        texts = deduped[text_col].tolist()
        metrics = deduped[metric_col].tolist()

    original_rows = len(df)
    deduped_rows = len(texts)

    # Derive a name from the uploaded filename
    name = file.filename or "untitled"
    if name.lower().endswith(".csv"):
        name = name[:-4]

    run_id = str(uuid.uuid4())[:8]
    runs[run_id] = {
        "texts": texts,
        "metrics": metrics,
        "text_col": text_col,
        "metric_col": metric_col,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "uploaded",
        "events": [],
    }

    return {
        "run_id": run_id,
        "rows": deduped_rows,
        "original_rows": original_rows,
        "text_col": text_col,
        "metric_col": metric_col,
    }


@app.websocket("/api/ws/cluster/{run_id}")
async def ws_cluster(websocket: WebSocket, run_id: str):
    """Stream clustering events over WebSocket."""
    await websocket.accept()

    if run_id not in runs:
        await websocket.send_json({"type": "error", "message": "Unknown run_id"})
        await websocket.close()
        return

    run = runs[run_id]
    if run["status"] == "complete":
        # Replay stored events
        for event in run["events"]:
            await websocket.send_json(event)
        await websocket.close()
        return

    run["status"] = "running"
    texts = run["texts"]
    metrics = run["metrics"]

    # Queue for streaming events from background threads to the WebSocket
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def enqueue(event: dict):
        """Thread-safe: enqueue an event from a background thread."""
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def send_log(message: str):
        """Thread-safe: enqueue a log event."""
        enqueue({"type": "log", "message": message})

    try:
        # Step 1: Embeddings
        await websocket.send_json({"type": "progress", "message": "Generating embeddings..."})
        await websocket.send_json({"type": "log", "message": "=== PHASE 1: EMBEDDINGS ==="})

        def do_embeddings():
            return get_embeddings(texts, log_fn=send_log)

        # Run embeddings in background, drain queue concurrently
        embed_task = asyncio.create_task(asyncio.to_thread(do_embeddings))
        while not embed_task.done():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.1)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                pass
        embeddings = embed_task.result()
        # Drain remaining
        while not queue.empty():
            await websocket.send_json(queue.get_nowait())

        # Step 2: 3D projection
        await websocket.send_json({"type": "progress", "message": "Computing 3D projection..."})
        await websocket.send_json({"type": "log", "message": "=== PHASE 2: 3D PROJECTION ==="})
        await websocket.send_json({"type": "log", "message": f"Projecting {embeddings.shape[0]} vectors from {embeddings.shape[1]}D → 3D via UMAP"})

        t0 = time.time()
        coords = await asyncio.to_thread(project_3d, embeddings)
        elapsed = time.time() - t0
        await websocket.send_json({"type": "log", "message": f"Projection complete ({elapsed:.1f}s)"})

        # Step 3: Clustering
        await websocket.send_json({"type": "progress", "message": "Starting clustering..."})
        await websocket.send_json({"type": "log", "message": "=== PHASE 3: RECURSIVE CLUSTERING ==="})

        clusterer = StepClusterer(
            embeddings=embeddings,
            texts=texts,
            metrics=metrics,
            coords=coords,
            openai_client=openai_client,
            min_cluster_size=10,
            target_leaf_count=max(10, int(len(texts) ** 0.5)),  # sqrt(n) scaling
            min_gain_rel=0.01,
            min_child_size=8,
        )

        async def drain_generator(gen):
            """Run a clustering generator in a thread, draining events to the WS."""
            def iterate():
                for event in gen:
                    enqueue(event)
                enqueue(None)  # Sentinel

            task = asyncio.create_task(asyncio.to_thread(iterate))

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    if task.done():
                        task.result()
                        break
                    continue

                if event is None:
                    break

                if event.get("type") == "log":
                    await websocket.send_json(event)
                else:
                    run["events"].append(event)
                    await websocket.send_json(event)

            # Drain remaining
            while not queue.empty():
                event = queue.get_nowait()
                if event is not None:
                    if event.get("type") == "log":
                        await websocket.send_json(event)
                    else:
                        run["events"].append(event)
                        await websocket.send_json(event)

            if not task.done():
                await task

        # Initial run
        await drain_generator(clusterer.run())

        # Save after initial clustering
        async def persist():
            await asyncio.to_thread(save_run, run_id, run)
            runs_index[run_id] = {
                "name": run.get("name", run_id),
                "created_at": run.get("created_at", ""),
                "row_count": len(texts),
                "text_col": run["text_col"],
                "metric_col": run["metric_col"],
            }

        await persist()

        # Keep WebSocket open for split_more requests
        while not clusterer.exhausted:
            try:
                msg = await websocket.receive_json()
            except WebSocketDisconnect:
                run["status"] = "complete"
                return

            if msg.get("type") == "split_more":
                n = msg.get("count", 5)
                await drain_generator(clusterer.split_more(n))
                # Re-save with new events
                await persist()
            elif msg.get("type") == "finish":
                break

        run["status"] = "complete"

    except WebSocketDisconnect:
        run["status"] = "disconnected"
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"ERROR in clustering: {tb}")
        try:
            await websocket.send_json({"type": "error", "message": str(e), "traceback": tb})
        except Exception:
            pass
        run["status"] = "error"
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


def _validate_run_id(run_id: str) -> None:
    """Raise 404 if run_id is invalid (path traversal prevention)."""
    if not RUN_ID_PATTERN.match(run_id):
        raise HTTPException(status_code=404, detail="Unknown run_id")


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str):
    """Delete a run from memory and from the local data folder."""
    _validate_run_id(run_id)

    path = os.path.join(DATA_DIR, f"{run_id}.json")
    deleted = False

    if run_id in runs:
        del runs[run_id]
        deleted = True
    if run_id in runs_index:
        del runs_index[run_id]
        deleted = True
    if os.path.exists(path):
        os.remove(path)
        deleted = True

    if deleted:
        return {"ok": True, "deleted": run_id}
    raise HTTPException(status_code=404, detail="Unknown run_id")


@app.get("/api/results/{run_id}")
async def get_results(run_id: str):
    """Fetch all stored events for a run (for reconnection). Falls back to disk."""
    _validate_run_id(run_id)

    if run_id in runs:
        return {"run_id": run_id, "status": runs[run_id]["status"], "events": runs[run_id]["events"]}

    # Try loading from disk
    path = os.path.join(DATA_DIR, f"{run_id}.json")
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            return {"run_id": run_id, "status": "complete", "events": data["events"]}
        except json.JSONDecodeError as e:
            print(f"Warning: corrupted run file {run_id}.json: {e}")
            raise HTTPException(status_code=500, detail="Run file corrupted")

    raise HTTPException(status_code=404, detail="Unknown run_id")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
