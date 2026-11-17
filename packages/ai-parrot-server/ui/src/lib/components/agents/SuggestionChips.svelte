<script lang="ts">
  import type { AgentChatSuggestion } from "$lib/types/generated/AgentChatResponse";

  let {
    suggestions,
    disabled = false,
    onSelect,
  }: {
    suggestions: AgentChatSuggestion[];
    disabled?: boolean;
    onSelect: (s: AgentChatSuggestion) => void;
  } = $props();
</script>

{#if suggestions && suggestions.length > 0}
  <div class="mt-2 flex flex-wrap gap-1.5" data-testid="suggestion-chips">
    {#each suggestions as s, i (s.label + i)}
      <button
        type="button"
        class="btn btn-xs btn-outline rounded-full"
        data-kind={s.kind}
        data-testid="suggestion-chip"
        title={s.prompt}
        {disabled}
        onclick={() => onSelect(s)}
      >
        {s.label}
      </button>
    {/each}
  </div>
{/if}
