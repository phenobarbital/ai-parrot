<script>
  import { writable } from 'svelte/store';
  import { SvelteFlow, Controls, Background, MiniMap } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';
  
  import AgentNode from './components/AgentNode.svelte';
  import ConfigPanel from './components/ConfigPanel.svelte';
  import Toolbar from './components/Toolbar.svelte';
  import { crewStore } from './stores/crewStore';
  
  // Node types mapping
  const nodeTypes = {
    agentNode: AgentNode
  };
  
  // Flow state
  let nodes = writable([]);
  let edges = writable([]);
  
  let selectedNode = null;
  let showConfigPanel = false;
  
  // Subscribe to crew store changes
  crewStore.subscribe(value => {
    nodes.set(value.nodes);
    edges.set(value.edges);
  });
  
  function onNodeClick(event) {
    selectedNode = event.detail.node;
    showConfigPanel = true;
  }
  
  function onConnect(connection) {
    crewStore.addEdge(connection.detail);
  }
  
  function onNodesChange(changes) {
    crewStore.updateNodes(changes.detail);
  }
  
  function onEdgesChange(changes) {
    crewStore.updateEdges(changes.detail);
  }
  
  function addAgent() {
    crewStore.addAgent();
  }
  
  function closeConfigPanel() {
    showConfigPanel = false;
    selectedNode = null;
  }
  
  function updateAgent(updatedData) {
    if (selectedNode) {
      crewStore.updateAgent(selectedNode.id, updatedData);
    }
  }
  
  function deleteAgent() {
    if (selectedNode) {
      crewStore.deleteAgent(selectedNode.id);
      closeConfigPanel();
    }
  }
  
  function exportCrew() {
    const crewJSON = crewStore.exportToJSON();
    console.log('Exported Crew:', crewJSON);
    
    // Download as JSON file
    const blob = new Blob([JSON.stringify(crewJSON, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${crewJSON.name || 'crew'}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }
</script>

<main>
  <Toolbar 
    on:addAgent={addAgent}
    on:export={exportCrew}
  />
  
  <div class="flow-container">
    <SvelteFlow
      {nodes}
      {edges}
      {nodeTypes}
      on:nodeclick={onNodeClick}
      on:connect={onConnect}
      on:nodeschange={onNodesChange}
      on:edgeschange={onEdgesChange}
      fitView
    >
      <Controls />
      <Background />
      <MiniMap />
    </SvelteFlow>
  </div>
  
  {#if showConfigPanel && selectedNode}
    <ConfigPanel
      agent={selectedNode.data}
      on:close={closeConfigPanel}
      on:update={(e) => updateAgent(e.detail)}
      on:delete={deleteAgent}
    />
  {/if}
</main>

<style>
  main {
    width: 100vw;
    height: 100vh;
    display: flex;
    flex-direction: column;
    background: #f0f0f0;
  }
  
  .flow-container {
    flex: 1;
    position: relative;
  }
</style>
