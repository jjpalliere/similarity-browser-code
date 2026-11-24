<script lang="ts">
  import { onMount } from "svelte";
  import "./styles/hud.css";
  import Upload from "./lib/Upload.svelte";
  import Map3D from "./lib/Map3D.svelte";
  import HUD from "./lib/HUD.svelte";
  import Tooltip from "./lib/Tooltip.svelte";
  import ScrollDriver from "./lib/ScrollDriver.svelte";
  import Sidebar from "./lib/Sidebar.svelte";
  import Terminal from "./lib/Terminal.svelte";
  import Background3D from "./lib/Background3D.svelte";
  import { status, statusMessage, resetStores } from "./stores/cluster";
  import { innerWidth, isMobile, openRunListOnUpload } from "./stores/viewport";

  let showMap = $derived(
    $status === "clustering" || $status === "complete"
  );
  let showUpload = $derived($status === "idle" || $status === "error");
  let showLoading = $derived(
    $status === "uploading" || $status === "embedding" || $status === "projecting"
  );
  let showTerminal = $derived(
    showLoading || $status === "clustering"
  );
  function onResize() {
    innerWidth.set(window.innerWidth);
  }

  function onBackToRuns() {
    if ($isMobile) openRunListOnUpload.set(true);
    resetStores();
  }

  onMount(() => onResize());
</script>

<svelte:window onresize={onResize} />

<div style:display={showUpload ? "contents" : "none"}>
  <Background3D />
  <div class="frost-overlay"></div>
  <Upload />
  {#if $status === "error"}
    <div style="position:fixed; bottom:60px; left:50%; transform:translateX(-50%); z-index:100; font-size:11px; color:#ef4444; font-family:var(--font-mono);">
      ERROR: {$statusMessage}
    </div>
  {/if}
</div>

{#if showTerminal}
  <div class="terminal-sidebar">
    <Terminal />
  </div>
{/if}

{#if showLoading}
  <div class="loading-main">
    <div class="loading-card">
      <div class="loading-spinner"></div>
      <div class="loading-label">{$statusMessage}</div>
    </div>
  </div>
  <button class="back-btn" onclick={onBackToRuns}>← RUNS</button>
{/if}

{#if showMap}
  {#if $isMobile}
    <button class="runs-btn-map" onclick={onBackToRuns} aria-label="Open runs">
      ≡ RUNS
    </button>
  {:else}
    <button class="back-btn" onclick={onBackToRuns}>← RUNS</button>
  {/if}
  <Map3D />
  <Sidebar />
  <ScrollDriver />
{/if}

<HUD />
<Tooltip />
