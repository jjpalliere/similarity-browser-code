# Similarity Browser — Code Review

**Date:** March 15, 2025 (Updated)  
**Scope:** Backend (Python/FastAPI), Frontend (Svelte 5/Three.js), data flow, security, robustness

---

## Executive Summary

The Similarity Browser is a well-architected full-stack tool for hierarchical text clustering with 3D visualization. The codebase is generally clean and follows good patterns. This review identifies **2 critical bugs**, several **medium-priority issues**, and a number of **minor improvements**.

---

## Critical Bugs

### 1. **NameError in `clustering.py` — Canonical Label Fallback** ✅ FIXED

**File:** `backend/clustering.py` (line 303)

**Issue:** When LLM-based canonical label generation fails, the fallback referenced an undefined variable `top`. **Fixed** to use `indexed[0][1][:80]`.

---

### 2. **State Corruption When Switching Saved Runs**

**File:** `frontend/src/lib/Upload.svelte` — `loadSavedRun()`

**Issue:** When loading run B after run A (without clicking "← RUNS" first), the function:
- Appends B's events to `eventBuffer` without clearing A's events
- Never clears `$steps` on init — Map3D's init handler replaces `$points` but leaves old steps
- Result: mixed clusters from both runs, wrong `pointClusterMap`, corrupted visualization

**Fix:** Call `resetStores()` at the start of `loadSavedRun()` before fetching and processing events. Also add `$steps = []` in Map3D's init handler when handling a new run (belt-and-suspenders).

---

### 3. **`loadingRun` Never Cleared on Success**

**File:** `frontend/src/lib/Upload.svelte` — `loadSavedRun()`

**Issue:** `loadingRun` is set to `run.run_id` at the start but only cleared in the `catch` block. On success, it stays set forever, so the run item shows a permanent loading spinner.

**Fix:** Add `loadingRun = ""` at the end of the `try` block (or in a `finally`).

---

## Medium-Priority Issues

### 4. **HUD Mouse Coordinates Never Updated**

**Files:** `frontend/src/stores/viewport.ts`, `frontend/src/lib/HUD.svelte`

**Issue:** `mouseDataX` and `mouseDataY` are defined in the viewport store but **never written to**. The HUD displays "X: 0.000 Y: 0.000" at all times.

**Fix:** Map3D (or a shared mouse handler) should project the mouse position into 3D data space and update these stores on `mousemove`. Alternatively, remove the display if not needed.

---

### 5. **Backend Missing DELETE Endpoint for Runs**

**File:** `backend/server.py`

**Issue:** `dataService.deleteRun()` calls `DELETE /api/runs/{runId}` when using the local backend, but the backend only exposes:

- `GET /api/health`
- `GET /api/runs`
- `POST /api/upload`
- `WebSocket /api/ws/cluster/{run_id}`
- `GET /api/results/{run_id}`

**Impact:** Deleting runs fails with 404 when using the local Python backend. Delete only works when using Cloudflare Pages/KV.

**Fix:** Add `DELETE /api/runs/{run_id}` that removes the run from memory and deletes the JSON file from `data/runs/`.

---

### 6. **Path Traversal Risk in `get_results`**

**File:** `backend/server.py` (lines 401–414)

**Issue:** `run_id` comes from the URL path and is used directly in `os.path.join(DATA_DIR, f"{run_id}.json")`. A malicious request like `/api/results/../../../etc/passwd` could escape the data directory.

**Mitigation:** Run IDs are generated as `uuid.uuid4()[:8]` (8 hex chars). Validate that `run_id` matches `^[a-f0-9]{8}$` before use.

---

### 7. **Incorrect Log Message — UMAP vs t-SNE**

**File:** `backend/server.py` (line 284)

**Issue:** The log says "Projecting via UMAP" but `projector.py` uses **PCA + t-SNE**:

```python
await websocket.send_json({"type": "log", "message": f"Projecting ... via UMAP"})
```

**Fix:** Change to "via PCA + t-SNE" for accuracy.

---

### 8. **`visibleClusters` Root Cluster at Step 0**

**File:** `frontend/src/stores/cluster.ts`

**Issue:** At `currentStep === 0`, `visibleClusters` returns `[]`. The root cluster from the `init` event is never represented in `steps`, so it never appears in `visibleClusters`. At step 0, the user sees no clusters and all points are uncolored.

**Assessment:** This may be intentional (step 0 = pre-split view). If the design intends to show the root at step 0, the init event’s `root_cluster` would need to be folded into the step/cluster model.

---

### 9. **Auth Default Password**

**File:** `frontend/functions/api/auth.ts` (line 8)

**Issue:** If `SITE_PASSWORD` is not set, the default is `"similarity"`. Deploying without configuring the env var leaves a weak, guessable password.

---

### 10. **KV Metadata Missing `text_col` / `metric_col`**

**Files:** `frontend/functions/api/runs/index.ts`, `scripts/upload-to-kv.py`

**Issue:** The upload-to-kv script only stores `run_id`, `name`, `created_at`, `row_count` in KV metadata. The fallback in `index.ts` fetches full data but still only returns those four fields. `RunMeta` expects `text_col` and `metric_col` — they may be empty for KV-sourced runs.

