# Similarity Browser — Coordination Review

**Scope:** API contracts, data flow alignment, cross-stack consistency, config/env parity

---

## What We've Already Reviewed

| Review | File | Covers |
|--------|------|--------|
| **Code** | CODE_REVIEW.md | Bugs, security, robustness |
| **UI** | UI_FUNCTIONALITY_REVIEW.md | Features, server vs localhost |
| **Unused** | UNUSED_FILES_AND_DEPS.md | Dead code, unused deps |

---

## 1. API Contract Alignment

### GET /api/runs (list runs)

| Source | Response shape | Frontend expects |
|--------|----------------|------------------|
| **Python** | `{ runs: [{ run_id, name, created_at, row_count, text_col, metric_col }] }` | `run.run_id`, `run.name`, etc. |
| **KV (metadata)** | `key.metadata` → same fields if set by upload-to-kv | ✅ |
| **KV (fallback)** | `{ run_id, name, created_at, row_count }` — **missing text_col, metric_col** | RunMeta has them; may be `undefined` |

**Gap:** KV index fallback (`frontend/functions/api/runs/index.ts`) does not include `text_col` or `metric_col` when metadata is absent. RunMeta allows it; UI doesn't display them in the run list. **Low impact.**

---

### GET /api/results/{id} vs GET /api/runs/{id} (fetch events)

| Source | Response | dataService normalizes to |
|--------|----------|---------------------------|
| **Python** | `{ run_id, status, events }` | Same |
| **KV** | Full run JSON `{ run_id, name, ..., events }` | `{ run_id, status: "complete", events: data.events }` |

**Alignment:** ✅ dataService normalizes both to `{ run_id, status, events }`.

---

### DELETE /api/runs/{id}

| Source | Response | dataService |
|--------|----------|-------------|
| **Python** | `{ ok: true, deleted: run_id }` | Checks `res.ok` |
| **KV** | `{ ok: true, deleted: runId }` | Same |

**Alignment:** ✅ Both return 200 with `ok: true`.

---

### WebSocket events (init, step, paused, complete)

| Event | Backend sends | Frontend expects |
|-------|---------------|-----------------|
| **init** | `points`, `total_steps_estimate`, `root_cluster` | Map3D: `event.points`, `event.points[].x,y,z` |
| **step** | `step`, `depth`, `parent_id`, `parent_canonical`, `clusters` | Map3D: `event.step`, `event.clusters`, `c.queries` → `member_ids` |
| **paused** | `total_steps`, `leaf_count`, `can_split` | Upload: `event.can_split`, `event.total_steps`, `event.leaf_count` |
| **complete** | `total_steps` | Map3D: `event.total_steps` |

**Alignment:** ✅ Event shapes match. Point has `id`, `text`, `metric`, `x`, `y`, optional `z`. Cluster has `queries` (array of points).

---

## 2. Naming Consistency

| Concept | Backend (Python) | Frontend (TS) | KV/Pages |
|---------|------------------|---------------|----------|
| Run ID | `run_id` (snake_case) | `runId` (camelCase in stores), `run_id` (API) | `run_id` |
| Run metadata | `run_id`, `name`, `created_at`, `row_count`, `text_col`, `metric_col` | RunMeta: same | Same |

**Note:** Frontend uses `run_id` when consuming API responses; `runId` in Svelte store. Consistent.

---

## 3. Error Handling Flow

| Layer | On error | Propagates to |
|-------|----------|---------------|
| **Upload** | `res.status === 403` → auth error, stay on auth | User |
| **Upload** | `!res.ok` → `err.detail` or "Upload failed" | `$statusMessage`, `$status = "error"` |
| **WebSocket** | `event.type === "error"` → `$status = "error"` | User |
| **fetchRunEvents** | Throws `"Run not found"` | `loadSavedRun` catch → `$status = "error"` |
| **deleteRun** | Returns `false` if !res.ok | `onDeleteRun` → run stays in list (no toast) |

**Gap:** Delete failure is silent — user clicks delete, nothing happens, run stays. Consider showing "Delete failed" or similar.

---

## 4. Config / Environment Parity

| Env var | Where | Documented |
|---------|-------|------------|
| `OPENAI_API_KEY` | Backend `.env` | ✅ README, .env.example |
| `UPLOAD_PASSWORD` | Backend `.env` | ✅ README |
| `VITE_API_BASE` | Frontend (build-time) | ⚠️ Only in UI_FUNCTIONALITY_REVIEW |
| `VITE_R2_BASE` | Frontend (build-time) | ⚠️ Only in UI_FUNCTIONALITY_REVIEW |
| `SITE_PASSWORD` | Cloudflare Pages (wrangler) | ❌ Not in README |

**Gap:** Frontend env vars are not documented in README. Local dev typically uses `VITE_API_BASE=http://localhost:8000` in a `.env` or `.env.local` in the frontend (or project root with Vite picking it up).

**Recommendation:** Add to README:

```bash
# Frontend (optional, for local dev)
# In frontend/.env.local or project root .env:
VITE_API_BASE=http://localhost:8000
```

---

## 5. Data Source Merge Logic (fetchRuns)

```
1. If backend available → fetch from Python, add to results, track seenIds
2. Fetch from KV → add runs NOT in seenIds (dedup by run_id)
3. Sort by created_at desc
```

**Alignment:** ✅ Prevents duplicates when both sources have the same run. Python runs take precedence (loaded first).

---

## 6. State Synchronization

| Scenario | Stores updated | Potential race |
|----------|----------------|----------------|
| **Load saved run** | resetStores → fetch → replay events → points, steps, status | None (sequential) |
| **Live clustering** | WebSocket → eventBuffer, steps, status | Events append; Map3D replays buffer on mount |
| **Switch run A → B** | resetStores clears all; B loads fresh | ✅ Fixed (resetStores at start) |
| **Delete run** | `$savedRuns = filter(...)` | None |

---

## 7. Viewport Store Cleanup

**File:** `frontend/src/stores/viewport.ts`

| Export | Used by | Status |
|--------|---------|--------|
| `panX`, `panY`, `zoom` | — | Unused |
| `mouseDataX`, `mouseDataY` | — | Unused (HUD display removed) |
| `scrollProgress` | ScrollDriver, HUD | Used (HUD may not use it — verify) |

**Recommendation:** Remove `panX`, `panY`, `zoom`, `mouseDataX`, `mouseDataY` from viewport.ts to reduce dead code. Keep `scrollProgress`.

---

## 8. KV Metadata Completeness

**upload-to-kv.py** now stores: `run_id`, `name`, `created_at`, `row_count`, `text_col`, `metric_col`.

**KV index fallback** (when `key.metadata` is absent) only returns: `run_id`, `name`, `created_at`, `row_count`.

**Impact:** Old KV entries uploaded before the script update may lack `text_col`/`metric_col`. Run list doesn't display them, so **low impact**.

---

## Summary: Coordination Health

| Area | Status | Notes |
|------|--------|-------|
| API contracts | ✅ | init/step/paused/complete aligned |
| Run list shape | ⚠️ | KV fallback missing 2 fields |
| Error handling | ⚠️ | Delete failure silent |
| Config docs | ⚠️ | Frontend env vars not in README |
| State sync | ✅ | resetStores fixes switch-run |
| Viewport store | ⚠️ | 5 unused exports |

---

## Suggested Next Steps (optional)

1. Add `VITE_API_BASE` to README for local dev.
2. Add `text_col`, `metric_col` to KV index fallback for consistency.
3. Show feedback on delete failure (e.g. "Delete failed" message).
4. Clean up viewport.ts (remove unused exports).
