<!--
  App.svelte (TASK-2528) — wires the Router's route table, resolves the
  active page against the current path, guards non-login routes, and
  wraps authenticated pages in AppShell (login renders full-screen,
  outside the shell).
-->
<script lang="ts">
  import { onMount } from "svelte";
  import type { Component } from "svelte";

  import { config } from "$lib/config";
  import { router, type RouteDefinition } from "$lib/router.svelte";
  import { authStore } from "$lib/stores/auth.svelte";
  import { themeStore } from "$lib/stores/theme.svelte";
  import AppShell from "$lib/components/AppShell.svelte";

  router.routes = [
    { path: "/admin/login", component: () => import("./pages/Login.svelte") },
    { path: "/admin/home", component: () => import("./pages/Home.svelte"), requiresAuth: true },
    {
      path: "/admin/dashboard",
      component: () => import("./pages/Dashboard.svelte"),
      requiresAuth: true,
    },
    {
      path: "/admin/agents",
      component: () => import("./pages/Agents.svelte"),
      requiresAuth: true,
    },
  ];

  let ActiveComponent = $state<Component | null>(null);
  let activeRoute = $state<RouteDefinition | null>(null);

  function fallbackPath(): string {
    return authStore.isAuthenticated ? "/admin/home" : config.loginPath;
  }

  async function resolve(): Promise<void> {
    // Normalize the bare mount root to home (authenticated) or login.
    if (router.path === config.basePath || router.path === `${config.basePath}/`) {
      router.navigate(fallbackPath(), { replace: true });
      // Recurse immediately rather than relying on the $effect below to
      // re-fire on the mutated `router.path` — deterministic within a
      // single resolution pass (also correct under SSR-less unit tests,
      // where effect re-scheduling timing is otherwise a race).
      return resolve();
    }

    const matched = router.match(router.path);
    if (!matched) {
      router.navigate(fallbackPath(), { replace: true });
      return resolve();
    }

    if (!router.guard(router.path)) {
      // guard() already navigated to login with ?next=.
      return resolve();
    }

    const mod = await matched.component();
    activeRoute = matched;
    ActiveComponent = mod.default as Component;
  }

  $effect(() => {
    // Establish the reactive dependency on router.path, then resolve.
    void router.path;
    resolve();
  });

  onMount(() => {
    themeStore.init();
  });
</script>

{#if ActiveComponent}
  {#if activeRoute?.requiresAuth}
    <AppShell>
      <ActiveComponent />
    </AppShell>
  {:else}
    <ActiveComponent />
  {/if}
{/if}
