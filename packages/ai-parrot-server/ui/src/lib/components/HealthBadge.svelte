<!--
  HealthBadge (TASK-2529) — status pill for a single dependency's health
  (`DependencyHealth.status` from GET /api/v1/admin/status), reused by
  Dashboard's dependency list and any future dashboard.

  Status -> appearance mapping (spec §3 Module 5):
    ok           -> green (success token)
    unreachable  -> destructive (Badge's built-in "destructive" variant)
    unconfigured -> muted
-->
<script lang="ts">
  import { Badge } from "$lib/ui/internal/shadcn/ui/badge/index.js";
  import type { DependencyHealth } from "$lib/types/generated/DependencyHealth";

  type Status = DependencyHealth["status"];

  let {
    status,
    detail = null,
    latencyMs = null,
  }: {
    status: Status;
    detail?: string | null;
    latencyMs?: number | null;
  } = $props();

  const labels: Record<Status, string> = {
    ok: "OK",
    unreachable: "Unreachable",
    unconfigured: "Unconfigured",
  };

  const okUnconfiguredClasses: Record<Exclude<Status, "unreachable">, string> = {
    ok: "border-success/30 bg-success/10 text-success",
    unconfigured: "border-border bg-muted text-muted-foreground",
  };

  const title = $derived(
    [detail, latencyMs != null ? `${latencyMs}ms` : null].filter(Boolean).join(" · ") ||
      undefined,
  );
</script>

<Badge
  variant={status === "unreachable" ? "destructive" : "outline"}
  class={status === "unreachable" ? "" : okUnconfiguredClasses[status]}
  data-testid={`health-badge-${status}`}
  {title}
>
  {labels[status]}
</Badge>
