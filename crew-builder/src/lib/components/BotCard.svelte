<script lang="ts">
  import { goto } from '$app/navigation';
  import type { BotSummary } from '$lib/api/bots';

  export let bot: BotSummary;

  function handleClick() {
    goto(`/agents/${bot.chatbot_id}`);
  }
</script>

<button
  class="card group cursor-pointer border border-base-200 bg-base-100/80 text-left transition hover:-translate-y-1 hover:border-primary/50 hover:shadow-xl"
  type="button"
  on:click={handleClick}
>
  <div class="card-body gap-4">
    <div class="flex items-center gap-3">
      <div class="rounded-2xl bg-primary/10 p-3 text-primary">🤖</div>
      <div>
        <h3 class="text-xl font-semibold text-base-content">{bot.name}</h3>
        <p class="text-xs uppercase tracking-wide text-base-content/50">{bot.category}</p>
      </div>
    </div>
    <p class="text-sm text-base-content/70">
      {bot.description}
    </p>
    <div class="flex items-center justify-between text-xs text-base-content/60">
      <span>Owner: {bot.owner}</span>
      <span class="font-semibold text-primary group-hover:text-secondary">Start chat →</span>
    </div>
  </div>
</button>
