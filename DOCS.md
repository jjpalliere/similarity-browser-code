# Similarity Browser — Technical Documentation

A full-stack interactive visualization tool that takes a CSV of text queries + numeric metrics, clusters them semantically using AI embeddings, and renders an animated 2D map you can scroll through step by step.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Data Flow: End to End](#2-data-flow-end-to-end)
3. [Backend: Python + FastAPI](#3-backend-python--fastapi)
   - 3.1 [CSV Upload & Validation](#31-csv-upload--validation)
   - 3.2 [Embedding Generation](#32-embedding-generation)
   - 3.3 [2D Projection (PCA + t-SNE)](#33-2d-projection-pca--t-sne)
   - 3.4 [Recursive Clustering](#34-recursive-clustering)
   - 3.5 [WebSocket Streaming Protocol](#35-websocket-streaming-protocol)
4. [Frontend: Svelte 5 + Canvas](#4-frontend-svelte-5--canvas)
   - 4.1 [Store Architecture](#41-store-architecture)
   - 4.2 [Upload Flow](#42-upload-flow)
   - 4.3 [Canvas Rendering Pipeline](#43-canvas-rendering-pipeline)
   - 4.4 [Scroll-Driven Navigation](#44-scroll-driven-navigation)
   - 4.5 [Interactions (Hover, Click, Pan, Zoom)](#45-interactions-hover-click-pan-zoom)
   - 4.6 [HUD Overlay](#46-hud-overlay)
   - 4.7 [Visual Design System](#47-visual-design-system)
5. [File Reference](#5-file-reference)
6. [Running Locally](#6-running-locally)

---

## 1. Architecture Overview

```
┌─────────────────────┐         ┌──────────────────────────────┐
│   Svelte Frontend   │  HTTP   │      FastAPI Backend          │
│   (Vite, port 5173) │────────▶│      (Uvicorn, port 8000)    │
│                     │         │                              │
│  Upload.svelte      │  POST   │  /api/upload                 │
│    sends CSV file ──────────▶│    validates, stores in RAM  │
│                     │         │                              │
│  Upload.svelte      │   WS    │  /api/ws/cluster/{run_id}    │
│    opens WebSocket ─────────▶│    1. embeddings (OpenAI)    │
│                     │         │    2. PCA + t-SNE projection │
│  Map.svelte         │◀────────│    3. recursive clustering   │
│    receives events  │  JSON   │    4. streams events back    │
│    renders canvas   │         │                              │
└─────────────────────┘         └──────────────────────────────┘
                                          │
                                          ▼
                                 ┌─────────────────┐
                                 │  OpenAI API      │
                                 │  - embeddings    │
                                 │  - cluster labels│
                                 └─────────────────┘
```

**Tech stack:**
- **Backend**: Python 3, FastAPI, scikit-learn (KMeans, PCA, t-SNE), OpenAI API
- **Frontend**: Svelte 5 (with runes: `$state`, `$derived`, `$effect`), Vite 8, TypeScript, HTML5 Canvas
- **Communication**: REST for upload, WebSocket for real-time clustering stream

---

## 2. Data Flow: End to End

Here's exactly what happens from the moment you drop a CSV to the final rendered map:

### Step 1 — Upload

The user drops a CSV onto the upload zone. The file is sent via `POST /api/upload` as multipart form data. The server:

1. Parses the CSV with pandas
2. Auto-detects a headerless CSV (if the second column name parses as a number, it re-reads with `header=None`)
3. Finds the first string-like column (text) and first numeric column (metric)
4. Strips empty rows, generates a random `run_id`, stores the data in memory
5. Returns `{ run_id, rows, text_col, metric_col }`

### Step 2 — WebSocket Connection

The frontend opens a WebSocket to `/api/ws/cluster/{run_id}`. The server begins a three-stage pipeline, sending progress updates as it goes:

```
"Generating embeddings..."  →  "Computing 2D projection..."  →  "Starting clustering..."
```

### Step 3 — Embeddings

Each text query is sent to OpenAI's `text-embedding-3-small` model in batches of 100. This returns a 1536-dimensional vector per query. For 951 queries, this takes about 5-10 seconds.

### Step 4 — 2D Projection

The 1536-dimensional embeddings are reduced to 2D coordinates:

1. **PCA** reduces from 1536 → 50 dimensions (fast linear projection, preserves most variance)
2. **t-SNE** reduces from 50 → 2 dimensions (non-linear, preserves local neighborhoods)
3. Both axes are **normalized to [-1, 1]** so data fills the screen regardless of scale

The t-SNE step uses cosine distance (matching the embedding space) and PCA initialization for stability.

### Step 5 — Recursive Clustering

The `StepClusterer` processes all points through a recursive splitting loop:

1. All points start in one root cluster
2. The largest cluster (by total metric) is selected for splitting
3. KMeans is tried with k=2 and k=3, and the better split is kept. If its inertia gain is too small (<1%), the cluster is marked terminal
4. Each child cluster gets a canonical label from GPT-4o-mini (one LLM call per cluster)
5. A `step` event is yielded with the new child clusters
6. Repeat until √n leaf clusters exist (n = number of rows, at least 10), then pause; more splits run on request (split_more)

### Step 6 — Event Streaming

Each event is sent over the WebSocket as JSON:

```
init    → all points with (x, y) coordinates
step    → each cluster split with child details
complete → final step count
```

### Step 7 — Frontend Rendering

The `Map.svelte` component receives events via a `CustomEvent` bridge:

1. On `init`: create animated point objects, start render loop
2. On each `step`: append to steps store, auto-advance `currentStep`
3. The canvas render loop runs at 60fps, drawing grid, points, boundaries, and labels
4. Points spring-animate from the center outward on first load

### Step 8 — User Exploration

Once clustering completes, the user can:

- **Scroll** to navigate through clustering depth (each scroll step reveals deeper splits)
- **Hover** points to see their text and metric
- **Click** near a cluster to open a detail panel with top queries
- **Pan** by dragging, **zoom** with Cmd/Ctrl + scroll

---

## 3. Backend: Python + FastAPI

### 3.1 CSV Upload & Validation

**File**: `backend/server.py` — `POST /api/upload`

The upload endpoint handles messy real-world CSVs:

```python
# Headerless detection: if the second column name is a number,
# the "header" row is actually data
col1_name = str(df.columns[1])
try:
    float(col1_name)
    df = pd.read_csv(io.BytesIO(content), header=None, names=["text", "metric"])
except (ValueError, TypeError):
    pass
```

Column detection walks all columns looking for the first string-like and first numeric column. This means the CSV can have extra columns, different names, or mixed ordering — it'll find the right ones.

After detection, rows with empty text or missing metrics are dropped, and the cleaned data is stored in an in-memory dict keyed by `run_id`.

### 3.2 Embedding Generation

**File**: `backend/server.py` — `get_embeddings()`

```python
def get_embeddings(texts: list[str]) -> np.ndarray:
    all_embs = []
    for i in range(0, len(texts), 100):  # batch_size = 100
        batch = texts[i : i + 100]
        resp = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=batch
        )
        all_embs.extend([item.embedding for item in resp.data])
    return np.array(all_embs)
```

- Model: `text-embedding-3-small` (1536 dimensions, fast, cheap)
- Batched in groups of 100 to stay within API limits
- Returns an (N, 1536) numpy array

### 3.3 2D Projection (PCA + t-SNE)

**File**: `backend/projector.py`

The projection pipeline converts high-dimensional embeddings to plottable 2D coordinates:

```
Embeddings (N × 1536) → PCA (N × 50) → t-SNE (N × 2) → Normalize to [-1, 1]
```

**Why two steps?**
- PCA is fast and removes noise dimensions, making t-SNE much faster
- t-SNE preserves local cluster structure (similar queries stay close together)
- Together they run in seconds instead of minutes

**Key parameters:**
| Parameter | Value | Why |
|-----------|-------|-----|
| PCA components | 50 | Balance between speed and information retention |
| t-SNE perplexity | 30 (or N-1 if small) | Standard choice, balances local vs global structure |
| t-SNE metric | cosine | Matches embedding space semantics |
| t-SNE init | pca | Deterministic, stable starting point |
| t-SNE iterations | 1000 | Enough for convergence |

**Small dataset fallback**: If fewer than 6 points, PCA alone is used (t-SNE needs more samples than perplexity).

**Normalization**: Both x and y are independently scaled to [-1, 1], centering the point cloud on screen.

### 3.4 Recursive Clustering

**File**: `backend/clustering.py`

This is the core algorithm. It implements a top-down recursive splitting strategy using KMeans:

```
                    [all queries]
                    /           \
          [cluster A]         [cluster B]
          /        \              |
    [leaf 1]   [leaf 2]      [terminal]
```

**The `StepClusterer` class:**

```python
class StepClusterer:
    def __init__(self,
        embeddings,          # (N, D) embedding vectors
        texts,               # original query strings
        metrics,             # numeric values per query
        coords_2d,           # (N, 2) projected coordinates
        openai_client,       # for canonical labels
        min_cluster_size=10, # don't split clusters smaller than this
        target_leaf_count=max(10, int(len(texts) ** 0.5)),  # server.py's value: pause at √n leaves, at least 10 (class default 30)
        min_gain_rel=0.01,   # minimum inertia reduction (1%) to accept a split
        min_child_size=8,    # reject child clusters smaller than this
    )
```

**How splitting works:**

1. Maintain a queue of "live" leaf clusters
2. Pick the largest by `total_metric` (not by count — a cluster of 50 high-volume queries is more interesting than 200 low-volume ones)
3. Run KMeans with k=2 and k=3 on the cluster's embeddings; keep the better one
4. Compute **inertia gain**: `(parent_inertia - sum(child_inertias)) / parent_inertia`
5. If gain < 1%, the cluster is too homogeneous to split — mark it terminal
6. If any child has fewer than 8 members, reject the split
7. Otherwise, accept the split and generate canonical labels

**Canonical label generation:**

For each new cluster, the top 30 queries (by metric) are sent to GPT-4o-mini:

```
Prompt: "Generate ONE canonical label (max 6 words) that summarizes
         the theme of these queries: [query1, query2, ...]"
```

Parameters: `temperature=0.3`, `max_tokens=30`. Falls back to the top query text on failure.

**The generator pattern:**

`StepClusterer.run()` is a Python generator that yields events one at a time. This is critical for WebSocket streaming — the server can send each event immediately as it's produced rather than waiting for the entire clustering to finish:

```python
def run(self) -> Generator[Dict, None, None]:
    yield {"type": "init", ...}     # all points
    while should_continue:
        split_result = self._try_split(best_candidate)
        yield {"type": "step", ...} # each split
    yield {"type": "complete", ...} # done
```

### 3.5 WebSocket Streaming Protocol

**File**: `backend/server.py` — `WebSocket /api/ws/cluster/{run_id}`

The WebSocket sends a sequence of JSON messages. Here's the complete protocol:

#### Progress Messages (informational)
```json
{ "type": "progress", "message": "Generating embeddings..." }
{ "type": "progress", "message": "Computing 2D projection..." }
{ "type": "progress", "message": "Starting clustering..." }
```

#### Init Event (sent once, after projection)
```json
{
  "type": "init",
  "points": [
    { "id": 0, "text": "best crm software", "metric": 2400, "x": 0.32, "y": -0.15 },
    { "id": 1, "text": "how to use salesforce", "metric": 880, "x": 0.28, "y": -0.12 }
  ],
  "total_steps_estimate": 12,
  "root_cluster": {
    "id": "c-0",
    "canonical": "all queries",
    "size": 951,
    "total_metric": 45230
  }
}
```

#### Step Events (one per cluster split)
```json
{
  "type": "step",
  "step": 1,
  "depth": 1,
  "parent_id": "c-0",
  "parent_canonical": "all queries",
  "clusters": [
    {
      "id": "c-1",
      "parent_id": "c-0",
      "canonical": "Business Solutions and Client Engagement",
      "size": 312,
      "total_metric": 15400,
      "depth": 1,
      "queries": [
        { "id": 5, "text": "...", "metric": 120, "x": 0.1, "y": 0.3 }
      ]
    },
    {
      "id": "c-2",
      "parent_id": "c-0",
      "canonical": "Product Information and Support",
      "size": 639,
      "total_metric": 29830,
      "depth": 1,
      "queries": [...]
    }
  ]
}
```

#### Complete Event (sent last)
```json
{ "type": "complete", "total_steps": 3 }
```

#### Error Event (on failure)
```json
{ "type": "error", "message": "Something went wrong", "traceback": "..." }
```

**Reconnection**: If a client connects to a completed run, all stored events are replayed in order and the socket closes. This is handled via `GET /api/results/{run_id}` for REST-based replay.

---

## 4. Frontend: Svelte 5 + Canvas

### 4.1 Store Architecture

The frontend uses Svelte's `writable` and `derived` stores for shared state. There are two store files:

#### Cluster Stores (`stores/cluster.ts`)

| Store | Type | Purpose |
|-------|------|---------|
| `points` | `Writable<Point[]>` | All data points with coordinates |
| `steps` | `Writable<StepEvent[]>` | Accumulated clustering steps |
| `currentStep` | `Writable<number>` | Which step the user is viewing (scroll-controlled) |
| `totalSteps` | `Writable<number>` | Total steps from the complete event |
| `totalStepsEstimate` | `Writable<number>` | Estimated steps from the init event |
| `status` | `Writable<Status>` | App state: idle, uploading, embedding, projecting, clustering, complete, error |
| `statusMessage` | `Writable<string>` | Human-readable status text |
| `runId` | `Writable<string>` | Current session ID |
| `selectedCluster` | `Writable<ClusterData\|null>` | Cluster selected by clicking |
| `hoveredPoint` | `Writable<Point\|null>` | Point under the cursor |

**Key derived stores:**

**`visibleClusters`** — The most important derived store. It computes which clusters are visible at the current scroll position:

```
Step 0: no clusters visible (just points)
Step 1: root splits into 2 clusters → show those 2
Step 2: one of those splits → remove parent, add its 2 children
Step 3: another split → same pattern
```

The logic replays all steps from 0 to `currentStep`, tracking which clusters are leaves (haven't been split yet). When a parent is split, it's removed and replaced by its children.

**`pointClusterMap`** — A `Map<number, string>` that maps each point's ID to its current cluster ID. Built from `visibleClusters` by iterating each cluster's `member_ids`. Used for coloring points and determining which cluster a clicked point belongs to.

#### Viewport Stores (`stores/viewport.ts`)

| Store | Type | Default | Purpose |
|-------|------|---------|---------|
| `panX` | `Writable<number>` | 0 | Horizontal pan offset in data space |
| `panY` | `Writable<number>` | 0 | Vertical pan offset |
| `zoom` | `Writable<number>` | 1 | Zoom level (0.2 to 5) |
| `mouseDataX` | `Writable<number>` | 0 | Cursor X in data coordinates |
| `mouseDataY` | `Writable<number>` | 0 | Cursor Y in data coordinates |
| `scrollProgress` | `Writable<number>` | 0 | Normalized 0–1 for the progress bar |

### 4.2 Upload Flow

**File**: `lib/Upload.svelte`

The upload component handles two things: getting the file to the server, and initiating the WebSocket clustering stream.

```
User drops CSV
    │
    ▼
POST /api/upload  →  get run_id
    │
    ▼
Open WebSocket to /api/ws/cluster/{run_id}
    │
    ▼
On each message:
    ├── "progress" → update status store (embedding/projecting/clustering)
    ├── "init"     → dispatch CustomEvent("cluster-event") on window
    ├── "step"     → dispatch CustomEvent("cluster-event") on window
    ├── "complete" → dispatch CustomEvent("cluster-event"), set status="complete"
    └── "error"    → set status="error"
```

**Why CustomEvent?** The Upload and Map components don't have a parent-child relationship in the DOM during the transition (Upload disappears when Map appears). Using `window.dispatchEvent(new CustomEvent(...))` provides a simple global event bus that works regardless of component lifecycle.

### 4.3 Canvas Rendering Pipeline

**File**: `lib/Map.svelte`

The map uses HTML5 Canvas (not SVG or WebGL) for performance with hundreds to thousands of points. The render loop runs via `requestAnimationFrame` at 60fps.

#### Coordinate System

Two coordinate spaces are used:

- **Data space**: [-1, 1] in both axes. This is where the t-SNE coordinates live.
- **Canvas space**: pixels, with (0, 0) at the top-left corner.

Conversion between them:

```typescript
// Data → Canvas
function dataToCanvas(x, y, width, height, panX, panY, zoom) {
  const cx = width / 2;
  const cy = height / 2;
  const scale = Math.min(width, height) * 0.4 * zoom;
  return [cx + (x + panX) * scale, cy + (y + panY) * scale];
}
```

The `0.4` factor leaves 20% padding on each side so points don't touch the edges.

#### Render Order (back to front)

Each frame draws layers in this order:

1. **Background**: Solid `#0a0a0a` fill
2. **Grid**: Subtle vertical/horizontal lines every 40px (`rgba(255,255,255,0.04)`)
3. **Concentric circles**: Dotted circles radiating from center every 80px (`rgba(255,255,255,0.06)`)
4. **Cluster boundaries**: Dotted convex hulls around each cluster's points
5. **Points**: Colored circles, sized by metric
6. **Cluster labels**: Text labels at each cluster's centroid

#### Point Animation

When points first appear (on the `init` event), they spring-animate from the center outward:

```typescript
const elapsed = (performance.now() - initTime) / 1000;
const springT = Math.min(1, elapsed * 1.5);      // full spring in ~0.67s
const ease = 1 - Math.pow(1 - springT, 3);       // cubic ease-out

pt.ax = lerp(pt.ax, src.tx * ease, 0.08);        // smooth toward target
pt.ay = lerp(pt.ay, src.ty * ease, 0.08);
```

The `lerp(..., 0.08)` creates a trailing effect — each frame moves 8% of the remaining distance, giving a buttery smooth feel.

#### Point Sizing

Points are sized logarithmically by their metric value:

```typescript
const metricNorm = Math.log2(Math.max(1, src.metric) + 1);
const radius = Math.max(1.5, Math.min(8, metricNorm * 1.2));
```

This prevents high-metric outliers from dominating the view while still making them visibly larger.

#### Cluster Boundaries

Each visible cluster gets a dotted convex hull boundary:

1. Collect all member points' canvas coordinates
2. Compute the convex hull (Andrew's monotone chain algorithm)
3. Expand the hull outward by 20px (so the boundary doesn't sit on top of points)
4. Draw with a dashed stroke pattern `[4, 4]`

Only drawn when a cluster has 3+ members (can't form a hull with fewer).

#### Label Collision Avoidance

Cluster labels are drawn at each cluster's centroid, but they'd overlap if clusters are close together. A simple nudging algorithm handles this:

```typescript
for (const existing of labelPositions) {
  const overlapX = Math.abs(lpx - existing.x) < (tw + existing.w) / 2;
  const overlapY = Math.abs(lpy - existing.y) < (th + existing.h) / 2;
  if (overlapX && overlapY) {
    lpy = existing.y + existing.h / 2 + th / 2 + 4;  // push down
  }
}
```

Labels are pushed downward when they'd overlap with an already-placed label. Not perfect, but works well in practice.

### 4.4 Scroll-Driven Navigation

**File**: `lib/ScrollDriver.svelte`

This is the mechanism that lets you scroll through clustering depth. Instead of the page scrolling, mouse wheel events are intercepted and converted to step changes.

**Constants:**
- `SCROLL_PER_STEP = 150` — pixels of scroll distance per clustering step

**How it works:**

```
Mouse wheel (deltaY)
    │
    ▼
accumulated += deltaY          (running total of scroll distance)
    │
    ▼
rawStep = accumulated / 150    (continuous step value)
    │
    ▼
clamped = clamp(rawStep, 0, maxSteps)
    │
    ▼
newStep = Math.round(clamped)  (snap to integer step)
    │
    ▼
$currentStep = newStep         (triggers visibleClusters recomputation)
$scrollProgress = clamped / maxSteps  (drives progress bar)
```

**External sync**: During live clustering, the backend auto-advances `currentStep` as new steps arrive. The ScrollDriver watches for this via a `$effect` and syncs its `accumulated` value accordingly, so the scroll position stays correct when the user starts scrolling after clustering finishes.

**Modifier key handling**: If Cmd/Ctrl is held, the wheel event is passed through to Map.svelte for zoom control instead.

### 4.5 Interactions (Hover, Click, Pan, Zoom)

All interactions are handled in `Map.svelte`:

#### Hover → Tooltip

On `mousemove`, each animated point is hit-tested:

```typescript
const hitRadius = 10;  // pixels
for (let i = 0; i < animatedPoints.length; i++) {
  const [px, py] = dataToCanvas(pt.ax, pt.ay, ...);
  const dx = e.clientX - px;
  const dy = e.clientY - py;
  if (dx * dx + dy * dy < hitRadius * hitRadius) {
    found = $points[i];
    break;
  }
}
$hoveredPoint = found;
```

The `Tooltip.svelte` component listens to `hoveredPoint` and renders a floating box with the point's text and metric, positioned at the cursor + 12px offset.

#### Click → Detail Panel

A click is detected when `mouseup` fires with <5px of movement from `mousedown`. The click handler finds the nearest point within 20px, looks up its cluster via `pointClusterMap`, and sets `selectedCluster`.

The `DetailPanel.svelte` component slides in from the right (340px wide) showing:
- Cluster name (canonical label)
- Size, total metric, depth
- Breadcrumb trail (root → parent → this cluster)
- Top 10 queries sorted by metric

#### Pan (Click-Drag)

On `mousedown`, the drag start position and current pan offset are recorded. On `mousemove` while dragging, the pan offset is updated proportionally to mouse movement, scaled by the current zoom level:

```typescript
const scale = Math.min(width, height) * 0.4 * $zoom;
$panX = dragStartPanX + (e.clientX - dragStartX) / scale;
$panY = dragStartPanY + (e.clientY - dragStartY) / scale;
```

#### Zoom (Cmd/Ctrl + Scroll)

Zoom is multiplicative and clamped:

```typescript
const delta = -e.deltaY * 0.001;
$zoom = Math.max(0.2, Math.min(5, $zoom + delta * $zoom));
```

The multiplicative factor (`delta * $zoom`) means zooming feels consistent at all levels — scrolling the same amount at zoom level 3 moves proportionally more than at zoom level 1.

### 4.6 HUD Overlay

**File**: `lib/HUD.svelte`

The HUD (heads-up display) provides technical-looking status information without obstructing the map:

```
┌─ FIG 1.0 // NODES ─────────────────────── ● COMPLETE ─┐
│  DEPTH: 02                                              │
│  CLUSTERS: 6                                            │
│  STEP: 3/3                                              │
│                                                         │
│  ═══════════════════════ (progress bar, 2px tall)       │
│                                                         │
│                      [canvas map]                       │
│                                                         │
│  X: -0.157                                         03   │
│  Y: -0.022                                    (large)   │
└─────────────────────────────────────────────────────────┘
```

- **Corner brackets**: CSS pseudo-elements creating L-shaped corners at all four edges
- **Progress bar**: 2px bar across the top, width proportional to `scrollProgress`
- **Pulsing dot**: Green circle that animates (scale + opacity) while clustering is active
- **Step counter**: Large 48px number in the bottom-right at ~8% opacity

### 4.7 Visual Design System

**File**: `styles/hud.css`

The visual system is built around a monospace, technical aesthetic:

**Colors:**
```css
--hud-white:  #e0e0e0     /* primary text */
--hud-dim:    #666         /* secondary text */
--hud-accent: #888         /* mid-brightness elements */
--hud-bg:     #0a0a0a      /* background */
--hud-border: rgba(255, 255, 255, 0.1)
```

**Typography:**
```css
--font-mono: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace
```
- All text is uppercase with wide letter-spacing (0.08em–0.1em)
- HUD labels: 10–11px, regular weight
- Step counter: 48px, bold (700)

**Cluster colors** (15-color palette):
```
#6366f1  indigo       #ec4899  pink        #14b8a6  teal
#f59e0b  amber        #8b5cf6  violet      #ef4444  red
#22c55e  green        #3b82f6  blue        #f97316  orange
#a855f7  purple       #06b6d4  cyan        #e11d48  rose
#84cc16  lime         #0ea5e9  sky         #d946ef  fuchsia
```

Colors are assigned deterministically by hashing the cluster ID string, so the same cluster always gets the same color.

---

## 5. File Reference

### Backend (`backend/`)

| File | Purpose |
|------|---------|
| `server.py` | FastAPI app: upload endpoint, WebSocket streaming, results replay |
| `clustering.py` | `StepClusterer` class: recursive KMeans with generator pattern |
| `projector.py` | `project_2d()`: PCA + t-SNE dimensionality reduction |
| `requirements.txt` | Python dependencies |

### Frontend (`frontend/src/`)

| File | Purpose |
|------|---------|
| `App.svelte` | Root component, state-based view switching |
| `main.ts` | Svelte mount point |
| `stores/cluster.ts` | Shared state: points, steps, clusters, status |
| `stores/viewport.ts` | Pan, zoom, mouse position, scroll progress |
| `utils/canvas.ts` | Coordinate transforms, drawing primitives, convex hull |
| `utils/interpolate.ts` | Easing functions, lerp, snap helpers |
| `lib/Upload.svelte` | Drag-and-drop CSV upload + WebSocket initiation |
| `lib/Map.svelte` | Canvas rendering, animation loop, mouse interactions |
| `lib/HUD.svelte` | Technical overlay: stats, progress bar, coordinates |
| `lib/ScrollDriver.svelte` | Scroll → step mapping |
| `lib/Tooltip.svelte` | Hover tooltip for points |
| `lib/DetailPanel.svelte` | Click-to-open cluster detail sidebar |
| `styles/hud.css` | Global styles, CSS variables, component styles |

---

## 6. Running Locally

### Prerequisites
- Python 3.10+
- Node.js 18+
- An OpenAI API key (set in `.env` at the project root)

### Backend

```bash
cd backend
pip install -r requirements.txt
python server.py
# → running on http://localhost:8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# → running on http://localhost:5173
```

### Environment

Create a `.env` file in the project root:

```
OPENAI_API_KEY=sk-...
```

### Usage

1. Open `http://localhost:5173` in your browser
2. Drop a CSV file onto the upload zone
3. The CSV should have at least 2 columns: one text column and one numeric column
4. Watch the embedding, projection, and clustering steps stream in real-time
5. Once complete, scroll to navigate through clustering depth
6. Hover points for details, click clusters for the detail panel
7. Cmd/Ctrl + scroll to zoom, click-drag to pan
