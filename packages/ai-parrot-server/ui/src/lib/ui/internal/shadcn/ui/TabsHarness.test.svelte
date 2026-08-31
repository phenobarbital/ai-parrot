<!--
  Test-only harness for vendored-primitives.test.ts: Tabs is a compound
  component (Root/List/Trigger/Content) that needs real markup composed
  around it — @testing-library/svelte's render() cannot supply that
  directly for a bare Root import, so this tiny wrapper provides it
  (same pattern as AppShellHarness.test.svelte).
-->
<script lang="ts">
  import { Tabs, TabsContent, TabsList, TabsTrigger } from "./tabs/index.js";
</script>

<Tabs value="general">
  <TabsList>
    <TabsTrigger value="general">General</TabsTrigger>
    <TabsTrigger value="behavior">Behavior</TabsTrigger>
  </TabsList>
  <TabsContent value="general">General tab content</TabsContent>
  <TabsContent value="behavior">Behavior tab content</TabsContent>
</Tabs>
