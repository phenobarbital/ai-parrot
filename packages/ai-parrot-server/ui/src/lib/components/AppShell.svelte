<!--
  AppShell (TASK-2528) — persistent authenticated layout: Sidebar + Topbar
  + routed content area. Rendered by App.svelte for every non-login route
  (all of which require auth — enforced by Router.guard(), not here).
-->
<script lang="ts">
  import type { Snippet } from "svelte";

  import Sidebar from "./Sidebar.svelte";
  import Topbar from "./Topbar.svelte";

  interface Props {
    children: Snippet;
  }

  let { children }: Props = $props();
</script>

<div class="bg-background text-foreground flex h-screen">
  <Sidebar />
  <div class="flex flex-1 flex-col overflow-hidden">
    <Topbar />
    <main class="flex-1 overflow-auto p-6">
      {@render children()}
    </main>
  </div>
</div>
