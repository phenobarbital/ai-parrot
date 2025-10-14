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

  const nodesStore = crewStore.nodes as Writable<AgentFlowNode[]>;
  const edgesStore = crewStore.edges as Writable<AgentFlowEdge[]>;

  let nodes: AgentFlowNode[] = [];
  let edges: AgentFlowEdge[] = [];
  let selectedNodeId: string | null = null;
  let showConfigPanel = false;
  let selectedNode: AgentFlowNode | undefined;

  $: nodes = $nodesStore as AgentFlowNode[];
  $: edges = $edgesStore as AgentFlowEdge[];
  $: selectedNode = nodes.find((node) => node.id === selectedNodeId);

  function handleNodeClick(event: CustomEvent<{ node: Node }>) {
    selectedNodeId = event.detail.node.id;
    showConfigPanel = true;
  }

  function handleConnect(event: CustomEvent<Connection>) {
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
