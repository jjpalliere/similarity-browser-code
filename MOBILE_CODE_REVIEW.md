# Code Review: Option C Mobile Implementation

## Summary

Overall the implementation is solid. A few fixes and improvements are recommended below.

---

## Issues Found & Fixes

### 1. Unused import in Sidebar.svelte
**Severity:** Low  
**Fix:** Remove `effectiveSidebarWidth` from imports — it's not used (Sidebar uses `$sidebarWidth` and `DRAWER_WIDTH` directly).

### 2. Breakpoint constant duplication
**Severity:** Low  
**Issue:** `768` / `MOBILE_BP` is defined in 4 places: `viewport.ts`, `cluster.ts`, `Sidebar.svelte`, `Upload.svelte`. Risk of drift if one is updated and others aren't.  
**Fix:** Import `MOBILE_BREAKPOINT` from `viewport.ts` in Sidebar and Upload; use it in cluster.ts.

### 3. Drawer width inconsistency
**Severity:** Low  
**Issue:** Cluster sidebar uses `280px`; upload drawer uses `var(--drawer-width)` = `min(320px, 85vw)`. Minor UX inconsistency.  
**Recommendation:** Consider aligning both to `var(--drawer-width)` for consistency, or document the intentional difference.

### 4. Upload backdrop a11y
**Severity:** Low  
**Issue:** Upload drawer backdrop has `svelte-ignore` but Sidebar backdrop has `role="button"` and `tabindex="-1"`.  
**Fix:** Add `role="button"` and `tabindex="-1"` to upload backdrop for consistency and keyboard users.

### 5. Tap detection edge case
**Severity:** None (verified)  
**Note:** When transitioning from 2-finger pinch to 1 finger, `tapStartX/Y` may be stale. Verified: we only set tapStart on single-touch start, so the tap block won't fire incorrectly (distance would be large). No fix needed.

### 6. Pixel ratio not updated on resize
**Severity:** Very low  
**Note:** `renderer.setPixelRatio()` is set once on mount. If user connects external display or zooms, we don't re-evaluate. Acceptable for now.

---

## What's Working Well

- **effectiveSidebarWidth** correctly drives Map3D and HUD layout
- **Touch handlers** correctly distinguish pinch (2 fingers) vs tap (1 finger)
- **Drawer state** is reset in `resetStores()` when navigating back
- **Run list** closes on successful run load
- **Z-index** layering is correct (hamburger 85, backdrop 75, drawer 80)
- **No overlap** between upload hamburger and cluster hamburger (different views)

---

## Fixes Applied

- `Sidebar.svelte`: Removed unused `effectiveSidebarWidth` import; now uses `MOBILE_BREAKPOINT` from viewport
- `Upload.svelte`: Uses `MOBILE_BREAKPOINT` from viewport; added `role="button"` and `tabindex="-1"` to backdrop
- `cluster.ts`: Uses `MOBILE_BREAKPOINT` from viewport (single source of truth)
