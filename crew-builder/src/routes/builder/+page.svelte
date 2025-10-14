<script lang="ts">
  import { Background, Controls, MiniMap, SvelteFlow } from '@xyflow/svelte';
  import type { Connection, Edge, Node, NodeTypes } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';

  import AgentNode from '$lib/components/AgentNode.svelte';
  import ConfigPanel from '$lib/components/ConfigPanel.svelte';
  import Toolbar from '$lib/components/Toolbar.svelte';
  import { crewStore } from '$lib/stores/crewStore';
  import type { AgentNodeData } from '$lib/stores/crewStore';
  import type { Writable } from 'svelte/store';

  type AgentFlowNode = Node<AgentNodeData>;
  type AgentFlowEdge = Edge;

  const nodeTypes: NodeTypes = {
    agentNode: AgentNode as unknown as NodeTypes[string]
  };

  // SvelteFlow expects stores, not plain values!
  const nodesStore = crewStore.nodes as Writable<AgentFlowNode[]>;
  const edgesStore = crewStore.edges as Writable<AgentFlowEdge[]>;

  let selectedNodeId = $state<string | null>(null);
  let showConfigPanel = $state(false);

  // Derived values for UI (not for SvelteFlow)
  let nodes = $state<AgentFlowNode[]>([]);
  let selectedNode = $derived.by(() => nodes.find((n) => n.id === selectedNodeId));

  // Subscribe to nodes for local state
  $effect(() => {
    const unsubscribe = nodesStore.subscribe((value) => {
      nodes = value;
      console.log('Nodes updated:', value.length);
    });
    return unsubscribe;
  });

  function handleNodeClick(event: CustomEvent<{ node: Node }>) {
    console.log('Node clicked:', event.detail.node);
    selectedNodeId = event.detail.node.id;
    showConfigPanel = true;
  }

  function handleConnect(event: CustomEvent<Connection>) {
    console.log('Connecting:', event.detail);
    crewStore.addEdge(event.detail);
  }

  function handleAddAgent() {
    console.log('Adding agent...');
    crewStore.addAgent();
  }

  function closeConfigPanel() {
    selectedNodeId = null;
    showConfigPanel = false;
  }

  function handleUpdateAgent(data: Partial<AgentNodeData>) {
    if (!selectedNodeId) return;
    console.log('Updating agent:', selectedNodeId, data);
    crewStore.updateAgent(selectedNodeId, data);
  }

  function handleDeleteAgent() {
    if (!selectedNodeId) return;
    console.log('Deleting agent:', selectedNodeId);
    crewStore.deleteAgent(selectedNodeId);
    closeConfigPanel();
  }

  function handleExport() {
    const crewJSON = crewStore.exportToJSON();
    console.log('Exporting crew:', crewJSON);
    const blob = new Blob([JSON.stringify(crewJSON, null, 2)], {
      type: 'application/json'
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${crewJSON.name || 'crew'}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }
</script>

<svelte:head>
  <title>Crew Builder</title>
</svelte:head>

<div class="flex h-screen flex-col">
  <Toolbar onAddAgent={handleAddAgent} onExport={handleExport} />
  <div class="relative flex-1">
    <SvelteFlow
      nodes={nodesStore}
      edges={edgesStore}
      {nodeTypes}
      fitView
      on:nodeclick={handleNodeClick}
      on:connect={handleConnect}
    >
      <Controls />
      <Background />
      <MiniMap />
    </SvelteFlow>
  </div>

  {#if showConfigPanel && selectedNode}
    <ConfigPanel
      agent={selectedNode.data}
      onClose={closeConfigPanel}
      onUpdate={handleUpdateAgent}
      onDelete={handleDeleteAgent}
    />
  {/if}
</div>

<style>
  :global(.svelte-flow) {
    background-color: #f8f9fa;
  }

  :global(.svelte-flow__minimap) {
    background-color: #fff;
  }
</style>
