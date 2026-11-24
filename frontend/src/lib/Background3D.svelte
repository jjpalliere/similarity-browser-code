<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import * as THREE from "three";

  let canvas: HTMLCanvasElement;
  let animId: number;
  let renderer: THREE.WebGLRenderer;

  const POINT_COUNT = 300;
  const SPHERE_RADIUS = 1.8;
  const MIN_DOT = 0.0023;
  const MAX_DOT = 0.009;
  const AUTO_ROTATE_SPEED = 0.0008;
  const MOUSE_INFLUENCE = 0.3;
  const MOUSE_LERP = 0.05;
  const NUM_CLUSTERS = 8;
  const LINE_OPACITY = 0.375;

  const CLUSTER_COLORS_HEX = [
    0x6366f1, 0xec4899, 0x14b8a6, 0xf59e0b, 0x8b5cf6,
    0xef4444, 0x22c55e, 0x3b82f6, 0xf97316, 0xa855f7,
    0x06b6d4, 0xe11d48, 0x84cc16, 0x0ea5e9, 0xd946ef,
  ];

  const BLINK_GROUPS = [
    { period: 3.0, duty: 0.12 },
    { period: 4.5, duty: 0.10 },
    { period: 2.2, duty: 0.18 },
    { period: 5.5, duty: 0.08 },
    { period: 1.8, duty: 0.15 },
    { period: 7.0, duty: 0.06 },
  ];
  const BLINK_INTENSITY = 0.3;

  onMount(() => {
    const CLUSTER_COLORS = CLUSTER_COLORS_HEX.map((h) => new THREE.Color(h));

    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0a0a0a);
    scene.fog = new THREE.FogExp2(0x0a0a0a, 0.15);

    const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.01, 100);
    camera.position.set(1.5, 1.0, 2.5);
    camera.lookAt(0, 0, 0);

    const grid = new THREE.GridHelper(4, 20, 0x1a1a1a, 0x111111);
    grid.position.y = -1.5;
    scene.add(grid);

    // Generate points
    const pointData: { x: number; y: number; z: number; cluster: number; size: number }[] = [];
    const clusterCentroids = Array.from({ length: NUM_CLUSTERS }, () => ({ x: 0, y: 0, z: 0, count: 0 }));

    for (let i = 0; i < POINT_COUNT; i++) {
      const u = Math.random();
      const v = Math.random();
      const theta = 2 * Math.PI * u;
      const phi = Math.acos(2 * v - 1);
      const r = SPHERE_RADIUS * Math.cbrt(Math.random());
      const x = r * Math.sin(phi) * Math.cos(theta);
      const y = r * Math.sin(phi) * Math.sin(theta);
      const z = r * Math.cos(phi);
      const ci = Math.floor(((theta + Math.PI) / (2 * Math.PI)) * NUM_CLUSTERS) % NUM_CLUSTERS;
      const dotSize = MIN_DOT + Math.sqrt(Math.random()) * (MAX_DOT - MIN_DOT);
      pointData.push({ x, y, z, cluster: ci, size: dotSize });
      clusterCentroids[ci].x += x;
      clusterCentroids[ci].y += y;
      clusterCentroids[ci].z += z;
      clusterCentroids[ci].count++;
    }

    for (const c of clusterCentroids) {
      const n = c.count || 1;
      c.x /= n; c.y /= n; c.z /= n;
    }

    // Instanced dots
    const dotGeo = new THREE.SphereGeometry(1, 8, 6);
    const dotMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.85 });
    const dots = new THREE.InstancedMesh(dotGeo, dotMat, POINT_COUNT);
    const dummy = new THREE.Object3D();
    const baseColors: THREE.Color[] = [];
    const blinkGroup = new Uint8Array(POINT_COUNT);
    const blinkPhase = new Float32Array(POINT_COUNT);

    for (let i = 0; i < POINT_COUNT; i++) {
      const p = pointData[i];
      dummy.position.set(p.x, p.y, p.z);
      dummy.scale.setScalar(p.size);
      dummy.updateMatrix();
      dots.setMatrixAt(i, dummy.matrix);
      const baseCol = CLUSTER_COLORS[p.cluster % CLUSTER_COLORS.length];
      baseColors.push(baseCol.clone());
      dots.setColorAt(i, baseCol);
      blinkGroup[i] = Math.floor(Math.random() * BLINK_GROUPS.length);
      blinkPhase[i] = Math.random() * Math.PI * 2;
    }
    dots.instanceMatrix.needsUpdate = true;
    if (dots.instanceColor) dots.instanceColor.needsUpdate = true;
    scene.add(dots);

    const white = new THREE.Color(1, 1, 1);
    const blinkTmp = new THREE.Color();

    // Connector lines
    const lineVerts: number[] = [];
    const lineColors: number[] = [];
    for (let i = 0; i < POINT_COUNT; i++) {
      const p = pointData[i];
      const cent = clusterCentroids[p.cluster];
      lineVerts.push(p.x, p.y, p.z, cent.x, cent.y, cent.z);
      const lc = CLUSTER_COLORS[p.cluster % CLUSTER_COLORS.length];
      lineColors.push(lc.r, lc.g, lc.b, lc.r, lc.g, lc.b);
    }
    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute("position", new THREE.Float32BufferAttribute(lineVerts, 3));
    lineGeo.setAttribute("color", new THREE.Float32BufferAttribute(lineColors, 3));
    const lineMat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: LINE_OPACITY, depthWrite: false });
    scene.add(new THREE.LineSegments(lineGeo, lineMat));

    // Mouse tracking
    let mouseX = 0, mouseY = 0, targetX = 0, targetY = 0;
    let prevMouseX = 0;
    let spinVelocity = AUTO_ROTATE_SPEED;
    const SPIN_FRICTION = 0.97;
    const MOUSE_SPIN_GAIN = 0.003;

    function onMouseMove(e: MouseEvent) {
      const newMouseX = (e.clientX / window.innerWidth) * 2 - 1;
      spinVelocity += (newMouseX - prevMouseX) * MOUSE_SPIN_GAIN;
      prevMouseX = newMouseX;
      mouseX = newMouseX;
      mouseY = (e.clientY / window.innerHeight) * 2 - 1;
    }
    document.addEventListener("mousemove", onMouseMove);

    let angle = 0;

    function animate() {
      animId = requestAnimationFrame(animate);

      spinVelocity *= SPIN_FRICTION;
      if (Math.abs(spinVelocity) < AUTO_ROTATE_SPEED) {
        spinVelocity = spinVelocity >= 0 ? AUTO_ROTATE_SPEED : -AUTO_ROTATE_SPEED;
      }
      angle += spinVelocity;
      const baseX = Math.sin(angle) * 2.5;
      const baseZ = Math.cos(angle) * 2.5;

      targetX += (mouseX - targetX) * MOUSE_LERP;
      targetY += (mouseY - targetY) * MOUSE_LERP;

      camera.position.x = baseX + targetX * MOUSE_INFLUENCE;
      camera.position.y = 1.0 - targetY * MOUSE_INFLUENCE * 0.5;
      camera.position.z = baseZ;
      camera.lookAt(0, 0, 0);

      const t = performance.now() * 0.001;
      for (let i = 0; i < POINT_COUNT; i++) {
        const grp = BLINK_GROUPS[blinkGroup[i]];
        const pos = ((t + blinkPhase[i] * grp.period) % grp.period) / grp.period;
        const bright = pos < grp.duty ? Math.sin((pos / grp.duty) * Math.PI) * BLINK_INTENSITY : 0;
        blinkTmp.copy(baseColors[i]).lerp(white, bright);
        dots.setColorAt(i, blinkTmp);
      }
      dots.instanceColor!.needsUpdate = true;

      renderer.render(scene, camera);
    }
    animate();

    function onResize() {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    }
    window.addEventListener("resize", onResize);

    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("resize", onResize);
    };
  });

  onDestroy(() => {
    if (animId) cancelAnimationFrame(animId);
    if (renderer) renderer.dispose();
  });
</script>

<canvas bind:this={canvas} class="bg-canvas"></canvas>

<style>
  .bg-canvas {
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
  }
</style>
