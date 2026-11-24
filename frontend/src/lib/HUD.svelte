<script lang="ts">
  import {
    status,
    statusMessage,
    currentStep,
    totalSteps,
    steps,
    visibleClusters,
    effectiveSidebarWidth,
  } from "../stores/cluster";
  import { isMobile } from "../stores/viewport";

  let clusterCount = $derived($visibleClusters.length);
  let maxDepth = $derived(
    $visibleClusters.length > 0
      ? Math.max(...$visibleClusters.map((c) => c.depth))
      : 0
  );
  let isActive = $derived(
    $status === "embedding" ||
    $status === "projecting" ||
    $status === "clustering"
  );
  let stepDisplay = $derived(String($currentStep).padStart(2, "0"));

  function stepBack() {
    if ($currentStep > 0) $currentStep = $currentStep - 1;
  }
  function stepForward() {
    const max = $totalSteps || $steps.length || 0;
    if ($currentStep < max) $currentStep = $currentStep + 1;
  }

  let SIDEBAR = $derived($effectiveSidebarWidth);
</script>

{#if !$isMobile}
<!-- Corner brackets (map area only) -->
<div class="corner-bracket corner-tl" style="left:{SIDEBAR + 12}px;"></div>
<div class="corner-bracket corner-tr"></div>
<div class="corner-bracket corner-bl" style="left:{SIDEBAR + 12}px;"></div>
<div class="corner-bracket corner-br"></div>

<!-- Top left (in map area) -->
<div class="hud-block hud-top-left" style="left:{SIDEBAR + 24}px;">
  <div class="hud-title">FIG 1.0 // NODES</div>
  <div class="hud-value">DEPTH: {String(maxDepth).padStart(2, "0")}</div>
  <div class="hud-value">CLUSTERS: {clusterCount}</div>
  <div class="hud-value">STEP: {$currentStep}/{$totalSteps}</div>
</div>

<!-- Top right -->
<div class="hud-block hud-top-right">
  <span class="pulse-dot" class:active={isActive}></span>
  <span class="hud-value">
    {#if isActive}
      {$statusMessage}
    {:else if $status === "complete"}
      COMPLETE
    {:else}
      READY
    {/if}
  </span>
</div>

<!-- Bottom right step navigator -->
<div class="hud-block hud-bottom-right">
  <div class="step-nav">
    <button class="step-arrow" onclick={stepBack}>‹</button>
    <div class="hud-step-counter">{stepDisplay}</div>
    <button class="step-arrow" onclick={stepForward}>›</button>
  </div>
</div>
{/if}
