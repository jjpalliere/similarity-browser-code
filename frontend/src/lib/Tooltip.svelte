<script lang="ts">
  import { hoveredPoint } from "../stores/cluster";

  let x = $state(0);
  let y = $state(0);

  function onMouseMove(e: MouseEvent) {
    x = e.clientX + 12;
    y = e.clientY + 12;
  }

  $effect(() => {
    window.addEventListener("mousemove", onMouseMove);
    return () => window.removeEventListener("mousemove", onMouseMove);
  });
</script>

{#if $hoveredPoint}
  <div class="tooltip" style="left: {x}px; top: {y}px;">
    {#if $hoveredPoint.citings?.length || $hoveredPoint.query || $hoveredPoint.llm || $hoveredPoint.page_url}
      <!-- Structured card (AEO topic maps) -->
      {#if $hoveredPoint.page_title || $hoveredPoint.page_url}
        <div>{$hoveredPoint.page_title ?? $hoveredPoint.page_url}</div>
        {#if $hoveredPoint.page_title && $hoveredPoint.page_url}
          <div class="tooltip-metric">{$hoveredPoint.page_url}</div>
        {/if}
      {:else if $hoveredPoint.kind === "query"}
        <div>“{$hoveredPoint.text}”</div>
      {/if}
      {#if $hoveredPoint.citings?.length}
        <div class="tooltip-metric">
          {$hoveredPoint.kind === "query"
            ? `asked ${$hoveredPoint.citings_total ?? $hoveredPoint.citings.length} times`
            : `cited in ${$hoveredPoint.citings_total ?? $hoveredPoint.citings.length} answers`}
        </div>
        {#each $hoveredPoint.citings as c}
          <div class="tooltip-metric">{$hoveredPoint.kind === "query" ? c.llm : `${c.llm} · “${c.query}”`}</div>
        {/each}
        {#if ($hoveredPoint.citings_total ?? 0) > $hoveredPoint.citings.length}
          <div class="tooltip-metric">+{($hoveredPoint.citings_total ?? 0) - $hoveredPoint.citings.length} more</div>
        {/if}
      {:else if $hoveredPoint.query}
        <div class="tooltip-metric">{$hoveredPoint.llm} · “{$hoveredPoint.query}”</div>
      {/if}
    {:else}
      <div>{$hoveredPoint.text}</div>
      <div class="tooltip-metric">metric: {$hoveredPoint.metric.toLocaleString()}</div>
    {/if}
  </div>
{/if}
