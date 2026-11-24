<script lang="ts">
  import {
    visibleClusters,
    hoveredCluster,
    pinnedClusterIds,
    sidebarWidth,
    mobileSidebarOpen,
    currentStep,
    totalSteps,
    status,
    points,
    wsRef,
    canSplitMore,
    type ClusterData,
  } from "../stores/cluster";
  import { innerWidth, MOBILE_BREAKPOINT } from "../stores/viewport";

  const DRAWER_WIDTH = 280;
  let isMobile = $derived($innerWidth < MOBILE_BREAKPOINT);

  let splitting = $state(false);
  let showLimit: 10 | 20 | "all" = $state(10);

  function onSplitMore() {
    const ws = $wsRef;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    splitting = true;
    $status = "clustering";
    try {
      ws.send(JSON.stringify({ type: "split_more", count: 5 }));
    } catch (e) {
      splitting = false;
      $status = "error";
    }
    // Status will update back to "complete" when paused/complete event arrives
    // Listen for it via a one-shot check
    const unsub = status.subscribe((s) => {
      if (s === "complete" || s === "error") {
        splitting = false;
        unsub();
      }
    });
  }

  const CLUSTER_COLORS = [
    "#6366f1", "#ec4899", "#14b8a6", "#f59e0b", "#8b5cf6",
    "#ef4444", "#22c55e", "#3b82f6", "#f97316", "#a855f7",
    "#06b6d4", "#e11d48", "#84cc16", "#0ea5e9", "#d946ef",
  ];

  function getClusterColor(clusterId: string): string {
    let hash = 0;
    for (let i = 0; i < clusterId.length; i++) {
      hash = ((hash << 5) - hash + clusterId.charCodeAt(i)) | 0;
    }
    return CLUSTER_COLORS[Math.abs(hash) % CLUSTER_COLORS.length];
  }

  let sorted = $derived(
    [...$visibleClusters].sort((a, b) => b.total_metric - a.total_metric)
  );

  let displayed = $derived(
    showLimit === "all" ? sorted : sorted.slice(0, showLimit)
  );

  let totalMetric = $derived(
    $visibleClusters.reduce((sum, c) => sum + c.total_metric, 0)
  );

  const MIN_SIDEBAR = Math.floor(window.innerWidth / 4);
  const MAX_SIDEBAR = Math.floor(window.innerWidth / 2);
  let dragging = $state(false);

  function startResize(e: MouseEvent) {
    e.preventDefault();
    dragging = true;
    const onMove = (ev: MouseEvent) => {
      const w = Math.max(MIN_SIDEBAR, Math.min(MAX_SIDEBAR, ev.clientX));
      $sidebarWidth = w;
    };
    const onUp = () => {
      dragging = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  function selectCluster(cluster: ClusterData) {
    // Toggle pin (used for both map highlighting and detail expansion)
    const cur = $pinnedClusterIds;
    if (cur.includes(cluster.id)) {
      $pinnedClusterIds = cur.filter((id) => id !== cluster.id);
    } else {
      $pinnedClusterIds = [...cur, cluster.id];
    }
  }

  function formatMetric(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
    return n.toLocaleString();
  }

  // Detail helpers per-cluster
  function getTopQueries(cluster: ClusterData) {
    const pts = $points.filter((p) => cluster.member_ids.includes(p.id));
    return pts.sort((a, b) => b.metric - a.metric).slice(0, 10);
  }

</script>

{#if isMobile}
  <!-- Hamburger: visible when drawer closed (offset when Runs button is in top-left) -->
  <button
    class="sidebar-hamburger sidebar-hamburger-offset"
    class:open={$mobileSidebarOpen}
    onclick={() => mobileSidebarOpen.set(!$mobileSidebarOpen)}
    aria-label="Toggle clusters"
  >
    ≡
  </button>
  <!-- Backdrop when drawer open -->
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  {#if $mobileSidebarOpen}
    <div
      class="sidebar-backdrop"
      onclick={() => mobileSidebarOpen.set(false)}
      role="button"
      tabindex="-1"
    ></div>
  {/if}
{/if}

<aside
  class="sidebar"
  class:drawer={isMobile}
  class:drawer-open={isMobile && $mobileSidebarOpen}
  style="width: {isMobile ? DRAWER_WIDTH : $sidebarWidth}px;"
>
  {#if isMobile && $mobileSidebarOpen}
    <button class="sidebar-close" onclick={() => mobileSidebarOpen.set(false)} aria-label="Close">×</button>
  {/if}
  <!-- Resize handle: desktop only -->
  {#if !isMobile}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="resize-handle" onmousedown={startResize} class:active={dragging}></div>
  {/if}
  <div class="sidebar-header">
    <div class="sidebar-header-top">
      <div>
        <div class="sidebar-title">CLUSTERS</div>
        <div class="sidebar-meta">
          {#if $status === "complete" || $status === "clustering"}
            STEP {$currentStep}/{$totalSteps}
          {:else}
            &mdash;
          {/if}
        </div>
      </div>
      {#if $canSplitMore && $status === "complete" && $wsRef && $wsRef.readyState === WebSocket.OPEN}
        <button class="split-btn" onclick={onSplitMore} disabled={splitting}>
          {#if splitting}
            SPLITTING...
          {:else}
            SPLIT MORE
          {/if}
        </button>
      {/if}
    </div>
    {#if sorted.length > 0}
      <div class="sidebar-controls">
        <select class="limit-select" bind:value={showLimit}>
          <option value={10}>TOP 10</option>
          <option value={20}>TOP 20</option>
          <option value={"all"}>ALL ({sorted.length})</option>
        </select>
      </div>
    {/if}
  </div>

  {#if sorted.length === 0}
    <div class="sidebar-empty">
      {#if $status === "clustering"}
        Waiting for first split...
      {:else}
        Scroll to explore clustering depth
      {/if}
    </div>
  {:else}
    <div class="sidebar-list">
      {#each displayed as cluster (cluster.id)}
        {@const pct = totalMetric > 0 ? (cluster.total_metric / totalMetric) * 100 : 0}
        {@const isPinned = $pinnedClusterIds.includes(cluster.id)}
        <button
          class="sidebar-item"
          class:active={isPinned}
          class:pinned={isPinned}
          onclick={() => selectCluster(cluster)}
          onmouseenter={() => $hoveredCluster = cluster}
          onmouseleave={() => $hoveredCluster = null}
        >
          <div class="item-color" style="background: {getClusterColor(cluster.id)};"></div>
          <div class="item-content">
            <div class="item-label">{cluster.canonical}</div>
            <div class="item-stats">
              <span class="item-metric">{formatMetric(cluster.total_metric)}</span>
              <span class="item-sep">&middot;</span>
              <span class="item-size">{cluster.size}</span>
              <span class="item-pct">{pct.toFixed(0)}%</span>
            </div>
            <div class="item-bar-track">
              <div class="item-bar-fill" style="width: {pct}%; background: {getClusterColor(cluster.id)};"></div>
            </div>
          </div>
        </button>

        {#if isPinned}
          <div class="detail-inline">
            <div class="detail-stats">
              <div class="detail-stat">SIZE: {cluster.size} queries</div>
              <div class="detail-stat">METRIC TOTAL: {cluster.total_metric.toLocaleString()}</div>
              <div class="detail-stat">DEPTH: {cluster.depth}</div>
            </div>
            <div class="detail-queries">
              <div class="detail-queries-title">TOP QUERIES</div>
              {#each getTopQueries(cluster) as q}
                <div class="detail-query-item">
                  <span class="detail-query-metric">{q.metric.toLocaleString()}</span>
                  <span class="detail-query-text">{q.text}</span>
                </div>
              {/each}
            </div>
          </div>
        {/if}
      {/each}
    </div>
  {/if}
</aside>

<style>
  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    /* width set via inline style */
    background: rgba(10, 10, 10, 0.92);
    border-right: 1px solid rgba(255, 255, 255, 0.06);
    z-index: 70;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
  }

  .resize-handle {
    position: absolute;
    right: -3px;
    top: 0;
    bottom: 0;
    width: 6px;
    cursor: col-resize;
    z-index: 80;
    background: transparent;
    transition: background 0.15s;
  }

  .resize-handle:hover,
  .resize-handle.active {
    background: rgba(255, 255, 255, 0.1);
  }

  .sidebar-header {
    padding: 20px 20px 16px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    flex-shrink: 0;
  }

  .sidebar-header-top {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }

  .split-btn {
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.1em;
    padding: 5px 10px;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 3px;
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.5);
    cursor: pointer;
    transition: all 0.15s;
    white-space: nowrap;
    flex-shrink: 0;
  }

  .split-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.7);
    border-color: rgba(255, 255, 255, 0.25);
  }

  .split-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .sidebar-controls {
    margin-top: 10px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .limit-select {
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.08em;
    padding: 4px 8px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 3px;
    background: rgba(255, 255, 255, 0.04);
    color: rgba(255, 255, 255, 0.45);
    cursor: pointer;
    outline: none;
    appearance: none;
    -webkit-appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='8' height='5'%3E%3Cpath d='M0 0l4 5 4-5z' fill='rgba(255,255,255,0.3)'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 8px center;
    padding-right: 22px;
  }

  .limit-select:hover {
    border-color: rgba(255, 255, 255, 0.2);
    color: rgba(255, 255, 255, 0.6);
  }

  .limit-select option {
    background: #1a1a1a;
    color: rgba(255, 255, 255, 0.7);
  }

  .sidebar-title {
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0.12em;
    color: rgba(255, 255, 255, 0.5);
  }

  .sidebar-meta {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.25);
    margin-top: 4px;
    letter-spacing: 0.08em;
  }

  .sidebar-empty {
    padding: 24px 20px;
    font-size: 12px;
    color: rgba(255, 255, 255, 0.2);
    letter-spacing: 0.05em;
  }

  .sidebar-list {
    flex: 1;
    overflow-y: auto;
    padding: 8px 0;
  }

  .sidebar-list::-webkit-scrollbar {
    width: 3px;
  }

  .sidebar-list::-webkit-scrollbar-track {
    background: transparent;
  }

  .sidebar-list::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 2px;
  }

  .sidebar-item {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    width: 100%;
    padding: 10px 20px;
    background: none;
    border: none;
    outline: none;
    cursor: pointer;
    text-align: left;
    font-family: var(--font-mono);
    transition: background 0.15s;
  }

  .sidebar-item:hover {
    background: rgba(255, 255, 255, 0.03);
  }

  .sidebar-item.active {
    background: rgba(255, 255, 255, 0.05);
  }

  .sidebar-item.pinned {
    background: rgba(255, 255, 255, 0.06);
    border-left: 2px solid rgba(255, 255, 255, 0.15);
  }

  .item-color {
    width: 3px;
    min-height: 28px;
    border-radius: 1px;
    flex-shrink: 0;
    margin-top: 1px;
    opacity: 0.7;
  }

  .item-content {
    flex: 1;
    min-width: 0;
  }

  .item-label {
    font-size: 13px;
    color: rgba(255, 255, 255, 0.75);
    line-height: 1.35;
    margin-bottom: 4px;
  }

  .item-stats {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.3);
    letter-spacing: 0.05em;
    display: flex;
    align-items: center;
    gap: 5px;
  }

  .item-metric {
    color: rgba(255, 255, 255, 0.45);
    font-weight: 500;
  }

  .item-sep {
    opacity: 0.3;
  }

  .item-size {
    color: rgba(255, 255, 255, 0.25);
  }

  .item-pct {
    margin-left: auto;
    color: rgba(255, 255, 255, 0.2);
  }

  .item-bar-track {
    height: 2px;
    background: rgba(255, 255, 255, 0.04);
    margin-top: 6px;
    border-radius: 1px;
    overflow: hidden;
  }

  .item-bar-fill {
    height: 100%;
    border-radius: 1px;
    opacity: 0.4;
    transition: width 0.3s ease;
  }

  /* Inline detail panel */
  .detail-inline {
    padding: 8px 20px 12px 33px;
    background: rgba(255, 255, 255, 0.02);
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  }

  .detail-stats {
    margin-bottom: 10px;
  }

  .detail-stat {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.35);
    margin-bottom: 3px;
    letter-spacing: 0.05em;
  }

  .detail-queries-title {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.35);
    letter-spacing: 0.05em;
    margin-bottom: 6px;
  }

  .detail-query-item {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.5);
    padding: 3px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
    display: flex;
    gap: 8px;
  }

  .detail-query-metric {
    color: rgba(255, 255, 255, 0.25);
    flex-shrink: 0;
    min-width: 32px;
    text-align: right;
  }

  .detail-query-text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Mobile drawer - offset when Runs button is visible (map view) */
  .sidebar-hamburger {
    position: fixed;
    top: 14px;
    left: 14px;
    z-index: 85;
    width: 40px;
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
    font-family: var(--font-mono);
    color: rgba(255, 255, 255, 0.5);
    background: rgba(10, 10, 10, 0.92);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 4px;
    cursor: pointer;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    transition: color 0.2s, border-color 0.2s;
  }

  .sidebar-hamburger:hover {
    color: rgba(255, 255, 255, 0.7);
    border-color: rgba(255, 255, 255, 0.2);
  }

  .sidebar-hamburger-offset {
    left: 90px;
  }

  .sidebar-backdrop {
    position: fixed;
    inset: 0;
    z-index: 75;
    background: rgba(0, 0, 0, 0.4);
    backdrop-filter: blur(2px);
    -webkit-backdrop-filter: blur(2px);
  }

  .sidebar-close {
    position: absolute;
    top: 14px;
    right: 14px;
    z-index: 90;
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 24px;
    line-height: 1;
    color: rgba(255, 255, 255, 0.5);
    background: transparent;
    border: none;
    cursor: pointer;
    border-radius: 4px;
    transition: color 0.2s, background 0.2s;
  }

  .sidebar-close:hover {
    color: rgba(255, 255, 255, 0.9);
    background: rgba(255, 255, 255, 0.08);
  }

  .sidebar.drawer {
    transform: translateX(-100%);
    transition: transform 0.25s ease-out;
    z-index: 80;
    box-shadow: 4px 0 24px rgba(0, 0, 0, 0.4);
  }

  .sidebar.drawer.drawer-open {
    transform: translateX(0);
  }
</style>
