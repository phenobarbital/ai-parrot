<!--
  Home page (TASK-2529) — welcome page: server identity (name + version
  from GET /api/v1/admin/status) and navigation cards to Dashboard and
  Agents, driven by the nav.ts registry. Route /admin/home.
-->
<script lang="ts">
  import apiClient from "$lib/api/http";
  import type { AdminStatus } from "$lib/types/generated/AdminStatus";
  import { navEntries } from "$lib/nav";
  import { router } from "$lib/router.svelte";
  import { Card, CardContent, CardHeader, CardTitle } from "$lib/ui/internal/shadcn/ui/card/index.js";

  let identity = $state<{ name: string; version: string } | null>(null);

  $effect(() => {
    // One-shot fetch — no polling needed for the welcome banner; the
    // Dashboard page owns the auto-refreshing status view.
    apiClient
      .get<AdminStatus>("/api/v1/admin/status")
      .then(({ data }) => {
        identity = { name: data.name, version: data.version };
      })
      .catch(() => {
        // Best-effort — the welcome banner just omits identity on failure.
        identity = null;
      });
  });

  const cards = $derived(navEntries.filter((entry) => entry.path !== "/admin/home"));
</script>

<div class="flex flex-col gap-6">
  <Card>
    <CardHeader>
      <CardTitle class="text-xl">
        Welcome to {identity?.name ?? "AI-Parrot"} Admin
      </CardTitle>
    </CardHeader>
    <CardContent>
      <p class="text-muted-foreground text-sm">
        {#if identity}
          Server version {identity.version}.
        {:else}
          Manage agents, crews, and server status from one place.
        {/if}
      </p>
    </CardContent>
  </Card>

  <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
    {#each cards as entry (entry.path)}
      <a href={entry.path} onclick={(event) => (event.preventDefault(), router.navigate(entry.path))}>
        <Card class="hover:border-primary/50 transition-colors">
          <CardHeader>
            <CardTitle class="text-base">{entry.label}</CardTitle>
          </CardHeader>
          <CardContent>
            <p class="text-muted-foreground text-sm">Go to {entry.label}</p>
          </CardContent>
        </Card>
      </a>
    {/each}
  </div>
</div>
