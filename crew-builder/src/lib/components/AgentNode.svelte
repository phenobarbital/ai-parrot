<script lang="ts">
  import { Handle, Position } from '@xyflow/svelte';
  import type { AgentNodeData } from '$lib/stores/crewStore';

  export let data: AgentNodeData;
  export let selected = false;

  $: agentName = data.name || 'Unnamed Agent';
  $: agentId = data.agent_id || 'unknown';
  $: model = data.config?.model || 'Not configured';
  $: hasTools = data.tools && data.tools.length > 0;
</script>

<div class={`card card-compact w-72 border-2 transition-shadow ${selected ? 'border-primary shadow-lg' : 'border-base-200 shadow'}`}>
  <Handle type="target" position={Position.Top} />
  <div class="card-body gap-4">
    <div class="flex items-center gap-3 border-b border-base-200 pb-3">
      <div class="text-3xl">🤖</div>
      <div>
        <div class="font-semibold text-base-content">{agentName}</div>
        <div class="text-xs font-mono text-base-content/70">{agentId}</div>
      </div>
    </div>
    <div class="space-y-2 text-sm">
      <div class="flex items-center justify-between">
        <span class="font-medium text-base-content/70">Model:</span>
        <span class="font-mono text-xs text-base-content">{model}</span>
      </div>
      {#if hasTools}
        <div class="flex items-center justify-between">
          <span class="font-medium text-base-content/70">Tools:</span>
          <span class="text-xs text-base-content">{data.tools.length} tool(s)</span>
        </div>
      {/if}
      {#if data.system_prompt}
        <div class="rounded-lg bg-base-200 p-2 text-xs italic text-base-content/80">
          {data.system_prompt.substring(0, 50)}...
        </div>
      {/if}
    </div>
  </div>
  <Handle type="source" position={Position.Bottom} />
</div>
