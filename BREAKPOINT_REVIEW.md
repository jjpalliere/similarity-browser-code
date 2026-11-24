# Breakpoint Review: Mobile / Desktop Dashboard

## Summary

**Updated (Option C implemented):** The dashboard now uses a **768px breakpoint** with full mobile support: Map3D always visible, touch controls (pinch zoom, tap-to-pin), run list and cluster sidebar as slide-out drawers, and responsive typography.

---

## Current Breakpoint Usage

| Location | Breakpoint | Effect |
|----------|------------|--------|
| `viewport.ts` | 768px | `MOBILE_BREAKPOINT`, `isMobile` derived |
| `hud.css` | `@media (max-width: 768px)` | Upload drawer, responsive login/HUD |
| `cluster.ts` | 768px | `effectiveSidebarWidth` = 0 or drawer width on mobile |
| `Sidebar.svelte` | 768px | Cluster sidebar as drawer with hamburger |
| `Upload.svelte` | 768px | Run list as drawer with hamburger |

---

## Layout by Viewport Size

### Desktop (≥ 768px)

- **Upload view**: Run list sidebar (33.33vw) + upload/main area
- **Loading view**: Terminal sidebar (33.33vw) + loading card
- **Map view**: Cluster sidebar (resizable) + Map3D + HUD + ScrollDriver

### Mobile (< 768px)

- **Upload view**: Hamburger opens run list drawer; upload-main full width
- **Loading view**: Terminal sidebar (33.33vw) + loading card
- **Map view**: Map3D full width; hamburger opens cluster drawer overlay; HUD visible; touch pinch zoom, tap-to-pin

---

## Resolved (Option C Implemented)

- **Map3D** always visible on mobile; pixel ratio capped at 2x for performance
- **Touch controls**: pinch-to-zoom, tap-to-pin clusters, touch hover for tooltips
- **Run list** accessible via hamburger drawer
- **Cluster sidebar** as overlay drawer with hamburger
- **Breakpoint** standardized to 768px; `--breakpoint-mobile` and `--drawer-width` in CSS
- **Login/HUD** responsive padding and typography

---

## Quick Reference: Current 768px Behavior

```
viewport.ts:    innerWidth store, isMobile derived
cluster.ts:     effectiveSidebarWidth = 0 (closed) or 280 (open) on mobile
hud.css:        .upload-main { left: 0 }
                .upload-sidebar.upload-drawer { transform: translateX(-100%) }
                .upload-sidebar.upload-drawer-open { transform: translateX(0) }
Sidebar.svelte: .sidebar.drawer { transform: translateX(-100%) }
                .sidebar.drawer.drawer-open { transform: translateX(0) }
Map3D.svelte:   pixel ratio capped at 2; touch pinch zoom, tap-to-pin
```