---

## Minor Issues & Weaknesses

### 11. **Duplicate `class` Attribute in Upload.svelte**

**File:** `frontend/src/lib/Upload.svelte` (line 250)

```svelte
<button class="new-run-btn" onclick={onNewRun} class:active={mode !== "home"}>
```

**Issue:** Two `class`-related attributes. Svelte merges them, but the first should be the base class and the second the conditional. Consider `class="new-run-btn"` + `class:active={...}` for clarity (current code is valid but slightly redundant).

---

### 12. **No File Size Limit on Upload**

**File:** `backend/server.py`

**Issue:** The entire CSV is read into memory with `await file.read()`. A very large file could cause OOM or slow the server.

**Suggestion:** Add a max size (e.g. 10MB) and reject larger uploads with 413.

---

### 13. **CORS `allow_origins=["*"]` with `allow_credentials=True`**

**File:** `backend/server.py` (lines 28–33)

**Issue:** `allow_origins=["*"]` with `allow_credentials=True` is invalid per the CORS spec. Browsers may reject it. For local dev, `["http://localhost:5173", "http://127.0.0.1:5173"]` is safer.

---

### 14. **WebSocket Error Handling — Status Not Reset**

**File:** `backend/server.py` (lines 378–391)

**Issue:** On exception, `run["status"]` is set to `"error"`, but the run stays in `runs`. A reconnect would still see the failed run. Consider clearing or marking it so clients don’t retry indefinitely.

---

### 15. **`sidebarWidth` Initial Value Uses `window` at Module Load**

**File:** `frontend/src/stores/cluster.ts` (line 62)

```typescript
export const sidebarWidth = writable<number>(Math.floor(window.innerWidth / 3));
```

**Issue:** During SSR (if ever used), `window` is undefined. For a client-only Svelte app this is fine, but it’s brittle if the app is ever pre-rendered.

---

### 16. **ScrollDriver `maxSteps` Edge Case**

**File:** `frontend/src/lib/ScrollDriver.svelte`

**Issue:** `maxSteps` uses `$totalSteps || $steps.length || 1`. During live clustering, `totalSteps` can be 0 before the first step, so `$steps.length` is used. After `complete`, `totalSteps` is set. Logic is correct but could be documented for clarity.

---

### 17. **Three.js `depthWrite: false` on Points**

**File:** `frontend/src/lib/Map3D.svelte`

**Issue:** Points use `depthWrite: false` for correct transparency. With many overlapping points, draw order can look inconsistent. Acceptable tradeoff for transparency; no change needed unless visual issues appear.

---

### 18. **No Explicit Cleanup of Runs from Memory**

**File:** `backend/server.py`

**Issue:** Completed runs stay in the `runs` dict. Over time, memory grows. Consider evicting runs after completion (since they’re persisted to disk) or adding a TTL.

---

### 19. **Terminal Log Not Replayed for Saved Runs**

**File:** `frontend/src/lib/Upload.svelte` — `loadSavedRun()`

**Issue:** When loading a saved run, `log` events from the event stream are not pushed to `terminalLines`. The terminal stays empty. Live clustering populates it; saved runs do not. May be intentional, but inconsistent.

---

### 20. **Background3D Cleanup Order**

**File:** `frontend/src/lib/Background3D.svelte`

**Issue:** The animation loop is cancelled in `onDestroy`, but the `onMount` return only removes event listeners. Svelte runs onMount cleanup before onDestroy. A frame or two of animation may still run after listeners are removed. Low impact; acceptable.

---

## Documentation Drift

| Doc | Issue |
|-----|-------|
| `DOCS.md` | Describes 2D canvas and `Map.svelte`; app uses 3D and `Map3D.svelte` |
| `DOCS.md` | Mentions `viewport.ts` stores (`panX`, `panY`, `zoom`) that Map3D does not use (it uses TrackballControls) |
| `README.md` | Says `target_leaf_count` is "~4% of total rows"; code uses `max(10, int(len(texts)**0.5))` (sqrt scaling) |
| `PLAN.md` | References UMAP; implementation uses t-SNE |

---

## Positive Observations

- Clear separation of concerns: clustering, projection, and API are well isolated.
- WebSocket streaming with a generator pattern is a good fit for incremental clustering.
- Svelte 5 runes and derived stores are used appropriately.
- Three.js setup (TrackballControls, custom shaders, point sizing) is solid.
- Event buffering for late-mounting Map3D handles replay correctly.
- Dual data sources (local backend + KV) in `dataService` is flexible for dev vs prod.

---

## Recommended Fix Order

1. **Immediate:** Fix `loadSavedRun` — add `resetStores()` at start, clear `loadingRun` on success.
2. **Immediate:** Add `$steps = []` in Map3D init handler when processing a new run.
3. **Short-term:** Add backend `DELETE /api/runs/{run_id}`.
4. **Short-term:** Validate `run_id` in `get_results` and WebSocket handler.
5. **Medium-term:** Fix or remove HUD mouse coordinates.
6. **Medium-term:** Correct UMAP → t-SNE log message.
7. **Ongoing:** Align DOCS.md and README.md with the current 3D implementation.
