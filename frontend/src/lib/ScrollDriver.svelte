<script lang="ts">
  import { currentStep, totalSteps, steps } from "../stores/cluster";
  import { scrollProgress } from "../stores/viewport";

  let accumulated = $state(0);
  let lastExternalStep = $state(0);
  const SCROLL_PER_STEP = 150;

  // Sync accumulated when currentStep is changed externally (e.g. during live clustering)
  $effect(() => {
    const cs = $currentStep;
    if (cs !== lastExternalStep) {
      accumulated = cs * SCROLL_PER_STEP;
      lastExternalStep = cs;
      const maxSteps = $totalSteps || $steps.length || 1;
      $scrollProgress = cs / maxSteps;
    }
  });

  $effect(() => {
    function onWheel(e: WheelEvent) {
      if (e.metaKey || e.ctrlKey) return;

      // Don't capture scroll inside the sidebar
      const target = e.target as HTMLElement;
      if (target.closest(".sidebar")) return;

      e.preventDefault();
      accumulated += e.deltaY;

      const maxSteps = $totalSteps || $steps.length || 1;
      accumulated = Math.max(0, Math.min(maxSteps * SCROLL_PER_STEP, accumulated));

      const rawStep = accumulated / SCROLL_PER_STEP;
      const clamped = Math.max(0, Math.min(maxSteps, rawStep));
      const newStep = Math.round(clamped);

      lastExternalStep = newStep;
      $currentStep = newStep;
      $scrollProgress = clamped / maxSteps;
    }

    window.addEventListener("wheel", onWheel, { passive: false });
    return () => window.removeEventListener("wheel", onWheel);
  });
</script>
