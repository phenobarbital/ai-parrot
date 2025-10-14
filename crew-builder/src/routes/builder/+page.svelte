<script lang="ts">
  import { Background, Controls, MiniMap, SvelteFlow } from '@xyflow/svelte';
  import type { Edge as FlowEdge, Node as FlowNode } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';

  import AgentNode from '$lib/components/AgentNode.svelte';
  import ConfigPanel from '$lib/components/ConfigPanel.svelte';
  import Toolbar from '$lib/components/Toolbar.svelte';
  import { crewStore } from '$lib/stores/crewStore';

  const nodeTypes = {
    agentNode: AgentNode
  } as const;

  const nodesStore = crewStore.nodes;
  const edgesStore = crewStore.edges;

  let nodes: FlowNode[] = [];
  let edges: FlowEdge[] = [];
  let selectedNodeId: string | null = null;
  let showConfigPanel = false;

  $: nodes = $nodesStore as FlowNode[];
  $: edges = $edgesStore as FlowEdge[];

  $: selectedNode = nodes.find((node) => node.id === selectedNodeId);

  function handleNodeClick(event: CustomEvent) {
    selectedNodeId = event.detail.node.id;
    showConfigPanel = true;
  }

  function handleConnect(event: CustomEvent) {
    crewStore.addEdge(event.detail);
  }

  function handleAddAgent() {
    crewStore.addAgent();
  }

  function closeConfigPanel() {
    selectedNodeId = null;
    showConfigPanel = false;
  }

  function handleUpdateAgent(event: CustomEvent) {
    if (!selectedNodeId) return;
    crewStore.updateAgent(selectedNodeId, event.detail);
  }

  function handleDeleteAgent() {
    if (!selectedNodeId) return;
    crewStore.deleteAgent(selectedNodeId);
    closeConfigPanel();
  }

  function handleExport() {
    const crewJSON = crewStore.exportToJSON();
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

<main class="flex min-h-screen flex-col">
  <Toolbar on:addAgent={handleAddAgent} on:export={handleExport} />
  <section class="relative flex-1">
    <SvelteFlow
      {nodeTypes}
      nodes={nodesStore}
      edges={edgesStore}
      class="h-full w-full"
      fitView
      on:nodeclick={handleNodeClick}
      on:connect={handleConnect}
    >
      <Controls />
      <Background />
      <MiniMap />
    </SvelteFlow>
  </section>

  {#if showConfigPanel && selectedNode}
    <ConfigPanel
      agent={selectedNode.data}
      on:close={closeConfigPanel}
      on:update={handleUpdateAgent}
      on:delete={handleDeleteAgent}
    />
  {/if}
</main>
