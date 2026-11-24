<script lang="ts">
  import { onMount } from "svelte";
  import {
    status, statusMessage, runId, eventBuffer, steps, currentStep,
    totalSteps, savedRuns, resetStores, wsRef, canSplitMore, terminalLines,
    type RunMeta,
  } from "../stores/cluster";
  import { fetchRuns, fetchRunEvents, deleteRun, isBackendAvailable, getApiBase } from "./dataService";
  import { innerWidth, MOBILE_BREAKPOINT, openRunListOnUpload } from "../stores/viewport";

  let isMobile = $derived($innerWidth < MOBILE_BREAKPOINT);
  let runListOpen = $state(false);

  // Auto-open run list when navigating back on mobile (e.g. from map view)
  $effect(() => {
    if ($status === "idle" && $openRunListOnUpload && isMobile) {
      runListOpen = true;
      openRunListOnUpload.set(false);
    }
  });

  let mode: "home" | "auth" | "upload" = $state("home");
  let dragover = $state(false);
  let fileInput: HTMLInputElement;
  let password = $state("");
  let authError = $state("");
  let loadingRun = $state("");
  let backendUp = $state(false);
  let deletingRun = false;

  let hasInitialized = false;

  onMount(async () => {
    backendUp = await isBackendAvailable();
    $savedRuns = await fetchRuns();
    hasInitialized = true;

    // Deep-link: ?run=… from terrain.run's embeds. The run's data comes from
    // the embedding page (dataService fromParent), never from this site, so
    // don't gate the load on list membership.
    const urlRun = new URLSearchParams(window.location.search).get("run");
    if (urlRun) {
      await loadSavedRun({
        run_id: urlRun, name: urlRun, created_at: "",
        row_count: 0, text_col: "", metric_col: "",
      });
    }
  });

  // Re-fetch runs when user navigates back (status resets to "idle").
  // Upload stays mounted (hidden via CSS), so onMount won't re-fire.
  $effect(() => {
    if ($status === "idle" && hasInitialized) {
      fetchRuns().then((runs) => { $savedRuns = runs; });
    }
  });

  function formatDate(iso: string): string {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }

  function formatCount(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
    return String(n);
  }

  async function loadSavedRun(run: RunMeta) {
    if (deletingRun) return;
    loadingRun = run.run_id;

    try {
      resetStores();
      const data = await fetchRunEvents(run.run_id);
      $runId = run.run_id;

      // Replay events into stores — go straight to clustering/complete, no loading flash
      let stepCount = 0;
      for (const event of data.events) {
        $eventBuffer = [...$eventBuffer, event];
        window.dispatchEvent(new CustomEvent("cluster-event", { detail: event }));

        if (event.type === "init") {
          $status = "clustering";
          $statusMessage = "Loading...";
        } else if (event.type === "step") {
          stepCount++;
        } else if (event.type === "complete" || event.type === "paused") {
          $status = "complete";
          const steps = event.total_steps || "";
          const leaves = event.leaf_count ? ` — ${event.leaf_count} clusters` : "";
          $statusMessage = `${steps} steps${leaves}`;
        }
      }

      // Flat partitions (exactly one step, e.g. AEO topic maps) have no
      // scroll-story — reveal the clusters immediately instead of waiting
      // for the first wheel event. Multi-step runs keep the walkthrough.
      if (stepCount === 1) {
        $currentStep = 1;
      }

      loadingRun = "";
      runListOpen = false; // Close drawer on mobile when run loads
    } catch (e: any) {
      $status = "error";
      $statusMessage = e.message;
      loadingRun = "";
    }
  }

  async function onDeleteRun(e: MouseEvent, run: RunMeta) {
    e.stopPropagation();
    e.preventDefault();
    if (!confirm(`Delete "${run.name}"?`)) return;
    deletingRun = true;
    try {
      const ok = await deleteRun(run.run_id);
      if (ok) {
        $savedRuns = $savedRuns.filter((r) => r.run_id !== run.run_id);
      }
    } finally {
      deletingRun = false;
    }
  }

  function onNewRun() {
    mode = "auth";
    authError = "";
    password = "";
  }

  function onAuthSubmit() {
    if (!password.trim()) {
      authError = "Password required";
      return;
    }
    authError = "";
    mode = "upload";
  }

  function onAuthKeydown(e: KeyboardEvent) {
    if (e.key === "Enter") onAuthSubmit();
    if (e.key === "Escape") { mode = "home"; }
  }

  async function handleFile(file: File) {
    if (!file.name.endsWith(".csv")) {
      alert("Please upload a CSV file");
      return;
    }

    $status = "uploading";
    $statusMessage = "Uploading CSV...";

    const form = new FormData();
    form.append("file", file);
    form.append("password", password);

    try {
      const res = await fetch(`${getApiBase()}/api/upload`, {
        method: "POST",
        body: form,
      });

      if (res.status === 403) {
        $status = "idle";
        $statusMessage = "";
        authError = "Invalid password";
        mode = "auth";
        return;
      }

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Upload failed");
      }

      const data = await res.json();
      $runId = data.run_id;
      $statusMessage = `Uploaded ${data.rows} rows (${data.text_col} + ${data.metric_col})`;

      startClustering(data.run_id);
    } catch (e: any) {
      $status = "error";
      $statusMessage = e.message;
    }
  }

  function startClustering(rid: string) {
    $status = "embedding";
    $statusMessage = "Connecting...";

    const ws = new WebSocket(`${getApiBase().replace("http", "ws")}/api/ws/cluster/${rid}`);
    $wsRef = ws;

    ws.onmessage = (ev) => {
      const event = JSON.parse(ev.data);

      if (event.type === "progress") {
        if (event.message.includes("embedding")) {
          $status = "embedding";
        } else if (event.message.includes("projection")) {
          $status = "projecting";
        } else {
          $status = "clustering";
        }
        $statusMessage = event.message;
        // Write directly to terminal store + dispatch event
        $terminalLines = [...$terminalLines, event.message];
        window.dispatchEvent(new CustomEvent("cluster-event", { detail: { type: "log", message: event.message } }));
      } else if (event.type === "log") {
        // Write directly to terminal store + dispatch event
        $terminalLines = [...$terminalLines, event.message];
        window.dispatchEvent(new CustomEvent("cluster-event", { detail: event }));
      } else if (event.type === "paused") {
        $eventBuffer = [...$eventBuffer, event];
        window.dispatchEvent(new CustomEvent("cluster-event", { detail: event }));
        $status = "complete";
        $canSplitMore = event.can_split;
        $statusMessage = `${event.total_steps} steps — ${event.leaf_count} clusters`;
      } else if (event.type === "init" || event.type === "step" || event.type === "complete") {
        $eventBuffer = [...$eventBuffer, event];
        window.dispatchEvent(new CustomEvent("cluster-event", { detail: event }));

        if (event.type === "init") {
          $status = "clustering";
          $statusMessage = "Clustering in progress...";
        } else if (event.type === "complete") {
          $status = "complete";
          $canSplitMore = false;
          $statusMessage = `Complete — ${event.total_steps} steps`;
        }
      } else if (event.type === "error") {
        $status = "error";
        $statusMessage = event.message;
      }
    };

    ws.onclose = () => {
      $wsRef = null;
    };

    ws.onerror = () => {
      $status = "error";
      $statusMessage = "WebSocket connection failed";
    };
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    dragover = false;
    const file = e.dataTransfer?.files[0];
    if (file) handleFile(file);
  }

  function onDragOver(e: DragEvent) {
    e.preventDefault();
    dragover = true;
  }

  function onDragLeave() {
    dragover = false;
  }

  function onFileSelect(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) handleFile(file);
  }
