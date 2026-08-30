<script lang="ts">
  import Icon from "@iconify/svelte";
  import { AppTooltip } from "$lib/ui/components";
  import type { SourceLink } from "$lib/types/bot-chat.js";

  let { sources }: { sources: SourceLink[] } = $props();

  let showSources = $state(false);
</script>

<div class="mt-2">
  <AppTooltip content={`Show sources (${sources.length})`} placement="bottom">
    <button
      class="inline-flex items-center justify-center size-7 rounded-md text-blue-600 bg-blue-50 hover:bg-blue-100 transition-colors"
      onclick={() => (showSources = !showSources)}
    >
      <Icon icon="mdi:book-open-page-variant-outline" class="size-3.5" />
    </button>
  </AppTooltip>

  {#if showSources}
    <div class="mt-3 animate-in fade-in slide-in-from-top-2 duration-200">
      <ul class="max-h-48 overflow-y-auto space-y-0.5">
        {#each sources as source}
          <li class="flex items-center gap-2 py-1">
            {#if source.type === "video"}
              <Icon
                icon={source.icon ?? "mdi:youtube"}
                class="size-4 text-red-500 shrink-0"
              />
            {:else if source.type === "document"}
              <Icon
                icon={source.icon ?? "mdi:file-document-outline"}
                class="size-4 text-blue-500 shrink-0"
              />
            {:else}
              <Icon
                icon={source.icon ?? "mdi:web"}
                class="size-4 text-slate-500 shrink-0"
              />
            {/if}
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              class="text-xs text-blue-600 dark:text-blue-400 hover:underline truncate"
            >
              {source.title}
            </a>
          </li>
        {/each}
      </ul>
    </div>
  {/if}
</div>
