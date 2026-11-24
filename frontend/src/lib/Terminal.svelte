<script lang="ts">
  import { terminalLines } from "../stores/cluster";

  let terminalEl: HTMLDivElement;

  // Auto-scroll whenever lines change
  $effect(() => {
    const _len = $terminalLines.length;
    requestAnimationFrame(() => {
      if (terminalEl) {
        terminalEl.scrollTop = terminalEl.scrollHeight;
      }
    });
  });
</script>

<div class="terminal-viewport">
  <div class="terminal-header">
    <span class="terminal-dot red"></span>
    <span class="terminal-dot yellow"></span>
    <span class="terminal-dot green"></span>
    <span class="terminal-title">PROCESS LOG</span>
  </div>
  <div class="terminal-body" bind:this={terminalEl}>
    {#each $terminalLines as line, i}
      <div class="terminal-line">
        <span class="terminal-prompt">{'>'}</span>
        <span class="terminal-text">{line}</span>
      </div>
    {/each}
    {#if $terminalLines.length === 0}
      <div class="terminal-line dim">
        <span class="terminal-prompt">{'>'}</span>
        <span class="terminal-text">Waiting for process...</span>
      </div>
    {/if}
  </div>
</div>
