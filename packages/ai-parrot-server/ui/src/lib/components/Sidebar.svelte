<!--
  Sidebar (TASK-2528) — driven entirely by the nav.ts registry so future
  module specs append entries without touching this component.
-->
<script lang="ts">
  import { navEntries } from "$lib/nav";
  import { router } from "$lib/router.svelte";

  function isActive(path: string): boolean {
    return router.path === path;
  }

  function navigate(path: string, event: MouseEvent) {
    event.preventDefault();
    router.navigate(path);
  }
</script>

<nav class="border-border bg-card flex h-full w-56 flex-col gap-1 border-r p-3" aria-label="Main">
  {#each navEntries as entry (entry.path)}
    <a
      href={entry.path}
      onclick={(event) => navigate(entry.path, event)}
      class={[
        "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
        isActive(entry.path)
          ? "bg-primary text-primary-foreground"
          : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
      ].join(" ")}
      aria-current={isActive(entry.path) ? "page" : undefined}
    >
      <svg
        class="h-4 w-4 shrink-0"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        aria-hidden="true"
      >
        <path d={entry.icon} stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      {entry.label}
    </a>
  {/each}
</nav>
