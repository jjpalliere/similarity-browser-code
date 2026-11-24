import type { RunMeta } from "../stores/cluster";

const API_BASE = import.meta.env.VITE_API_BASE || "";

// The pages allowed to hand this map its data (see fromParent below).
const PARENT_ORIGINS = [
  "https://terrain.run",
  "https://www.terrain.run",
  "http://localhost:8787",
  "http://127.0.0.1:8787",
];

// Runs anyone may open, as fixed copies in public/runs/ (?run=terrain-run).
// Every other run comes only from its terrain.run page, behind its login.
const PUBLIC_RUNS: Record<string, string> = {
  "terrain-run": "/runs/terrain-run.json",
};

let _backendAvailable: boolean | null = null;

export async function isBackendAvailable(): Promise<boolean> {
  if (_backendAvailable !== null) return _backendAvailable;
  if (!API_BASE) {
    _backendAvailable = false;
    return false;
  }
  try {
    const res = await fetch(`${API_BASE}/api/health`, {
      signal: AbortSignal.timeout(2000),
    });
    _backendAvailable = res.ok;
  } catch {
    _backendAvailable = false;
  }
  return _backendAvailable;
}

export function getApiBase(): string {
  return API_BASE;
}

// Local backend only — hosted runs are deliberately not listable.
export async function fetchRuns(): Promise<RunMeta[]> {
  if (!(await isBackendAvailable())) return [];

  try {
    const res = await fetch(`${API_BASE}/api/runs`);
    if (res.ok) {
      const data = await res.json();
      const results: RunMeta[] = data.runs;
      results.sort((a, b) => b.created_at.localeCompare(a.created_at));
      return results;
    }
  } catch {
    // backend went away — treat as no saved runs
  }
  return [];
}

export async function fetchRunEvents(
  runId: string
): Promise<{ run_id: string; status: string; events: any[] }> {
  // Try local backend first
  if (await isBackendAvailable()) {
    try {
      const res = await fetch(`${API_BASE}/api/results/${runId}`);
      if (res.ok) return res.json();
    } catch {
      // fall through to R2
    }
  }

  // A few runs are public on purpose: a fixed copy ships with the site, so
  // nothing is read from storage (2026-11-23: terrain.run's own map only).
  const publicFile = Object.hasOwn(PUBLIC_RUNS, runId) ? PUBLIC_RUNS[runId] : undefined;
  if (publicFile) {
    const res = await fetch(publicFile);
    if (!res.ok) throw new Error("Run not found");
    const data = await res.json();
    return { run_id: runId, status: "complete", events: data.events };
  }

  // Hosted runs come only from the terrain.run page this map is embedded in.
  // Since 2026-11-05 this site serves no run data itself: anyone with a run's
  // address could download it. terrain.run fetches the run behind its login
  // and posts it here (terrain.run public/assets/js/topic-map-embed.js).
  const data = await fromParent(runId);
  return { run_id: runId, status: "complete", events: data.events };
}

// Ask the page around this frame for the run, and accept the answer only from
// that page, on an allowed origin, for the run asked about.
function fromParent(runId: string, ms = 60000): Promise<any> {
  return new Promise((resolve, reject) => {
    if (window.parent === window) {
      reject(new Error("Open this map from terrain.run."));
      return;
    }
    const timer = setTimeout(() => {
      window.removeEventListener("message", onMessage);
      reject(new Error("The map's data didn't arrive."));
    }, ms);
    function onMessage(e: MessageEvent) {
      if (e.source !== window.parent || !PARENT_ORIGINS.includes(e.origin)) return;
      const d = e.data;
      if (!d || d.type !== "sb-run-data" || d.run !== runId) return;
      clearTimeout(timer);
      window.removeEventListener("message", onMessage);
      if (d.error || !d.data) reject(new Error(d.error || "Run not found"));
      else resolve(d.data);
    }
    window.addEventListener("message", onMessage);
    // The ask carries only the run's key, which the page already knows.
    window.parent.postMessage({ type: "sb-want-run", run: runId }, "*");
  });
}

// Local backend only — hosted runs can't be deleted from this site; use
// `wrangler kv key delete` for those.
export async function deleteRun(runId: string): Promise<boolean> {
  if (!(await isBackendAvailable())) return false;

  try {
    const res = await fetch(`${API_BASE}/api/runs/${runId}`, { method: "DELETE" });
    return res.ok;
  } catch {
    return false;
  }
}
