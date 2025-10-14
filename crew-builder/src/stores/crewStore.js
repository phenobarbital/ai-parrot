import { writable } from 'svelte/store';
import { MarkerType } from '@xyflow/svelte';

function createCrewStore() {
  const initialState = {
    metadata: {
      name: 'research_pipeline',
      description: 'Sequential pipeline for research and writing',
      execution_mode: 'sequential'
    },
    nodes: [],
    edges: [],
    nextNodeId: 1
  };

  const { subscribe, set, update } = writable(initialState);

  return {
    subscribe,
    
    addAgent: () => {
      update(state => {
        const nodeId = `agent-${state.nextNodeId}`;
        const newNode = {
          id: nodeId,
          type: 'agentNode',
          position: { 
            x: 100 + (state.nodes.length * 50), 
            y: 100 + (state.nodes.length * 50) 
          },
          data: {
            agent_id: `agent_${state.nextNodeId}`,
            name: `Agent ${state.nextNodeId}`,
            agent_class: 'Agent',
            config: {
              model: 'gemini-2.5-pro',
              temperature: 0.7
            },
            tools: [],
            system_prompt: 'You are an expert AI agent.'
          }
        };

        return {
          ...state,
          nodes: [...state.nodes, newNode],
          nextNodeId: state.nextNodeId + 1
        };
      });
    },

    updateAgent: (nodeId, updatedData) => {
      update(state => ({
        ...state,
        nodes: state.nodes.map(node => 
          node.id === nodeId 
            ? { ...node, data: { ...node.data, ...updatedData } }
            : node
        )
      }));
    },

    deleteAgent: (nodeId) => {
      update(state => ({
        ...state,
        nodes: state.nodes.filter(node => node.id !== nodeId),
        edges: state.edges.filter(edge => 
          edge.source !== nodeId && edge.target !== nodeId
        )
      }));
    },

    addEdge: (connection) => {
      update(state => {
        const newEdge = {
          id: `${connection.source}-${connection.target}`,
          source: connection.source,
          target: connection.target,
          type: 'smoothstep',
          animated: true,
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 20,
            height: 20
          }
        };

        return {
          ...state,
          edges: [...state.edges, newEdge]
        };
      });
    },

    updateNodes: (changes) => {
      update(state => {
        let newNodes = [...state.nodes];
        
        changes.forEach(change => {
          if (change.type === 'position' && change.position) {
            const index = newNodes.findIndex(n => n.id === change.id);
            if (index !== -1) {
              newNodes[index] = {
                ...newNodes[index],
                position: change.position
              };
            }
          } else if (change.type === 'remove') {
            newNodes = newNodes.filter(n => n.id !== change.id);
          }
        });

        return { ...state, nodes: newNodes };
      });
    },

    updateEdges: (changes) => {
      update(state => {
        let newEdges = [...state.edges];
        
        changes.forEach(change => {
          if (change.type === 'remove') {
            newEdges = newEdges.filter(e => e.id !== change.id);
          }
        });

        return { ...state, edges: newEdges };
      });
    },

    updateMetadata: (metadata) => {
      update(state => ({
        ...state,
        metadata: { ...state.metadata, ...metadata }
      }));
    },

    exportToJSON: () => {
      let currentState;
      subscribe(state => currentState = state)();

      // Build execution order based on edges (for sequential execution)
      const executionOrder = buildExecutionOrder(
        currentState.nodes,
        currentState.edges
      );

      // Convert nodes to agent configurations
      const agents = executionOrder.map(node => ({
        agent_id: node.data.agent_id,
        name: node.data.name,
        agent_class: node.data.agent_class,
        config: node.data.config,
        ...(node.data.tools && node.data.tools.length > 0 && { tools: node.data.tools }),
        system_prompt: node.data.system_prompt
      }));

      return {
        name: currentState.metadata.name,
        description: currentState.metadata.description,
        execution_mode: currentState.metadata.execution_mode,
        agents: agents
      };
    },

    reset: () => {
      set(initialState);
    }
  };
}

/**
 * Build execution order for sequential execution based on connections
 * Uses topological sort to determine order
 */
function buildExecutionOrder(nodes, edges) {
  if (nodes.length === 0) return [];

  // Build adjacency list
  const graph = new Map();
  const inDegree = new Map();

  nodes.forEach(node => {
    graph.set(node.id, []);
    inDegree.set(node.id, 0);
  });

  edges.forEach(edge => {
    graph.get(edge.source).push(edge.target);
    inDegree.set(edge.target, inDegree.get(edge.target) + 1);
  });

  // Find nodes with no incoming edges (starting points)
  const queue = [];
  nodes.forEach(node => {
    if (inDegree.get(node.id) === 0) {
      queue.push(node);
    }
  });

  // Topological sort
  const sorted = [];
  const nodeMap = new Map(nodes.map(n => [n.id, n]));

  while (queue.length > 0) {
    const current = queue.shift();
    sorted.push(current);

    const neighbors = graph.get(current.id);
    neighbors.forEach(neighborId => {
      inDegree.set(neighborId, inDegree.get(neighborId) - 1);
      if (inDegree.get(neighborId) === 0) {
        queue.push(nodeMap.get(neighborId));
      }
    });
  }

  // If there are disconnected nodes, add them at the end
  nodes.forEach(node => {
    if (!sorted.find(n => n.id === node.id)) {
      sorted.push(node);
    }
  });

  return sorted;
}

export const crewStore = createCrewStore();
