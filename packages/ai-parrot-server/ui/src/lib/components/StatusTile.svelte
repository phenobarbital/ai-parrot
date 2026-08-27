<!--
  StatusTile (TASK-2529) — small label/value stat tile (version, uptime,
  agent counts, crews) reused by Dashboard.svelte and any future
  dashboard, per the task Scope.
-->
<script lang="ts">
  import { Card, CardContent, CardHeader, CardTitle } from "$lib/ui/internal/shadcn/ui/card/index.js";
  import { Skeleton } from "$lib/ui/internal/shadcn/ui/skeleton/index.js";

  let {
    label,
    value,
    loading = false,
  }: {
    label: string;
    value?: string | number;
    loading?: boolean;
  } = $props();

  const testId = $derived(`status-tile-${label.toLowerCase().replace(/\s+/g, "-")}`);
</script>

<Card data-testid={testId}>
  <CardHeader class="pb-2">
    <CardTitle class="text-muted-foreground text-xs font-medium tracking-wide uppercase">
      {label}
    </CardTitle>
  </CardHeader>
  <CardContent>
    {#if loading}
      <Skeleton class="h-7 w-16" data-testid={`${testId}-skeleton`} />
    {:else}
      <p class="text-2xl font-semibold">{value}</p>
    {/if}
  </CardContent>
</Card>
