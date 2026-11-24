# Similarity Browser

Interactive 3D visualization tool for hierarchical text clustering. Upload a CSV of text + numeric metric, and the tool embeds, projects, and recursively clusters the data in real time — rendering an explorable 3D scatter plot with metric-scaled nodes, animated edges, and a step-by-step clustering walkthrough.

## Quick Start

### 1. Environment

```bash
# Create .env in the project root
echo "OPENAI_API_KEY=sk-..." > .env
echo "UPLOAD_PASSWORD=your-password" >> .env
```

### 2. Start the backend

```bash
cd backend
pip install -r requirements.txt
python server.py
```

Backend runs on `http://localhost:8000`.

### 3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:5173`.

### 4. Upload a CSV

Open the browser, enter the upload password, and drag a CSV onto the upload zone. The tool auto-detects columns and starts processing.

### Dev scripts

```bash
# Selective KV upload (choose which runs to upload)
python3 scripts/upload-to-kv.py

# Dev menu: O = open localhost, U = upload to KV, B = open backend
python3 scripts/dev-menu.py
```

---

## Architecture

```
CSV Upload → OpenAI Embeddings → PCA+t-SNE(3D) → Recursive K-Means → WebSocket Stream → 3D Visualization
```

### Processing Pipeline

1. **Upload** — CSV parsed, text deduped (case-insensitive, metrics summed), columns auto-detected
2. **Embedding** — OpenAI `text-embedding-3-small` in batches of 100
3. **Projection** — PCA(50) → t-SNE to 3D coordinates, normalized to [-1, 1]
4. **Clustering** — Recursive K-Means (k=2,3) with gain thresholding, streamed over WebSocket
5. **Labeling** — GPT-4o-mini generates canonical labels for each cluster (biased toward highest-metric queries)
6. **Pause/Resume** — Clusterer pauses at target leaf count; client can request more splits

### Backend (Python / FastAPI)