</script>

<!-- Mobile: hamburger to open run list -->
{#if isMobile}
  <button
    class="upload-hamburger"
    onclick={() => runListOpen = !runListOpen}
    aria-label="Open run list"
  >
    ≡ RUNS
  </button>
  {#if runListOpen}
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <div
      class="upload-drawer-backdrop"
      role="button"
      tabindex="-1"
      onclick={() => runListOpen = false}
    ></div>
  {/if}
{/if}

<!-- Left sidebar: run list (drawer on mobile) -->
<aside
  class="upload-sidebar"
  class:upload-drawer={isMobile}
  class:upload-drawer-open={isMobile && runListOpen}
>
  {#if isMobile && runListOpen}
    <button class="upload-drawer-close" onclick={() => runListOpen = false} aria-label="Close">×</button>
  {/if}
  <div class="upload-sidebar-content">
    {#if backendUp}
      <button class="new-run-btn" onclick={onNewRun} class:active={mode !== "home"}>
        + NEW RUN
      </button>
    {/if}

    {#if mode === "auth"}
      <div class="auth-block">
        <input
          class="password-input"
          type="password"
          placeholder="Password"
          bind:value={password}
          onkeydown={onAuthKeydown}
          autofocus
        />
        <button class="auth-submit" onclick={onAuthSubmit}>→</button>
        {#if authError}
          <div class="auth-error">{authError}</div>
        {/if}
      </div>
    {/if}

    {#if $savedRuns.length > 0}
      <div class="run-list-label">SAVED RUNS</div>
      <div class="run-list">
        {#each $savedRuns as run}
          <div
            class="run-item"
            class:loading={loadingRun === run.run_id}
            role="button"
            tabindex="0"
            onclick={() => loadSavedRun(run)}
            onkeydown={(e) => e.key === 'Enter' && loadSavedRun(run)}
          >
            <button class="run-delete-btn" onclick={(e: MouseEvent) => onDeleteRun(e, run)}>delete</button>
            <div class="run-item-name">{run.name}</div>
            <div class="run-item-meta">
              <span>{formatCount(run.row_count)} rows</span>
              <span class="run-item-date">{formatDate(run.created_at)}</span>
            </div>
          </div>
        {/each}
      </div>
    {:else}
      <div class="run-list-empty">No saved runs</div>
    {/if}
  </div>
</aside>

<!-- Main area: description OR upload zone -->
<div class="upload-main">
  {#if mode === "upload"}
    <!-- Upload zone -->
    <div class="upload-header">FIG 1.0 // UPLOAD</div>
    <div
      class="upload-zone"
      class:dragover
      role="button"
      tabindex="0"
      ondrop={onDrop}
      ondragover={onDragOver}
      ondragleave={onDragLeave}
      onclick={() => fileInput.click()}
      onkeydown={(e) => e.key === 'Enter' && fileInput.click()}
    >
      <div class="label">DROP CSV HERE</div>
      <div class="sublabel">2 columns: text + numeric metric</div>
    </div>
    <input
      bind:this={fileInput}
      type="file"
      accept=".csv"
      style="display:none"
      onchange={onFileSelect}
    />
  {:else}
    <!-- Description -->
    <div class="desc-container">
      <p class="desc-intro">
        Search queries exhibit patterns that reveal audience intent. Thousands of distinct entries make it difficult for trends to be manually identified. Intent concentrates &mdash; certain topics, needs, and questions draw disproportionate volume. For search queries, these concentrations map to the business areas that matter most. For chatbot logs, they surface what users actually care about. This tool maps text by semantic similarity and recursively partitions the densest regions, drilling deeper at each step means focusing on exactly where value sits.
      </p>

      <div class="desc-section">
        <div class="desc-heading">WHAT IT DOES</div>
        <p>Upload text data with a numeric metric (clicks, impressions, volume). The tool embeds your text into semantic space and recursively splits it &mdash; not into equal regions, but by identifying the largest concentrations of meaning and pulling them apart. Each split isolates the highest-value grouping first, then drills deeper.</p>
        <p>For search queries, this surfaces the business areas where intent is clustering. For chatbot logs, it reveals what users actually care about. Getting granular into sub-clusters means focusing on exactly what matters.</p>
      </div>

      <div class="desc-section">
        <div class="desc-heading">HOW IT WORKS</div>
        <ol class="desc-steps">
          <li>Drop a 2-column CSV (text + metric)</li>
          <li>Text is embedded via OpenAI</li>
          <li>Projected into 3D semantic space</li>
          <li>Recursive splitting isolates high-value groups</li>
          <li>Scroll to walk through each split step by step</li>
        </ol>
      </div>

      <div class="desc-section">
        <div class="desc-heading">EXPLORE</div>
        <ul class="desc-list">
          <li>Orbit the 3D map to see how your data groups</li>
          <li>Hover points for text and metric values</li>
          <li>Click clusters to pin and isolate them</li>
          <li>Pin multiple clusters to compare</li>
          <li>Drag the sidebar edge to resize</li>
        </ul>
      </div>

      <div class="desc-section">
        <div class="desc-heading">INPUT FORMAT</div>
        <p>Column 1: text (query, message, ticket)<br/>Column 2: number (clicks, impressions, count)</p>
      </div>
    </div>
  {/if}
</div>
