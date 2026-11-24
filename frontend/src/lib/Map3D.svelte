<script lang="ts">
  import { onMount } from "svelte";
  import * as THREE from "three";
  import { TrackballControls } from "three/examples/jsm/controls/TrackballControls.js";
  import { get } from "svelte/store";
  import {
    points,
    steps,
    totalSteps,
    currentStep,
    visibleClusters,
    pointClusterMap,
    hoveredPoint,
    hoveredCluster,
    pinnedClusterIds,
    effectiveSidebarWidth,
    eventBuffer,
    type Point,
    type StepEvent,
    type ClusterData,
  } from "../stores/cluster";

  let SIDEBAR_WIDTH = $derived($effectiveSidebarWidth);

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

  function hexToRGB(hex: string): [number, number, number] {
    return [
      parseInt(hex.slice(1, 3), 16) / 255,
      parseInt(hex.slice(3, 5), 16) / 255,
      parseInt(hex.slice(5, 7), 16) / 255,
    ];
  }

  let container: HTMLDivElement;
  let scene: THREE.Scene;
  let camera: THREE.PerspectiveCamera;
  let renderer: THREE.WebGLRenderer;
  let controls: TrackballControls;
  let animFrame: number;

  let pointsGeometry: THREE.BufferGeometry;
  let pointsMesh: THREE.Points;
  let edgesGroup: THREE.Group;
  let labelsContainer: HTMLDivElement;

  let initialized = false;
  let initTime = 0;
  let animatedPositions: Float32Array;
  let targetPositions: Float32Array;
  let pointColors: Float32Array;
  let pointSizes: Float32Array;
  let lastEdgeStep = -1; // Track when to rebuild edges
  let lastEdgeHoverId: string | null = null; // Track hovered cluster for edge rebuild
  let dragStartX = 0;
  let dragStartY = 0;
  const DRAG_THRESHOLD = 5; // px — distinguish click from drag-to-rotate
  let idToIndex: Map<number, number> = new Map(); // point ID → array index
  let raycaster: THREE.Raycaster;
  let mouse: THREE.Vector2;
  let zoomLimits = { min: 1, max: 3 };
  let targetZoomDist = -1; // -1 = no target (use current)
  let pinchStartDist = -1;
  let pinchStartZoom = -1;
  let tapStartX = 0;
  let tapStartY = 0;

  function handleClusterEvent(e: CustomEvent) {
    const event = e.detail;

    if (event.type === "init") {
      $steps = [];
      const pts: Point[] = event.points.map((p: any) => ({
        ...p,
        z: p.z ?? 0,
        ax: 0, ay: 0, az: 0,
        tx: p.x, ty: p.y, tz: p.z ?? 0,
      }));
      $points = pts;
      // Build ID → array index lookup
      idToIndex = new Map();
      for (let i = 0; i < pts.length; i++) {
        idToIndex.set(pts[i].id, i);
      }

      const n = pts.length;
      animatedPositions = new Float32Array(n * 3);
      targetPositions = new Float32Array(n * 3);
      pointColors = new Float32Array(n * 3);
      pointSizes = new Float32Array(n);

      // Compute metric-based sizes using sqrt scale (gentler than log, preserves size differences)
      const metrics = pts.map((p) => p.metric);
      const maxMetric = Math.max(...metrics, 1);
      const minMetric = Math.min(...metrics);
      // Uniform metrics (e.g. AEO topic maps where every point is one
      // citation) carry no size signal — render small dots, not max-size ones.
      const uniformMetric = maxMetric === minMetric;
      const UNIFORM_SIZE = 0.05;
      const MIN_SIZE = 0.02;
      const MAX_SIZE = 0.22;

      for (let i = 0; i < n; i++) {
        targetPositions[i * 3] = pts[i].tx;
        targetPositions[i * 3 + 1] = pts[i].ty;
        targetPositions[i * 3 + 2] = pts[i].tz;
        animatedPositions[i * 3] = 0;
        animatedPositions[i * 3 + 1] = 0;
        animatedPositions[i * 3 + 2] = 0;
        pointColors[i * 3] = 1;
        pointColors[i * 3 + 1] = 1;
        pointColors[i * 3 + 2] = 1;
        // Sqrt scale: gentler compression than log, high-metric points stay visibly larger
        const t = Math.sqrt(pts[i].metric / maxMetric);
        pointSizes[i] = uniformMetric ? UNIFORM_SIZE : MIN_SIZE + t * (MAX_SIZE - MIN_SIZE);
      }

      // Remove old mesh if re-initializing
      if (pointsMesh) {
        scene.remove(pointsMesh);
        pointsGeometry.dispose();
      }

      pointsGeometry = new THREE.BufferGeometry();
      pointsGeometry.setAttribute("position", new THREE.BufferAttribute(animatedPositions, 3));
      pointsGeometry.setAttribute("color", new THREE.BufferAttribute(pointColors, 3));
      pointsGeometry.setAttribute("aSize", new THREE.BufferAttribute(pointSizes, 1));

      // Create crisp circle texture (no glow)
      const circleCanvas = document.createElement("canvas");
      circleCanvas.width = 32;
      circleCanvas.height = 32;
      const ctx = circleCanvas.getContext("2d")!;
      ctx.beginPath();
      ctx.arc(16, 16, 14, 0, Math.PI * 2);
      ctx.fillStyle = "white";
      ctx.fill();
      const circleTexture = new THREE.CanvasTexture(circleCanvas);

      // Custom shader for per-point metric-based sizing
      const mat = new THREE.ShaderMaterial({
        uniforms: {
          uTexture: { value: circleTexture },
        },
        vertexShader: `
          attribute float aSize;
          varying vec3 vColor;
          void main() {
            vColor = color;
            vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
            gl_PointSize = aSize * (300.0 / -mvPosition.z);
            gl_Position = projectionMatrix * mvPosition;
          }
        `,
        fragmentShader: `
          uniform sampler2D uTexture;
          varying vec3 vColor;
          void main() {
            vec4 tex = texture2D(uTexture, gl_PointCoord);
            if (tex.a < 0.1) discard;
            gl_FragColor = vec4(vColor * tex.rgb, tex.a * 0.9);
          }
        `,
        transparent: true,
        depthWrite: false,
        vertexColors: true,
      });

      pointsMesh = new THREE.Points(pointsGeometry, mat);
      scene.add(pointsMesh);

      initTime = performance.now();
      initialized = true;
    } else if (event.type === "step") {
      const stepEvent: StepEvent = {
        step: event.step,
        depth: event.depth,
        parent_id: event.parent_id,
        parent_canonical: event.parent_canonical,
        clusters: event.clusters.map((c: any) => ({
          id: c.id,
          parent_id: c.parent_id,
          canonical: c.canonical,
          size: c.size,
          total_metric: c.total_metric,
          depth: c.depth,
          member_ids: c.queries.map((q: any) => q.id),
        })),
      };
      $steps = [...$steps, stepEvent];
      $totalSteps = event.step;
    } else if (event.type === "complete") {
      $totalSteps = event.total_steps;
    }
  }

  onMount(() => {
    const w = Math.max(100, window.innerWidth - $effectiveSidebarWidth);
    const h = window.innerHeight;

    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0a0a0a);
    scene.fog = new THREE.FogExp2(0x0a0a0a, 0.3);

    // Subtle grid on the floor
    const gridHelper = new THREE.GridHelper(4, 20, 0x1a1a1a, 0x111111);
    gridHelper.position.y = -1.5;
    scene.add(gridHelper);

    camera = new THREE.PerspectiveCamera(60, w / h, 0.01, 100);
    // Set camera at 1.5x zoom (closer than the original ~3.1 distance)
    const basePos = new THREE.Vector3(1.5, 1.2, 2.5);
    basePos.setLength(basePos.length() / 1.5);
    camera.position.copy(basePos);

    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(w, h);
    // Cap pixel ratio on mobile for performance (high-DPI phones can be 3x)
    const pixelRatio = Math.min(2, window.devicePixelRatio || 1);
    renderer.setPixelRatio(pixelRatio);
    container.appendChild(renderer.domElement);

    controls = new TrackballControls(camera, renderer.domElement);
    controls.rotateSpeed = 2.0;
    controls.noZoom = true; // We handle zoom manually (pinch only)
    controls.noPan = false;
    controls.panSpeed = 0.4;
    controls.dynamicDampingFactor = 0.15;
    controls.target.set(0, 0, 0);

    // Zoom limits (managed manually)
    const zoomMinDist = basePos.length() / 1.875; // 1.875x zoom in (1.5 × 1.25)
    const zoomMaxDist = basePos.length();        // default = furthest out
    zoomLimits = { min: zoomMinDist, max: zoomMaxDist };

    raycaster = new THREE.Raycaster();
    raycaster.params.Points = { threshold: 0.06 };
    mouse = new THREE.Vector2();

    edgesGroup = new THREE.Group();
    scene.add(edgesGroup);

    window.addEventListener("cluster-event", handleClusterEvent as EventListener);
    window.addEventListener("resize", onResize);
    renderer.domElement.addEventListener("mousedown", onMouseDown);
    renderer.domElement.addEventListener("mousemove", onMouseMove);
    renderer.domElement.addEventListener("click", onClick);
    renderer.domElement.addEventListener("wheel", onWheel, { passive: false });
    renderer.domElement.addEventListener("touchstart", onTouchStart, { passive: true });
    renderer.domElement.addEventListener("touchmove", onTouchMove, { passive: false });
    renderer.domElement.addEventListener("touchend", onTouchEnd, { passive: true });

    animFrame = requestAnimationFrame(renderLoop);

    // Replay any buffered events that arrived before mount
    const buffered = get(eventBuffer);
    for (const event of buffered) {
      handleClusterEvent(new CustomEvent("cluster-event", { detail: event }) as any);
    }

    // If loading a completed run, jump to the last step
    if (buffered.length > 0 && $totalSteps > 0) {
      $currentStep = $totalSteps;
    }

    return () => {
      window.removeEventListener("cluster-event", handleClusterEvent as EventListener);
      window.removeEventListener("resize", onResize);
      renderer.domElement.removeEventListener("mousedown", onMouseDown);
      renderer.domElement.removeEventListener("mousemove", onMouseMove);
      renderer.domElement.removeEventListener("click", onClick);
      renderer.domElement.removeEventListener("wheel", onWheel);
      renderer.domElement.removeEventListener("touchstart", onTouchStart);
      renderer.domElement.removeEventListener("touchmove", onTouchMove);
      renderer.domElement.removeEventListener("touchend", onTouchEnd);
      cancelAnimationFrame(animFrame);
      renderer.dispose();
    };
  });

  function onResize() {
    if (!renderer || !camera) return;
    const w = Math.max(100, window.innerWidth - $effectiveSidebarWidth);
    const h = window.innerHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
    if (controls) controls.handleResize();
  }

  // React to sidebar width changes
  $effect(() => {
    const _sw = $effectiveSidebarWidth;
    onResize();
  });

  /** Screen-space hit test: project all points to 2D, find nearest within pixel radius */
  function screenSpaceHitTest(clientX: number, clientY: number, maxPixelDist: number = 18): number | null {
    if (!initialized || !animatedPositions) return null;

    const rect = renderer.domElement.getBoundingClientRect();
    const screenX = clientX - rect.left;
    const screenY = clientY - rect.top;
    const hw = rect.width * 0.5;
    const hh = rect.height * 0.5;

    const pts = $points;
    const vec = new THREE.Vector3();
    let bestIdx = -1;
    let bestDist = maxPixelDist * maxPixelDist; // compare squared distances

    for (let i = 0; i < pts.length; i++) {
      const i3 = i * 3;
      vec.set(animatedPositions[i3], animatedPositions[i3 + 1], animatedPositions[i3 + 2]);
      vec.project(camera);

      // Behind camera
      if (vec.z > 1) continue;

      const px = (vec.x * hw) + hw;
      const py = (-vec.y * hh) + hh;

      const dx = px - screenX;
      const dy = py - screenY;
      const d2 = dx * dx + dy * dy;

      if (d2 < bestDist) {
        bestDist = d2;
        bestIdx = i;
      }
    }

    return bestIdx >= 0 ? bestIdx : null;
  }

  function onMouseMove(e: MouseEvent) {
    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    if (!initialized) return;

    const idx = screenSpaceHitTest(e.clientX, e.clientY);
    if (idx !== null) {
      const pt = $points[idx];
      // If clusters are pinned, only show hover for points in pinned clusters
      const pinned = $pinnedClusterIds;
      if (pinned.length > 0 && pt) {
        const cid = $pointClusterMap.get(pt.id);
        $hoveredPoint = cid && pinned.includes(cid) ? pt : null;
      } else {
        $hoveredPoint = pt || null;
      }
    } else {
      $hoveredPoint = null;
    }
  }

  function onMouseDown(e: MouseEvent) {
    dragStartX = e.clientX;
    dragStartY = e.clientY;
  }

  function onClick(e: MouseEvent) {
    if (!initialized) return;
    const dx = e.clientX - dragStartX;
    const dy = e.clientY - dragStartY;
    if (dx * dx + dy * dy > DRAG_THRESHOLD * DRAG_THRESHOLD) return;

    const idx = screenSpaceHitTest(e.clientX, e.clientY);
    const pcMap = $pointClusterMap;

    if (idx !== null) {
      const clusterId = pcMap.get($points[idx]?.id);
      if (clusterId) {
        // Toggle pin: add if not pinned, remove if already pinned
        const cur = $pinnedClusterIds;
        if (cur.includes(clusterId)) {
          $pinnedClusterIds = cur.filter((id) => id !== clusterId);
        } else {
          $pinnedClusterIds = [...cur, clusterId];
        }
      }
    } else {
      // Click on empty space: clear all pins
      if ($pinnedClusterIds.length > 0) {
        $pinnedClusterIds = [];
      }
    }
  }

  function onWheel(e: WheelEvent) {
    // Pinch-to-zoom on trackpad fires wheel events with ctrlKey=true
    // Regular two-finger scroll should NOT zoom
    if (e.ctrlKey) {
      e.preventDefault();
      if (!camera || !controls) return;

      const currentDist = camera.position.clone().sub(controls.target).length();
      const base = targetZoomDist > 0 ? targetZoomDist : currentDist;
      const factor = 1 + e.deltaY * 0.02;
      targetZoomDist = Math.max(zoomLimits.min, Math.min(zoomLimits.max, base * factor));
    }
    // Also block Cmd+scroll (browser zoom)
    if (e.metaKey) {
      e.preventDefault();
    }
  }

  function touchDistance(touches: TouchList): number {
    if (touches.length < 2) return -1;
    const dx = touches[1].clientX - touches[0].clientX;
    const dy = touches[1].clientY - touches[0].clientY;
    return Math.hypot(dx, dy);
  }

  function onTouchStart(e: TouchEvent) {
    if (e.touches.length === 2 && camera && controls) {
      pinchStartDist = touchDistance(e.touches);
      pinchStartZoom = targetZoomDist > 0 ? targetZoomDist : camera.position.clone().sub(controls.target).length();
    } else if (e.touches.length === 1) {
      tapStartX = e.touches[0].clientX;
      tapStartY = e.touches[0].clientY;
    }
  }

  function onTouchMove(e: TouchEvent) {
    if (e.touches.length === 2 && pinchStartDist > 0 && camera && controls) {
      e.preventDefault();
      const dist = touchDistance(e.touches);
      if (dist > 0) {
        const factor = dist / pinchStartDist;
        targetZoomDist = Math.max(zoomLimits.min, Math.min(zoomLimits.max, pinchStartZoom * factor));
      }
    }
    // Single touch: update hover for tooltip (use first touch)
    if (e.touches.length === 1 && initialized) {
      const t = e.touches[0];
      const idx = screenSpaceHitTest(t.clientX, t.clientY, 24);
      const pts = $points;
      const pinned = $pinnedClusterIds;
      const pcMap = $pointClusterMap;
      if (idx !== null && pts[idx]) {
        const pt = pts[idx];
        const cid = pcMap.get(pt.id);
        $hoveredPoint = pinned.length > 0 && cid && !pinned.includes(cid) ? null : pt;
      } else {
        $hoveredPoint = null;
      }
    }
  }

  function onTouchEnd(e: TouchEvent) {
    if (e.touches.length < 2) {
      pinchStartDist = -1;
      pinchStartZoom = -1;
    }
    // Tap-to-pin: single touch released with minimal movement
    if (e.changedTouches.length === 1 && initialized) {
      const t = e.changedTouches[0];
      const dx = t.clientX - tapStartX;
      const dy = t.clientY - tapStartY;
      if (dx * dx + dy * dy < DRAG_THRESHOLD * DRAG_THRESHOLD) {
        const idx = screenSpaceHitTest(t.clientX, t.clientY, 24);
        const pcMap = $pointClusterMap;
        if (idx !== null) {
          const clusterId = pcMap.get($points[idx]?.id);
          if (clusterId) {
            const cur = $pinnedClusterIds;
            if (cur.includes(clusterId)) {
              $pinnedClusterIds = cur.filter((id) => id !== clusterId);
            } else {
              $pinnedClusterIds = [...cur, clusterId];
            }
          }
        } else if ($pinnedClusterIds.length > 0) {
          $pinnedClusterIds = [];
        }
      }
    }
  }

  function renderLoop() {
    update();

    // Smooth zoom interpolation
    if (targetZoomDist > 0 && camera && controls) {
      const dir = camera.position.clone().sub(controls.target);
      const currentDist = dir.length();
      const diff = Math.abs(currentDist - targetZoomDist);
      if (diff > 0.001) {
        const newDist = currentDist + (targetZoomDist - currentDist) * 0.15;
        dir.setLength(newDist);
        camera.position.copy(controls.target).add(dir);
      } else {
        targetZoomDist = -1; // reached target, stop lerping
      }
    }

    renderer.render(scene, camera);
    controls.update();
    updateLabels();
    animFrame = requestAnimationFrame(renderLoop);
  }

  function update() {
    if (!initialized || !animatedPositions) return;

    const elapsed = (performance.now() - initTime) / 1000;
    const springT = Math.min(1, elapsed * 1.5);
    const ease = 1 - Math.pow(1 - springT, 3);

    const posAttr = pointsGeometry.getAttribute("position") as THREE.BufferAttribute;
    const colAttr = pointsGeometry.getAttribute("color") as THREE.BufferAttribute;
    const pcMap = $pointClusterMap;
    const pts = $points;
    const hCluster = $hoveredCluster;
    const pinned = $pinnedClusterIds;
    const DIM = 0.12; // dimmed brightness when another cluster is hovered/pinned

    // Determine the set of "highlighted" cluster IDs (pinned + hovered)
    const hasHighlight = hCluster !== null || pinned.length > 0;
    const highlightIds = new Set<string>(pinned);
    if (hCluster) highlightIds.add(hCluster.id);

    for (let i = 0; i < pts.length; i++) {
      const tx = targetPositions[i * 3] * ease;
      const ty = targetPositions[i * 3 + 1] * ease;
      const tz = targetPositions[i * 3 + 2] * ease;

      animatedPositions[i * 3] += (tx - animatedPositions[i * 3]) * 0.08;
      animatedPositions[i * 3 + 1] += (ty - animatedPositions[i * 3 + 1]) * 0.08;
      animatedPositions[i * 3 + 2] += (tz - animatedPositions[i * 3 + 2]) * 0.08;

      const clusterId = pcMap.get(pts[i].id);
      // Dim if there's any highlight active and this point isn't in a highlighted cluster
      const isDimmed = hasHighlight && (!clusterId || !highlightIds.has(clusterId));

      if (clusterId) {
        const [r, g, b] = hexToRGB(getClusterColor(clusterId));
        const mult = isDimmed ? DIM : 1;
        pointColors[i * 3] = r * mult;
        pointColors[i * 3 + 1] = g * mult;
        pointColors[i * 3 + 2] = b * mult;
      } else {
        const mult = isDimmed ? DIM : 1;
        pointColors[i * 3] = mult;
        pointColors[i * 3 + 1] = mult;
        pointColors[i * 3 + 2] = mult;
      }
    }

    posAttr.needsUpdate = true;
    colAttr.needsUpdate = true;

    // Rebuild edges when step changes, highlight changes, or during initial animation
    const curStep = $currentStep;
    const curHighlightKey = [...highlightIds].sort().join(",");
    if (curStep !== lastEdgeStep || curHighlightKey !== lastEdgeHoverId || elapsed < 2) {
      lastEdgeStep = curStep;
      lastEdgeHoverId = curHighlightKey;
      updateEdges();
    }
  }

  function updateEdges() {
    // Clear old edges
    while (edgesGroup.children.length > 0) {
      const child = edgesGroup.children[0];
      edgesGroup.remove(child);
      if ((child as THREE.LineSegments).geometry) (child as THREE.LineSegments).geometry.dispose();
      if ((child as THREE.LineSegments).material) ((child as THREE.LineSegments).material as THREE.Material).dispose();
    }

    const clusters = $visibleClusters;
    const hCluster = $hoveredCluster;
    const pinned = $pinnedClusterIds;
    const hasHighlight = hCluster !== null || pinned.length > 0;
    const highlightIds = new Set<string>(pinned);
    if (hCluster) highlightIds.add(hCluster.id);

    for (const cluster of clusters) {
      if (cluster.member_ids.length < 2) continue;

      const hex = getClusterColor(cluster.id);
      const color = new THREE.Color(hex);
      const isDimmed = hasHighlight && !highlightIds.has(cluster.id);
      if (isDimmed) color.multiplyScalar(0.15);

      // Resolve member IDs to array indices
      const indices: number[] = [];
      for (const pid of cluster.member_ids) {
        const idx = idToIndex.get(pid);
        if (idx !== undefined) indices.push(idx);
      }
      if (indices.length < 2) continue;

      // Compute centroid
      let cx = 0, cy = 0, cz = 0;
      const n = indices.length;
      for (const idx of indices) {
        const i3 = idx * 3;
        cx += animatedPositions[i3];
        cy += animatedPositions[i3 + 1];
        cz += animatedPositions[i3 + 2];
      }
      cx /= n; cy /= n; cz /= n;

      // Draw edges from each point to centroid (star topology)
      const edgeVerts: number[] = [];
      for (const idx of indices) {
        const i3 = idx * 3;
        edgeVerts.push(
          animatedPositions[i3], animatedPositions[i3 + 1], animatedPositions[i3 + 2],
          cx, cy, cz
        );
      }

      const edgeGeo = new THREE.BufferGeometry();
      edgeGeo.setAttribute("position", new THREE.Float32BufferAttribute(edgeVerts, 3));
      const edgeMat = new THREE.LineBasicMaterial({
        color,
        transparent: true,
        opacity: 0.18,
        linewidth: 1.2,
      });
      edgesGroup.add(new THREE.LineSegments(edgeGeo, edgeMat));

      // Also draw edges between nearby neighbors within cluster (k-nearest, k=3)
      if (n > 3 && n <= 200) {
        const neighborVerts: number[] = [];
        for (let a = 0; a < indices.length; a++) {
          const idxA = indices[a];
          const ax = animatedPositions[idxA * 3];
          const ay = animatedPositions[idxA * 3 + 1];
          const az = animatedPositions[idxA * 3 + 2];

          // Find 3 nearest neighbors
          const dists: { idx: number; d: number }[] = [];
          for (let b = 0; b < indices.length; b++) {
            if (a === b) continue;
            const idxB = indices[b];
            const dx = ax - animatedPositions[idxB * 3];
            const dy = ay - animatedPositions[idxB * 3 + 1];
            const dz = az - animatedPositions[idxB * 3 + 2];
            dists.push({ idx: idxB, d: dx * dx + dy * dy + dz * dz });
          }
          dists.sort((a, b) => a.d - b.d);
          const k = Math.min(3, dists.length);
          for (let j = 0; j < k; j++) {
            const idxB = dists[j].idx;
            neighborVerts.push(
              ax, ay, az,
              animatedPositions[idxB * 3], animatedPositions[idxB * 3 + 1], animatedPositions[idxB * 3 + 2]
            );
          }
        }

        const nGeo = new THREE.BufferGeometry();
        nGeo.setAttribute("position", new THREE.Float32BufferAttribute(neighborVerts, 3));
        const nMat = new THREE.LineBasicMaterial({
          color,
          transparent: true,
          opacity: 0.24,
          linewidth: 1.2,
        });
        edgesGroup.add(new THREE.LineSegments(nGeo, nMat));
      }
    }
  }

  function updateLabels() {
    if (!labelsContainer || !initialized) return;

    const clusters = $visibleClusters;
    const hCluster = $hoveredCluster;
    const pinned = $pinnedClusterIds;
    const hasHighlight = hCluster !== null || pinned.length > 0;
    const sorted = [...clusters].sort((a, b) => b.size - a.size);
    const maxLabels = Math.min(6, sorted.length);

    labelsContainer.innerHTML = "";

    // Build set of highlighted IDs
    const highlightIds = new Set<string>(pinned);
    if (hCluster) highlightIds.add(hCluster.id);

    // When highlighting, show only highlighted cluster labels
    // When not highlighting, show top 6 labels always
    const labelsToShow = hasHighlight
      ? sorted.filter((c) => highlightIds.has(c.id))
      : sorted.slice(0, maxLabels);

    const rect = renderer.domElement.getBoundingClientRect();

    for (const cluster of labelsToShow) {
      let cx = 0, cy = 0, cz = 0, count = 0;

      for (const pid of cluster.member_ids) {
        const idx = idToIndex.get(pid);
        if (idx === undefined) continue;
        const i3 = idx * 3;
        if (!animatedPositions || i3 + 2 >= animatedPositions.length) continue;
        cx += animatedPositions[i3];
        cy += animatedPositions[i3 + 1];
        cz += animatedPositions[i3 + 2];
        count++;
      }
      if (count === 0) continue;
      cx /= count; cy /= count; cz /= count;

      const vec = new THREE.Vector3(cx, cy, cz);
      vec.project(camera);

      const sx = (vec.x * 0.5 + 0.5) * rect.width;
      const sy = (-vec.y * 0.5 + 0.5) * rect.height;

      // Clamp to visible area (keep labels on-screen even if centroid is at edge)
      const clampedX = Math.max(10, Math.min(rect.width - 10, sx));
      const clampedY = Math.max(10, Math.min(rect.height - 10, sy));

      const label = document.createElement("div");
      label.className = "label-3d";
      label.textContent = cluster.canonical;
      label.style.left = `${clampedX}px`;
      label.style.top = `${clampedY}px`;
      labelsContainer.appendChild(label);
    }
  }
</script>

<div
  class="map3d-container"
  bind:this={container}
  style="position:fixed; top:0; left:{$effectiveSidebarWidth}px; width:calc(100vw - {$effectiveSidebarWidth}px); height:100vh;"
>
</div>

<div
  class="labels-overlay"
  bind:this={labelsContainer}
  style="position:fixed; top:0; left:{$effectiveSidebarWidth}px; width:calc(100vw - {$effectiveSidebarWidth}px); height:100vh; pointer-events:none; z-index:10;"
>
</div>

<style>
  .map3d-container {
    overflow: hidden;
    background: #0a0a0a;
  }

  .map3d-container :global(canvas) {
    display: block;
  }

  .labels-overlay :global(.label-3d) {
    position: absolute;
    transform: translate(-50%, -50%);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 10px;
    line-height: 1.3;
    color: rgba(255, 255, 255, 0.75);
    background: none;
    padding: 0;
    max-width: 130px;
    text-align: center;
    word-wrap: break-word;
    pointer-events: none;
  }
</style>