| File | Purpose |
|------|---------|
| `server.py` | FastAPI entry point. CSV upload with password auth, embedding, projection, WebSocket streaming, run persistence to disk. |
| `clustering.py` | `StepClusterer` class. Resumable recursive K-Means (k=2,3) with inertia gain thresholding. Yields `init`, `step`, `paused`, `complete` events. Generates LLM-based canonical labels via GPT-4o-mini. Supports `split_more()` for interactive refinement. |
| `projector.py` | Dimensionality reduction via PCA(50) → t-SNE to 3D, normalized to [-1, 1]. |
| `requirements.txt` | Python dependencies. |

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/upload` | POST | Accept CSV + password, return `run_id`. Auto-detects columns and headerless CSVs. Single-column CSVs use duplicate count as metric. |
| `/api/ws/cluster/{run_id}` | WebSocket | Stream clustering events (`init` → `step` x N → `paused`). Stays open for `split_more` requests. |
| `/api/results/{run_id}` | GET | Fetch stored events for reconnection/replay. Falls back to disk. |
| `/api/runs` | GET | List all saved runs (metadata only). |
| `/api/health` | GET | Health check. |

### WebSocket Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `init` | Server → Client | All points with coordinates, total steps estimate, root cluster |
| `step` | Server → Client | One split: parent removed, children added with member queries |
| `paused` | Server → Client | Target reached, `can_split: true`, awaiting client decision |
| `complete` | Server → Client | No more splittable clusters |
| `log` | Server → Client | Process log message (displayed in terminal) |
| `progress` | Server → Client | Status update (embedding/projection/clustering phase) |
| `split_more` | Client → Server | Request N additional split steps |

### Frontend (Svelte 5 / TypeScript / Three.js)

#### Components (`frontend/src/lib/`)

| Component | Purpose |
|-----------|---------|
| `Upload.svelte` | Home screen with saved run list, password gate, drag-and-drop CSV upload. Opens WebSocket, writes log events to `terminalLines` store, buffers clustering events to `eventBuffer`. |
| `Map3D.svelte` | 3D scatter plot via Three.js. Metric-scaled nodes (sqrt scale), cluster-colored points, star-topology + KNN edges, floating 3D labels. TrackballControls for free rotation (no gimbal lock), pinch-to-zoom. Raycaster for hover/click with cluster pinning. |
| `Sidebar.svelte` | Left panel (1/3 viewport). Sorted cluster list with color bars, metric totals, percentages. Click to expand inline detail (size, depth, breadcrumb, top queries). TOP 10/20/ALL dropdown filter. SPLIT MORE button for interactive refinement. Resizable via drag handle. |
| `Terminal.svelte` | Process log panel. Reads from `terminalLines` store — displays embedding, projection, and clustering progress in real time. |
| `HUD.svelte` | Heads-up display overlay. Title, depth, cluster count, status indicator, mouse coordinates, step counter with manual navigation arrows. |
| `ScrollDriver.svelte` | Maps mouse wheel scroll to clustering step progression (150px per step). Syncs with HUD arrow navigation. |
| `Tooltip.svelte` | Floating tooltip following mouse cursor. Shows hovered point's text and metric value. |

#### Stores (`frontend/src/stores/cluster.ts`)

| Store | Type | Purpose |
|-------|------|---------|
| `points` | Writable | All data points with coordinates and metrics |
| `steps` | Writable | Accumulated clustering step events |
| `currentStep` | Writable | Current depth step (controlled by scroll) |
| `totalSteps` | Writable | Total steps completed |
| `status` | Writable | Connection status: idle, uploading, embedding, projecting, clustering, complete, error |
| `visibleClusters` | Derived | Clusters visible at current step |
| `pointClusterMap` | Derived | Point ID → cluster ID lookup at current step |
| `pinnedClusterIds` | Writable | Multi-select cluster pinning |
| `hoveredCluster` | Writable | Sidebar hover → map highlighting |
| `sidebarWidth` | Writable | Resizable sidebar width (default: 1/3 viewport) |
| `wsRef` | Writable | WebSocket reference for split_more requests |
| `canSplitMore` | Writable | Whether more splits are available |
| `terminalLines` | Writable | Process log lines (persists across component mount/unmount) |
| `eventBuffer` | Writable | Buffered events for late-mounting components |
| `savedRuns` | Writable | Saved run metadata from server |

---

## Clustering Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `target_leaf_count` | √n of total rows (at least 10) | Target number of leaf clusters before pausing |
| `min_cluster_size` | 10 | Minimum members before a cluster can be split |
| `min_child_size` | 8 | Minimum size for child clusters (unless metric threshold met) |
| `min_gain_rel` | 0.01 | Minimum relative inertia improvement to keep a split |

### Dual Child Validity

A child cluster is valid if it has **either** enough members (`>= min_child_size`) **or** carries enough metric weight (`>= 5%` of parent's total metric). This allows small but high-value groups to survive as leaf clusters.

---

## Interaction Guide

| Action | Effect |
|--------|--------|
| **Scroll** (mouse wheel) | Navigate clustering steps (depth progression) |
| **‹ / › arrows** (bottom-right) | Step backward/forward one clustering step |
| **Pinch-to-zoom** (trackpad) | Smooth zoom camera in/out (1× to 1.5×) |
| **Click + Drag** (on 3D map) | Rotate camera freely (no pole lock) |
| **Hover** (on a point) | Show tooltip with text and metric |
| **Click** (on a point) | Pin its cluster; click again to unpin |
| **Click empty space** | Clear all pinned clusters |
| **Click** (sidebar cluster) | Toggle inline detail with top queries |
| **TOP 10/20/ALL** (sidebar dropdown) | Filter visible cluster count |
| **SPLIT MORE** (sidebar button) | Request 5 additional split steps from server |
| **Drag sidebar edge** | Resize sidebar (1/4 to 1/2 viewport) |

---

## Input Format

A CSV with text and an optional numeric metric:

- **2-column CSV**: Column 1 = text, Column 2 = number. Header auto-detected.
- **1-column CSV**: Text only. Duplicate count is used as the metric.
- Case-insensitive deduplication is applied (metrics summed for duplicates).

---

## Run Persistence

Completed runs are saved to `backend/data/runs/` as JSON files containing all clustering events. Saved runs appear in the home screen sidebar and can be replayed instantly without re-processing.

---

## Tools & Libraries

### Backend

| Tool | Purpose |
|------|---------|
| **FastAPI** | Async web framework with REST + WebSocket support |
| **Uvicorn** | ASGI server |
| **OpenAI SDK** | `text-embedding-3-small` for embeddings, `gpt-4o-mini` for cluster labels |
| **scikit-learn** | K-Means clustering |
| **NumPy / pandas** | Numerical operations and CSV parsing |
| **scikit-learn (t-SNE)** | 3D dimensionality reduction (PCA → t-SNE pipeline) |

### Frontend

| Tool | Purpose |
|------|---------|
| **Svelte 5** | Reactive UI with runes (`$state`, `$derived`, `$effect`) |
| **TypeScript** | Type safety across all components and stores |
| **Three.js** | WebGL 3D rendering (Points, BufferGeometry, ShaderMaterial, TrackballControls) |
| **Vite** | Dev server with HMR |
| **D3.js** | Utility functions |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key for embeddings and cluster labeling |
| `UPLOAD_PASSWORD` | No | Password required to upload new CSVs (empty = no auth) |
