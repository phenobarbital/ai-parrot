<script lang="ts">
  import Icon from "@iconify/svelte";
  import type { Prompt } from "$lib/types/prompt-library";
  import { replacePlaceholders } from "$lib/utils/prompt-placeholders";

  let {
    prompts = [],
    onSelect,
    onConfigure,
    compact = false,
    showConfigButton = true,
    maxVisible = 0,
    scrollable = false,
  }: {
    prompts: Prompt[];
    onSelect: (resolvedQuery: string, prompt: Prompt) => void;
    onConfigure: () => void;
    compact?: boolean;
    showConfigButton?: boolean;
    maxVisible?: number;
    // Single-row mode: pills don't wrap so a parent with overflow-x-auto
    // scrolls them horizontally instead.
    scrollable?: boolean;
  } = $props();

  // Group by origin so colors don't interleave: system (info) first, then the
  // user's own (warning), mirroring the modal's list order. When maxVisible
  // caps the row, system prompts claim the slots FIRST so they're never hidden
  // behind user prompts (the cap is applied per-group, not on the merged list).
  let allSystemPrompts = $derived(prompts.filter((p) => !p.is_user_prompt));
  let allOwnPrompts = $derived(prompts.filter((p) => p.is_user_prompt));
  let systemPrompts = $derived(
    maxVisible > 0 ? allSystemPrompts.slice(0, maxVisible) : allSystemPrompts,
  );
  let ownPrompts = $derived(
    maxVisible > 0
      ? allOwnPrompts.slice(0, Math.max(0, maxVisible - systemPrompts.length))
      : allOwnPrompts,
  );
  let hiddenCount = $derived(
    maxVisible > 0
      ? Math.max(0, prompts.length - systemPrompts.length - ownPrompts.length)
      : 0,
  );

  function handlePillClick(prompt: Prompt) {
    // Replace placeholders before passing to parent
    const resolvedQuery = replacePlaceholders(prompt.query);
    onSelect(resolvedQuery, prompt);
  }

  // Size classes based on compact mode
  const btnSize = $derived(compact ? "btn-xs" : "btn-sm");
  const iconSize = $derived(compact ? "h-3 w-3" : "h-3.5 w-3.5");
  const textSize = $derived(compact ? "text-[10px]" : "text-xs");
  const padding = $derived(compact ? "py-0.5 px-2" : "py-1 px-3");
</script>

{#snippet pill(prompt: Prompt)}
  <!-- User prompts are amber-tinted; system (public) prompts are blue-tinted -->
  <button
    type="button"
    class="btn {btnSize} {prompt.is_user_prompt
      ? 'bg-warning/10 border-warning/40'
      : 'bg-info/10 border-info/40'} shadow-sm hover:shadow-md
                 group rounded-full font-normal normal-case shrink-0
                 hover:border-primary hover:text-primary
                 transition-all gap-1 h-auto {padding}"
    title={prompt.query}
    onclick={() => handlePillClick(prompt)}
  >
    {#if prompt.is_user_prompt}
      <Icon icon="mdi:lock" class="{iconSize} text-amber-500 shrink-0" />
    {:else}
      <Icon
        icon="mdi:lightbulb-outline"
        class="{iconSize} text-info group-hover:text-primary transition-colors shrink-0"
      />
    {/if}
    <span
      class="{textSize} text-base-content/70 group-hover:text-primary transition-colors truncate max-w-[120px]"
    >
      {prompt.title}
    </span>
  </button>
{/snippet}

<div
  class="flex items-center gap-1.5 {scrollable ? 'flex-nowrap' : 'flex-wrap'}"
>
  {#each systemPrompts as prompt (prompt.id)}
    {@render pill(prompt)}
  {/each}

  {#if systemPrompts.length > 0 && ownPrompts.length > 0}
    <span class="mx-1 h-4 w-px shrink-0 bg-base-300" aria-hidden="true"></span>
  {/if}

  {#each ownPrompts as prompt (prompt.id)}
    {@render pill(prompt)}
  {/each}

  {#if hiddenCount > 0}
    <span class="{textSize} text-base-content/50 px-1">
      +{hiddenCount} more
    </span>
  {/if}

  {#if showConfigButton}
    <button
      type="button"
      class="btn {btnSize} btn-ghost btn-circle shrink-0 text-base-content/50 hover:text-primary
                   hover:bg-primary/10 transition-colors"
      title="Configure Prompt Library"
      onclick={onConfigure}
    >
      <Icon icon="mdi:cog" class={iconSize} />
    </button>
  {/if}
</div>
