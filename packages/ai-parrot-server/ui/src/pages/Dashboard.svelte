<!--
  Dashboard page (TASK-2529) — status dashboard consuming GET
  /api/v1/admin/status via the GENERATED `AdminStatus` type (TASK-2526
  output). Route /admin/dashboard.
-->
<script lang="ts" module>
  /**
   * Format a duration in seconds as a compact "3d 4h 12m" string.
   * Pure helper — exported for a dedicated unit test (Dashboard.test.ts).
   */
  export function formatUptime(totalSeconds: number): string {
    if (!Number.isFinite(totalSeconds) || totalSeconds < 0) return "0s";

    const seconds = Math.floor(totalSeconds);
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;

    if (days > 0) return `${days}d ${hours}h ${minutes}m`;
    if (hours > 0) return `${hours}h ${minutes}m`;
    if (minutes > 0) return `${minutes}m ${secs}s`;
    return `${secs}s`;
  }
</script>

<script lang="ts">
  import apiClient, { ApiError } from "$lib/api/http";
  import type { AdminStatus } from "$lib/types/generated/AdminStatus";
  import HealthBadge from "$lib/components/HealthBadge.svelte";
  import StatusTile from "$lib/components/StatusTile.svelte";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import { Card, CardContent, CardHeader, CardTitle } from "$lib/ui/internal/shadcn/ui/card/index.js";

  const REFRESH_INTERVAL_MS = 15_000;
  const STATUS_URL = "/api/v1/admin/status";

  let status = $state<AdminStatus | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let lastUpdated = $state<Date | null>(null);

  /**
   * Fetch the status payload. Deliberately reads no reactive `$state`
   * before its first `await` — the polling `$effect` below calls this
   * synchronously on mount, and any state read at that point would be
   * captured as an effect dependency, re-triggering the effect (and its
   * `setInterval`) every time this function later WRITES that same state,
   * turning the 15s poll into a request-storm. Only writes happen in the
   * synchronous portion; state reads happen after the `await`.
   */
  async function fetchStatus(): Promise<void> {
    loading = true;
    try {
      const { data } = await apiClient.get<AdminStatus>(STATUS_URL);
      status = data;
      error = null;
      lastUpdated = new Date();
    } catch (err) {
      error = err instanceof ApiError ? err.message : "Failed to load status";
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    fetchStatus();
    const intervalId = setInterval(fetchStatus, REFRESH_INTERVAL_MS);
    return () => clearInterval(intervalId);
  });
</script>

{#if error && status === null}
  <Card data-testid="dashboard-retry-card">
    <CardHeader>
      <CardTitle>Unable to load status</CardTitle>
    </CardHeader>
    <CardContent class="flex flex-col gap-3">
      <p class="text-muted-foreground text-sm">{error}</p>
      <Button class="w-fit" onclick={() => fetchStatus()}>Retry</Button>
    </CardContent>
  </Card>
{:else}
  <div class="flex flex-col gap-4">
    <div class="flex items-center justify-between">
      <span class="text-muted-foreground text-sm">
        {#if lastUpdated}Last updated {lastUpdated.toLocaleTimeString()}{/if}
      </span>
      <Button variant="outline" size="sm" onclick={() => fetchStatus()}>Refresh</Button>
    </div>

    <div class="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
      <StatusTile label="Version" value={status?.version} loading={loading && !status} />
      <StatusTile
        label="Uptime"
        value={status ? formatUptime(status.uptime_seconds) : undefined}
        loading={loading && !status}
      />
      <StatusTile label="Crews" value={status?.crews} loading={loading && !status} />
      <StatusTile
        label="Agents (DB)"
        value={status?.agents.database}
        loading={loading && !status}
      />
      <StatusTile
        label="Agents (Registry)"
        value={status?.agents.registry}
        loading={loading && !status}
      />
      <StatusTile
        label="Agents (Loaded)"
        value={status?.agents.loaded}
        loading={loading && !status}
      />
    </div>

    {#if status}
      <Card>
        <CardHeader>
          <CardTitle>Dependencies</CardTitle>
        </CardHeader>
        <CardContent class="flex flex-col gap-2">
          {#each Object.entries(status.dependencies) as [name, health] (name)}
            <div class="border-border flex items-center justify-between border-b py-2 last:border-0">
              <span class="text-sm font-medium capitalize">{name.replace(/_/g, " ")}</span>
              <HealthBadge
                status={health.status}
                detail={health.detail ?? null}
                latencyMs={health.latency_ms ?? null}
              />
            </div>
          {/each}
        </CardContent>
      </Card>
    {/if}
  </div>
{/if}
