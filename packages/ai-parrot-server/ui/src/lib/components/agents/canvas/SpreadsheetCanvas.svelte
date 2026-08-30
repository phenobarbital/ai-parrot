<script lang="ts">
  import ResultGrid from '$lib/components/grid/ResultGrid.svelte';

  interface Props {
    data: unknown;
    agentId?: string;
    previewMode?: boolean;
  }

  let { data, agentId }: Props = $props();

  let rows = $derived(Array.isArray(data) ? (data as Record<string, unknown>[]) : []);
  let persistKey = $derived(agentId ? `agentchat:${agentId}` : 'agentchat:default');
</script>

<ResultGrid data={rows} {persistKey} />
