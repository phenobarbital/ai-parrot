<!--
  ai-parrot (FEAT-476 TASK-2594): TEMPORARY build-resolution placeholder.

  Vite/Rollup resolve a literal dynamic-import specifier (e.g.
  `import("./X.svelte")`) at transform/bundle time regardless of the
  surrounding `{#if features.x}` runtime guard — `@vite-ignore` only
  suppresses the warning for genuinely non-analyzable (variable/template)
  specifiers, not resolution of a literal string. Without a file at this
  path, both `vite build` and any test that loads the importing
  component fail even when the flag is off and the branch never executes
  (verified empirically against vite@5.4.21 / rollup@4.63 while
  implementing this task).

  This stub exists solely to keep the gated import resolvable. TASK-2596
  must REPLACE this file wholesale with the real vendored component —
  do not extend it.
-->
<script lang="ts">
  // Intentionally empty — never rendered while its feature flag is off,
  // and there is no real implementation here yet.
  let _props = $props();
</script>
