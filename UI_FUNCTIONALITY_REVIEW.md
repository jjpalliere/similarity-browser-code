# Similarity Browser — UI Functionality Review

**Scope:** All UI features, server (Cloudflare Pages) vs localhost (Vite dev + Python backend)

---

## Environment Summary

| Env | Frontend | Backend | Data Source |
|-----|----------|---------|-------------|
| **Localhost** | Vite dev (localhost:5173) | Python FastAPI (localhost:8000) | In-memory + `backend/data/runs/` |
| **Server** | Cloudflare Pages (static + Functions) | None | KV only |

**Key env vars:**
- `VITE_API_BASE` — Python backend URL (e.g. `http://localhost:8000`). Empty on server.
- `VITE_R2_BASE` — Optional override for KV API (e.g. if different origin). Usually empty; `/api/*` uses same origin.

---

## Feature Matrix: Server vs Localhost

| Feature | Localhost | Server | Notes |
|---------|-----------|--------|-------|
| **Auth gate** | Bypassed (auto-login) | Password required | localhost/127.0.0.1 skips auth |
| **List saved runs** | ✅ Python + (KV if R2) | ✅ KV only | Merged on localhost |
| **Load saved run** | ✅ Python first, then KV | ✅ KV | Replay from stored events |
| **Delete run** | ⚠️ KV only | ✅ KV | Python backend has no DELETE |
| **Create new run (upload)** | ✅ | ❌ | NEW RUN hidden when no backend |
| **WebSocket clustering** | ✅ | ❌ | Requires Python backend |
| **SPLIT MORE** | ⚠️ Live only | ❌ | Dead for saved runs (no WS) |
| **3D map, scroll, HUD, tooltip** | ✅ | ✅ | Same for loaded runs |
| **Terminal log** | ✅ Live only | Empty | Not replayed for saved runs |

---

## UI Features — Detailed

### 1. Authentication Gate

| Aspect | Localhost | Server |
|--------|-----------|--------|
| **Visibility** | Bypassed | Full-screen password form |
| **Check** | `location.hostname === "localhost"` → auto-auth | Cookie `sb_auth=1` or submit password |
| **API** | N/A | `POST /api/auth` (Pages Function) |
| **Default password** | N/A | `"similarity"` if `SITE_PASSWORD` unset |

**Behavior:** On localhost, user never sees the login screen. On server, must enter password; cookie lasts 24h.

---

### 2. Run List (Upload Sidebar)

| Aspect | Localhost | Server |
|--------|-----------|--------|
| **Source** | Python `GET /api/runs` + KV `GET /api/runs` (merged) | KV `GET /api/runs` only |
| **Display** | Run name, row count, date | Same |
| **Empty state** | "No saved runs" | Same |
| **+ NEW RUN button** | Shown if `backendUp` | **Hidden** (backend always down) |

**Issue:** On server, if KV is empty, user sees "No saved runs" and no way to create runs. The app is effectively read-only.

---

### 3. Load Saved Run

| Aspect | Localhost | Server |
|--------|-----------|--------|
| **Source** | Python `GET /api/results/{id}` first, else KV `GET /api/runs/{id}` | KV `GET /api/runs/{id}` |
| **Flow** | Click run → fetch events → replay → show map | Same |
| **Auto-load** | Latest run on first load | Same (if runs exist) |

**Behavior:** Works identically once data is fetched. Events are replayed into stores; Map3D renders.

---

### 4. Delete Run

| Aspect | Localhost | Server |
|--------|-----------|--------|
| **Python backend** | `DELETE /api/runs/{id}` — **not implemented** (404) | N/A |
| **KV** | `DELETE /api/runs/{id}` (Pages Function) | Same |
| **Result** | Delete works only for KV-sourced runs | Delete works for all runs |

**Issue:** On localhost, runs created via Python are stored in `backend/data/runs/` and in memory. Delete calls the Python backend first (404), then falls back to KV. KV does not contain those runs, so delete fails. User sees no feedback beyond the run staying in the list.

---

### 5. Create New Run (Upload CSV)

| Aspect | Localhost | Server |
|--------|-----------|--------|
| **+ NEW RUN** | Shown | **Hidden** |
| **Upload flow** | Password → drop CSV → `POST /api/upload` → WebSocket | N/A |
| **Backend** | Python only | None |

**Flow when backend available:**
1. Click + NEW RUN → password prompt (Upload password, not site password)
2. Enter password → upload zone
3. Drop CSV → `POST ${API_BASE}/api/upload` with file + password
4. On success → `startClustering(run_id)` opens WebSocket
5. Events stream; map updates live

**Server:** No upload endpoint exists. NEW RUN is hidden when `backendUp` is false, so users cannot reach this flow.

---

### 6. WebSocket Clustering (Live)

| Aspect | Localhost | Server |
|--------|-----------|--------|
| **URL** | `ws://localhost:8000/api/ws/cluster/{run_id}` | N/A |
| **Events** | init, step, log, progress, paused, complete | N/A |
| **Terminal** | Populated with log/progress | N/A |

**Behavior:** Only works with Python backend. Streams embedding → projection → clustering in real time.

---

### 7. SPLIT MORE Button

