<script lang="ts">
  import Icon from "@iconify/svelte";
  import type { Prompt } from "$lib/types/prompt-library";
  import { replacePlaceholders } from "$lib/utils/prompt-placeholders";

  let {
    prompts = [],
    onSelect,
  }: {
    prompts: Prompt[];
    onSelect: (resolvedQuery: string, prompt: Prompt) => void;
  } = $props();

  function handleClick(prompt: Prompt) {
    onSelect(replacePlaceholders(prompt.query), prompt);
  }
</script>

{#if prompts.length > 0}
  <div class="relative z-10 mt-6 flex w-full max-w-2xl flex-col items-center gap-3 px-4">
    <span class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
      Try one of these
    </span>
    <div class="flex flex-wrap items-center justify-center gap-2">
      {#each prompts as prompt (prompt.id)}
        <button
          type="button"
          class="group inline-flex items-center gap-1.5 rounded-full border border-border bg-card/80 px-3.5 py-1.5 text-xs text-foreground/80 shadow-sm backdrop-blur-sm transition-all hover:border-primary/60 hover:bg-primary/5 hover:text-primary hover:shadow-md"
          title={prompt.query}
          onclick={() => handleClick(prompt)}
        >
          {#if prompt.is_user_prompt}
            <Icon
              icon="mdi:lock"
              class="size-3.5 shrink-0 text-amber-500"
            />
          {:else}
            <Icon
              icon="mdi:lightbulb-outline"
              class="size-3.5 shrink-0 text-muted-foreground transition-colors group-hover:text-primary"
            />
          {/if}
          <span class="max-w-[200px] truncate font-medium">
            {prompt.title}
          </span>
        </button>
      {/each}
    </div>
  </div>
{/if}
