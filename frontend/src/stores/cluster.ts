import { writable, derived } from "svelte/store";
import { innerWidth, MOBILE_BREAKPOINT } from "./viewport";

export interface Point {
  id: number;
  text: string;
  metric: number;
  x: number;
  y: number;
  z: number;
  // Animated positions (for transitions)
  ax: number;
  ay: number;
  az: number;
  // Target positions
  tx: number;
  ty: number;
  tz: number;
  // Optional hover metadata (AEO topic maps): Map3D spreads init points into
  // the store, so ingests that carry these render a structured tooltip.
  kind?: "query" | "citation";
  query?: string;
  llm?: string;
  page_title?: string;
  page_url?: string;
  // Aggregated bubbles: the asks behind this point (capped list + true total).
  citings?: Array<{ query: string; llm: string }>;
  citings_total?: number;
}

export interface ClusterData {
  id: string;
  parent_id: string | null;
  canonical: string;
  size: number;
  total_metric: number;
  depth: number;
  member_ids: number[];
}

export interface StepEvent {
  step: number;
  depth: number;
  parent_id: string;
  parent_canonical: string;
  clusters: ClusterData[];
}

// All points
export const points = writable<Point[]>([]);

// Steps accumulated so far
export const steps = writable<StepEvent[]>([]);

// Current depth step (controlled by scroll)
export const currentStep = writable<number>(0);

// Connection status
export type Status = "idle" | "uploading" | "embedding" | "projecting" | "clustering" | "complete" | "error";
export const status = writable<Status>("idle");
export const statusMessage = writable<string>("");

// Run ID
export const runId = writable<string>("");

// Pinned clusters (click-to-hold on map) — multiple allowed
// Using string[] instead of Set<string> for reliable Svelte reactivity
export const pinnedClusterIds = writable<string[]>([]);

// Hovered cluster (sidebar hover) — used to dim non-hovered clusters on the map
export const hoveredCluster = writable<ClusterData | null>(null);

// Sidebar width (resizable)
export const sidebarWidth = writable<number>(Math.floor(window.innerWidth / 3));

// Mobile: drawer open state (cluster sidebar)
export const mobileSidebarOpen = writable<boolean>(false);

// Effective width: on mobile, 0 when drawer closed, or drawer width when open
const DRAWER_WIDTH = 280;
export const effectiveSidebarWidth = derived(
  [sidebarWidth, innerWidth, mobileSidebarOpen],
  ([$sw, $w, $open]) => $w < MOBILE_BREAKPOINT ? ($open ? DRAWER_WIDTH : 0) : $sw
);

// Hovered point
export const hoveredPoint = writable<Point | null>(null);

// Total steps completed
export const totalSteps = writable<number>(0);

// Clusters visible at current step
// At step 0: just the root cluster
// At step N: all clusters created up to step N replace their parents
export const visibleClusters = derived(
  [steps, currentStep],
  ([$steps, $currentStep]) => {
    if ($steps.length === 0) return [];

    // Build the set of visible clusters at the current step
    // Start with nothing, accumulate through steps
    const clusterMap = new Map<string, ClusterData>();

    // Process steps up to currentStep
    for (let i = 0; i < Math.min($currentStep, $steps.length); i++) {
      const step = $steps[i];
      // Remove parent
      clusterMap.delete(step.parent_id);
      // Add children
      for (const cluster of step.clusters) {
        clusterMap.set(cluster.id, cluster);
      }
    }

    // If no steps processed yet, return root
    if ($currentStep === 0) return [];

    return Array.from(clusterMap.values());
  }
);

// WebSocket reference (for split_more)
export const wsRef = writable<WebSocket | null>(null);

// Can the user request more splits?
export const canSplitMore = writable<boolean>(false);

// Buffered events for late-mounting components (e.g. Map3D)
export const eventBuffer = writable<any[]>([]);

// Terminal log lines (persisted across component mount/unmount cycles)
export const terminalLines = writable<string[]>([]);

// Mapping: point id -> cluster id at current step
export const pointClusterMap = derived(visibleClusters, ($clusters) => {
  const map = new Map<number, string>();
  for (const cluster of $clusters) {
    for (const pid of cluster.member_ids) {
      map.set(pid, cluster.id);
    }
  }
  return map;
});

// --- Run management ---

export interface RunMeta {
  run_id: string;
  name: string;
  created_at: string;
  row_count: number;
  text_col: string;
  metric_col: string;
}

export const savedRuns = writable<RunMeta[]>([]);

/** Reset all visualization stores to idle state. */
export function resetStores() {
  points.set([]);
  steps.set([]);
  currentStep.set(0);
  totalSteps.set(0);
  eventBuffer.set([]);
  terminalLines.set([]);
  pinnedClusterIds.set([]);
  hoveredCluster.set(null);
  hoveredPoint.set(null);
  status.set("idle");
  statusMessage.set("");
  runId.set("");
  wsRef.set(null);
  canSplitMore.set(false);
  mobileSidebarOpen.set(false);
}
