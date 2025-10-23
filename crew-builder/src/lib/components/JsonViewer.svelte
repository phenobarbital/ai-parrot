<script lang="ts">
  import JsonTreeNode from './JsonTreeNode.svelte';

  export let data: unknown;
  export let title = 'Advanced results';
</script>

<div class="space-y-3">
  <div class="collapse collapse-arrow rounded-lg border border-base-300 bg-base-200">
    <input type="checkbox" />
    <div class="collapse-title text-sm font-semibold uppercase tracking-wide text-base-content/70">
      {title}
    </div>
    <div class="collapse-content">
      {#if data !== undefined}
        <div class="overflow-x-auto">
          <JsonTreeNode value={data} label="root" />
        </div>
      {:else}
        <p class="text-sm text-base-content/60">No data available.</p>
      {/if}
    </div>
  </div>
</div>
