<script>
  import { Handle, Position } from '@xyflow/svelte';
  
  export let data;
  export let selected = false;
  
  $: agentName = data.name || 'Unnamed Agent';
  $: agentId = data.agent_id || 'unknown';
  $: model = data.config?.model || 'Not configured';
  $: hasTools = data.tools && data.tools.length > 0;
</script>

<div class="agent-node" class:selected>
  <Handle type="target" position={Position.Top} />
  
  <div class="node-header">
    <div class="node-icon">🤖</div>
    <div class="node-title">
      <div class="agent-name">{agentName}</div>
      <div class="agent-id">{agentId}</div>
    </div>
  </div>
  
  <div class="node-body">
    <div class="info-row">
      <span class="label">Model:</span>
      <span class="value">{model}</span>
    </div>
    {#if hasTools}
      <div class="info-row">
        <span class="label">Tools:</span>
        <span class="value">{data.tools.length} tool(s)</span>
      </div>
    {/if}
    {#if data.system_prompt}
      <div class="prompt-preview">
        {data.system_prompt.substring(0, 50)}...
      </div>
    {/if}
  </div>
  
  <Handle type="source" position={Position.Bottom} />
</div>

<style>
  .agent-node {
    background: white;
    border: 2px solid #ddd;
    border-radius: 8px;
    padding: 12px;
    min-width: 250px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    transition: all 0.2s;
  }
  
  .agent-node.selected {
    border-color: #4f46e5;
    box-shadow: 0 4px 12px rgba(79, 70, 229, 0.3);
  }
  
  .agent-node:hover {
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  }
  
  .node-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
    padding-bottom: 10px;
    border-bottom: 1px solid #e5e7eb;
  }
  
  .node-icon {
    font-size: 32px;
  }
  
  .node-title {
    flex: 1;
  }
  
  .agent-name {
    font-weight: 600;
    font-size: 14px;
    color: #111827;
  }
  
  .agent-id {
    font-size: 11px;
    color: #6b7280;
    font-family: monospace;
  }
  
  .node-body {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  
  .info-row {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
  }
  
  .label {
    color: #6b7280;
    font-weight: 500;
  }
  
  .value {
    color: #111827;
    font-family: monospace;
    font-size: 11px;
  }
  
  .prompt-preview {
    margin-top: 6px;
    padding: 6px;
    background: #f9fafb;
    border-radius: 4px;
    font-size: 10px;
    color: #6b7280;
    font-style: italic;
    line-height: 1.4;
  }
</style>
