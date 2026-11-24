# Unused Files and Dependencies

## Unused npm Dependencies (frontend)

| Package | Status | Notes |
|---------|--------|-------|
| **d3** | Unused | In `package.json` but never imported. Map3D uses Three.js only. Safe to remove. |
| **@types/d3** | Unused | Type defs for d3. Remove with d3. |

**Remove:** `npm uninstall d3 @types/d3`

---

## Unused viewport store exports

**File:** `frontend/src/stores/viewport.ts`

| Export | Used by | Status |
|--------|---------|--------|
| `panX` | — | Unused (Map3D uses TrackballControls) |
| `panY` | — | Unused |
| `zoom` | — | Unused |
| `mouseDataX` | HUD.svelte | Used (but never written — always 0) |
| `mouseDataY` | HUD.svelte | Used (but never written) |
| `scrollProgress` | HUD.svelte, ScrollDriver.svelte | Used |

**Recommendation:** Remove `panX`, `panY`, `zoom` or leave for future use. The mouse coords are used but never updated (known issue).

---

## Redundant / Duplicate Scripts

| File | Status |
|------|--------|
| `scripts/upload-to-kv.sh` | Redundant — `upload-to-kv.py` now has selective upload. Shell script uploads all. Can delete or keep as fallback. |

---

## Standalone / Analysis Scripts (not part of app)

These are used for batch analysis, not the web app:

| File | Purpose |
|------|---------|
| `cluster_queries.py` | Standalone clustering (used by run_both_analyses, cluster_chatbot_questions, test_clustering.sh) |
| `cluster_chatbot_questions.py` | Wraps cluster_queries for chatbot data |
| `analyze_parameters.py` | Parameter analysis |
| `run_both_analyses.py` | Runs dual analyses |
| `run_both_analyses.sh` | Shell wrapper |
| `test_500_queries.py` | Test script |
| `test_clustering.sh` | Test script |

**Status:** Keep — they serve analysis workflows. Not "unused" for the project.

---

## Unused Static Assets

| File | Status |
|------|--------|
| `frontend/public/icons.svg` | Not referenced in index.html or any component |
| `frontend/public/favicon.svg` | Not linked in index.html (no `<link rel="icon">`) |

**Recommendation:** Add favicon link if desired; remove or repurpose icons.svg if unused.

---

## Documentation (outdated but kept)

| File | Status |
|------|--------|
| `DOCS.md` | Describes 2D/Map.svelte; app uses 3D/Map3D |
| `PLAN.md` | Planning doc; references UMAP (implementation uses t-SNE) |

**Status:** Informational; update when convenient.

---

## Summary: Safe to Remove

1. **npm:** `d3`, `@types/d3`
2. **Script:** `scripts/upload-to-kv.sh` (optional — Python version is preferred)
3. **Asset:** `frontend/public/icons.svg` (if confirmed unused)
