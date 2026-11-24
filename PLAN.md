# Similarity Browser — Implementation Plan

## Overview
Interactive web visualization: upload a 2-column CSV (text + metric), run recursive semantic clustering via a Python backend, and render an animated 2D force-directed map with a technical HUD aesthetic. Scroll drives navigation through clustering depth with snap points.

---

## Architecture

```
                    User's Browser
                         │
         ┌───────────────┼───────────────┐
         │               │               │
         ▼               ▼               ▼
  ┌─────────────┐  ┌──────────┐  ┌────────────┐
  │ Static Site │  │ REST API │  │ WebSocket  │
  │ (Svelte)    │  │ /upload  │  │ /ws/cluster│
  │ served by   │  │          │  │            │
  │ CF Workers  │  └────┬─────┘  └─────┬──────┘
  └─────────────┘       │              │
                        ▼              ▼
               ┌─────────────────────────────┐
               │  Python FastAPI Server      │
               │  - Receives CSV             │
               │  - Runs clustering pipeline │
               │  - Computes UMAP 2D coords  │
               │  - Streams step events      │
               │  - Uses OpenAI embeddings   │
               └──────────┬──────────────────┘
                          │
               ┌──────────▼──────────────────┐
               │  cluster_queries.py          │
               │  (refactored for per-step   │
               │   yields + UMAP projection) │
               └─────────────────────────────┘
```

**Two separate servers:**
1. **Cloudflare Workers** — serves the built Svelte frontend (static assets)
2. **Python FastAPI** — runs locally or on a VPS, handles clustering + embeddings

The frontend calls the Python backend directly (CORS configured). No CF Workers proxy needed for the API since the Python server handles CORS itself.

---

## Phase 1: Backend — Step-by-Step Clustering API

### 1.1 Refactor `cluster_queries.py` for per-step yields
- Copy the core clustering logic from the original `cluster_queries.py` script
- Refactor `RecursiveClusterer` into a generator that yields after each split:
  ```json
  {
    "type": "step",
    "step": 3,
    "depth": 2,
    "parent_id": "c-6",
    "clusters": [
      {
        "id": "c-7",
        "parent_id": "c-6",
        "canonical": "commercial roofing",
        "size": 42,
        "total_metric": 310,
        "queries": [{ "text": "...", "metric": 5, "x": 0.12, "y": -0.34 }]
      }
    ]
  }
  ```
- Initial event sends all points with UMAP 2D coordinates:
  ```json
  {
    "type": "init",
    "points": [
      { "id": 0, "text": "...", "metric": 5, "x": 0.12, "y": -0.34 }
    ],
    "total_steps_estimate": 12
  }
  ```
- Final event:
  ```json
  { "type": "complete", "total_steps": 12 }
  ```

### 1.2 UMAP 2D projection (`projector.py`)
- Takes the OpenAI embedding matrix → UMAP(n_components=2) → normalized to [-1, 1]
- Run once at start, coordinates are stable across all steps

### 1.3 FastAPI server (`backend/server.py`)
- `POST /api/upload` — accepts 2-col CSV, validates (text + numeric columns), returns `run_id`
- `WebSocket /api/ws/cluster/{run_id}` — kicks off clustering, streams step events as JSON
- `GET /api/results/{run_id}` — fetch all steps if WS disconnects
- `GET /api/health` — health check
- CORS: allow `*` in dev, restrict in prod
- Reads `OPENAI_API_KEY` from `.env`

---

## Phase 2: Frontend — Svelte + D3 Visualization

### 2.1 Project setup
- Svelte 5 + Vite + TypeScript
- D3.js for force simulation + canvas rendering
- Canvas-based (not SVG) for performance

### 2.2 Landing / Upload screen
- Full-screen HUD aesthetic: grid background, monospace type, corner brackets
- Central drag-and-drop CSV zone
- Header: `FIG 1.0 // UPLOAD`
- After upload → transition to map view

### 2.3 The Map (core visualization)
- **2D canvas** plotting all data points at UMAP coordinates
- **Nodes**: Small dots, radius scaled by metric value
- **Clusters**: At each depth level, nodes in same cluster share a dotted convex hull / boundary
- **Labels**: Canonical query labels float near cluster centroids
- **Density**: Overlapping semi-transparent dots create naturally darker regions

### 2.4 Scroll-driven depth navigation (hybrid)
- Scroll maps to a continuous progress value (0.0 → 1.0)
- **Snap points** at each recursive step (e.g., step 0 at 0.0, step 1 at 0.15, ...)
- Between snaps: smooth interpolation — nodes drift, boundaries stretch
- At each snap point:
  - Labels update with new cluster canonical queries
  - Stats update: cluster count, depth
  - HUD readout: `DEPTH: 02 // CLUSTERS: 9 // STEP: 3/12`