| Aspect | Localhost | Server |
|--------|-----------|--------|
| **Visibility** | When `canSplitMore && status === complete` | Same |
| **Requires** | WebSocket open (`wsRef`, `readyState === OPEN`) | Same |
| **Live run** | Works (WS still open) | N/A |
| **Saved run** | **Does nothing** (no WS) | Same |

**Issue:** `canSplitMore` is set from the `paused` event when the clusterer can split further. For saved runs, we replay events but never open a WebSocket. `wsRef` is null. The button appears (from replayed `paused`), but `onSplitMore` returns immediately. No feedback. **Recommendation:** Hide SPLIT MORE when `!wsRef` or when run was loaded from storage.

---

### 8. 3D Map (Map3D)

| Feature | Localhost | Server |
|---------|-----------|--------|
| **Render** | ✅ | ✅ |
| **Orbit (drag)** | ✅ | ✅ |
| **Pinch zoom** | ✅ | ✅ |
| **Point hover → tooltip** | ✅ | ✅ |
| **Point click → pin cluster** | ✅ | ✅ |
| **Cluster colors, edges, labels** | ✅ | ✅ |

**Behavior:** Identical for any loaded run, regardless of source.

---

### 9. Cluster Sidebar

| Feature | Localhost | Server |
|---------|-----------|--------|
| **List clusters** | ✅ | ✅ |
| **TOP 10/20/ALL** | ✅ | ✅ |
| **Click → pin + expand detail** | ✅ | ✅ |
| **Hover → highlight on map** | ✅ | ✅ |
| **Resize (drag edge)** | ✅ | ✅ |

**Behavior:** Same for both. Sidebar is hidden when `innerWidth < 700` (collapsed mode).

---

### 10. Scroll-Driven Step Navigation

| Feature | Localhost | Server |
|---------|-----------|--------|
| **Mouse wheel → step** | ✅ | ✅ |
| **HUD arrows ‹ ›** | ✅ | ✅ |
| **Scroll in sidebar** | Ignored (doesn’t change step) | Same |

**Behavior:** ScrollDriver captures wheel (except Cmd/Ctrl for zoom). 150px per step.

---

### 11. HUD Overlay

| Element | Localhost | Server |
|---------|-----------|--------|
| **FIG 1.0 // NODES** | ✅ | ✅ |
| **DEPTH, CLUSTERS, STEP** | ✅ | ✅ |
| **Status (COMPLETE / READY)** | ✅ | ✅ |
| **X / Y coordinates** | Always 0.000 | Same (never updated) |
| **Step arrows ‹ ›** | ✅ | ✅ |

**Issue:** `mouseDataX` / `mouseDataY` are never written; HUD always shows `0.000`.

---

### 12. Tooltip

| Aspect | Localhost | Server |
|--------|-----------|--------|
| **Trigger** | Hover point on map | Same |
| **Content** | Text + metric | Same |
| **Position** | Cursor + 12px offset | Same |

**Note:** When clusters are pinned, tooltip only shows for points in pinned clusters.

---

### 13. Terminal (Process Log)

| Aspect | Localhost | Server |
|--------|-----------|--------|
| **Live clustering** | Populated | N/A |
| **Saved run** | Empty | Empty |
| **Visibility** | When uploading/embedding/projecting/clustering | Same |

**Issue:** Log events are not replayed when loading a saved run. Terminal stays at "Waiting for process...".

---

### 14. Back Button (← RUNS)

| Aspect | Localhost | Server |
|--------|-----------|--------|
| **Action** | `resetStores()` → back to run list | Same |
| **Visibility** | During loading and when map shown | Same |

---

### 15. Responsive / Collapsed Mode

| Condition | Behavior |
|-----------|----------|
| `innerWidth < 700` | Map3D hidden, HUD hidden, Sidebar full-width |
| `innerWidth >= 700` | Full layout |

**Issue:** On narrow screens, user sees the cluster sidebar but no map. Scroll/arrows still change steps, but there is nothing to look at.

---

## Data Flow Summary

### Localhost (with Python backend)

```
fetchRuns()     → GET localhost:8000/api/runs (then merge KV if R2_BASE)
fetchRunEvents  → GET localhost:8000/api/results/{id} (then KV)
deleteRun       → DELETE localhost:8000/api/runs/{id} (404) → DELETE /api/runs/{id} (KV, usually 404)
upload          → POST localhost:8000/api/upload
clustering      → WS localhost:8000/api/ws/cluster/{id}
```

### Server (Cloudflare Pages)

```
fetchRuns()     → GET /api/runs (Pages Function → KV)
fetchRunEvents  → GET /api/runs/{id} (Pages Function → KV)
deleteRun       → DELETE /api/runs/{id} (Pages Function → KV)
upload          → Not available
clustering      → Not available
```

---

## Recommendations

1. **Server:** Add a clear message when there are no runs and no backend (e.g. "Upload requires the local backend. Run the Python server to create new runs.").
2. **SPLIT MORE:** Hide when `!wsRef` so it doesn’t appear for saved runs.
3. **Delete on localhost:** Implement `DELETE /api/runs/{id}` on the Python backend for local runs.
4. **HUD coordinates:** Either implement mouse→data projection or remove the X/Y display.
5. **Terminal for saved runs:** Optionally replay log events into `terminalLines` when loading.
6. **Collapsed mode:** Consider a minimal map or a message that the map is hidden on small screens.
