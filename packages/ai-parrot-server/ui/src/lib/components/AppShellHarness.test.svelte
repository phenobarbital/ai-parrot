<!--
  Test-only harness for AppShell.test.ts: AppShell requires a `children`
  snippet prop (Svelte 5), which @testing-library/svelte's render() cannot
  supply directly — this tiny wrapper provides one.
-->
<script lang="ts">
  import AppShell from "./AppShell.svelte";
</script>

<AppShell>
  <p>content</p>
</AppShell>