- When a cluster splits: boundary dissolves, two new ones emerge, nodes drift apart organically

### 2.5 Hover / Click interactions
- **Hover node**: Tooltip — query text + metric value
- **Hover cluster region**: Highlight all nodes, show canonical query + total metric
- **Click cluster**: Side panel slides in with:
  - Canonical query (title)
  - Total metric, cluster size
  - Top 5 representative queries
  - Depth breadcrumb: root → parent → this
- **Click empty space**: Dismiss panel

### 2.6 HUD overlay (matching screenshot style)
- Corner brackets at four corners
- Top-left: `FIG 1.0 // NODES` + `LATENCY: {ms}` + `DEPTH: {n}`
- Top-right: Pulsing dot indicator (active during clustering)
- Bottom-left: `X: {coord} Y: {coord}` (tracks mouse position)
- Bottom-right: Step counter `01`, `02` (large bold monospace)
- Grid background (light gray lines, subtle)
- Dotted concentric circles around map center
- Palette: black, white, grays — monochrome

### 2.7 Animations
- **Initial load**: Nodes fade in from center, spring to UMAP positions
- **Step transition**: Organic drift — nodes smoothly reposition as clusters split
- **Cluster split**: Parent boundary dissolves, children emerge, nodes flow into new groups
- **Zoom reveal**: Scrolling deeper feels like zooming into dense regions
- **Progress bar**: Thin line at top showing scroll progress

---

## Phase 3: Polish & Extras

### 3.1 Zoom / Pan
- Pinch/scroll-zoom on canvas (with modifier key to avoid conflict with depth scroll)
- Click-drag to pan
- Optional minimap in corner

### 3.2 Export
- Download current view as PNG
- Download cluster results as CSV

### 3.3 Live clustering animation
- As WebSocket streams steps, map updates in real-time
- Replay button to re-watch the clustering process

---

## File Structure

```
similarity-browser/
├── backend/
│   ├── server.py              # FastAPI + WebSocket server
│   ├── clustering.py          # Step-by-step wrapper (refactored from cluster_queries.py)
│   ├── projector.py           # UMAP 2D projection
│   ├── requirements.txt       # fastapi, uvicorn, umap-learn, openai, scikit-learn, numpy
│   └── .env.example           # OPENAI_API_KEY=sk-...
├── frontend/
│   ├── package.json
│   ├── svelte.config.js
│   ├── vite.config.ts
│   ├── src/
│   │   ├── App.svelte
│   │   ├── lib/
│   │   │   ├── Upload.svelte        # CSV drag-drop screen
│   │   │   ├── Map.svelte           # Main canvas visualization
│   │   │   ├── HUD.svelte           # Technical overlay
│   │   │   ├── DetailPanel.svelte   # Click sidebar
│   │   │   ├── ScrollDriver.svelte  # Scroll → depth mapping
│   │   │   └── Tooltip.svelte       # Hover tooltip
│   │   ├── stores/
│   │   │   ├── cluster.ts           # Cluster data store
│   │   │   └── viewport.ts          # Pan/zoom/scroll state
│   │   ├── utils/
│   │   │   ├── canvas.ts            # Canvas rendering helpers
│   │   │   ├── force.ts             # D3 force simulation config
│   │   │   └── interpolate.ts       # Step transition math
│   │   └── styles/
│   │       └── hud.css              # HUD styling
│   └── index.html
├── wrangler.toml                    # CF Workers config (serves built frontend)
└── PLAN.md
```

---

## Implementation Order

| Step | What |
|------|------|
| 1 | Backend: copy + refactor clustering logic for per-step generator yields |
| 2 | Backend: UMAP 2D projection module |
| 3 | Backend: FastAPI server + WebSocket streaming |
| 4 | Frontend: Svelte + Vite scaffold, HUD shell |
| 5 | Frontend: CSV upload screen with HUD aesthetic |
| 6 | Frontend: Canvas map — render nodes at UMAP coords |
| 7 | Frontend: Cluster boundaries (dotted hulls/circles) |
| 8 | Frontend: Scroll driver — depth transitions + snap points |
| 9 | Frontend: Node animations (spring physics, split transitions) |
| 10 | Frontend: Hover tooltips + click detail panel |
| 11 | Frontend: Full HUD polish (coords, counter, grid, brackets) |
| 12 | CF Workers: serve built frontend static assets |
| 13 | Phase 3 extras: zoom/pan, export, live replay |

**We'll tackle this incrementally — steps 1–11 first, then polish.**
