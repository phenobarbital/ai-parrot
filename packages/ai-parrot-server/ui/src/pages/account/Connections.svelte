<!-- Account › Connections (FEAT-777). -->
<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import ConnectionsPanel from "$lib/components/account/ConnectionsPanel.svelte";
  import { connectionsStore } from "$lib/stores/connections.svelte";
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "$lib/ui/internal/shadcn/ui/card/index.js";

  onMount(() => {
    connectionsStore.start();
    void connectionsStore.refresh();
  });

  onDestroy(() => connectionsStore.stop());
</script>

<div class="flex max-w-5xl flex-col gap-6">
  <Card>
    <CardHeader>
      <CardTitle>Connections</CardTitle>
      <CardDescription>Manage the accounts and channels connected to your Navigator account.</CardDescription>
    </CardHeader>
    <CardContent>
      <ConnectionsPanel />
    </CardContent>
  </Card>
</div>
