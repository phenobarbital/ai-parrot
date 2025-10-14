import { MarkerType, type Connection, type Edge, type Node } from '@xyflow/svelte';
import { derived, get, writable, type Readable } from 'svelte/store';

export interface AgentConfig {
  model: string;
  temperature: number;
}

export interface AgentNodeData extends Record<string, unknown> {
  agent_id: string;
  name: string;
  agent_class: string;
  config: AgentConfig;
  tools: string[];
  system_prompt: string;
}

export interface CrewMetadata {
  name: string;
  description: string;
  execution_mode: 'sequential' | 'parallel' | 'hierarchical';
}

export interface CrewState {
  metadata: CrewMetadata;
  nodes: Node<AgentNodeData>[];
  edges: Edge[];
  nextNodeId: number;
}

const createInitialState = (): CrewState => ({
  metadata: {
    name: 'research_pipeline',
    description: 'Sequential pipeline for research and writing',
    execution_mode: 'sequential'
  },
  nodes: [],
  edges: [],
  nextNodeId: 1
});

function createCrewStore() {
  const initialState = createInitialState();

  const metadataStore = writable(initialState.metadata);
  const nodesStore = writable<Node<AgentNodeData>[]>(initialState.nodes);
  const edgesStore = writable<Edge[]>(initialState.edges);
  const nextNodeIdStore = writable(initialState.nextNodeId);

  const combined: Readable<CrewState> = derived(
    [metadataStore, nodesStore, edgesStore, nextNodeIdStore],
    ([$metadata, $nodes, $edges, $nextNodeId]) => ({
      metadata: $metadata,
      nodes: $nodes,
      edges: $edges,
      nextNodeId: $nextNodeId
    })
  );

  function makeAgentNode(id: number, existingNodes: Node<AgentNodeData>[]): Node<AgentNodeData> {
    const nodeId = `agent-${id}`;
    return {
      id: nodeId,
      type: 'agentNode',
      position: {
        x: 100 + existingNodes.length * 50,
        y: 100 + existingNodes.length * 50
      },
      data: {
        agent_id: `agent_${id}`,
        name: `Agent ${id}`,
        agent_class: 'Agent',
        config: {
          model: 'gemini-2.5-pro',
          temperature: 0.7
        },
        tools: [],
        system_prompt: 'You are an expert AI agent.'
      }
    };
  }

  return {
    subscribe: combined.subscribe,
    nodes: nodesStore,
    edges: edgesStore,
    addAgent: () => {
      const nextId = get(nextNodeIdStore);
      nodesStore.update((current) => [...current, makeAgentNode(nextId, current)]);
      nextNodeIdStore.set(nextId + 1);
    },
    updateAgent: (nodeId: string, updatedData: Partial<AgentNodeData>) => {
      nodesStore.update((current) =>
        current.map((node) =>
          node.id === nodeId
            ? {
                ...node,
                data: {
                  ...node.data,
                  ...updatedData,
                  config: {
                    ...node.data.config,
                    ...(updatedData.config ?? {})
                  },
                  tools: updatedData.tools ?? node.data.tools
                }
              }
            : node
        )
      );
    },
    deleteAgent: (nodeId: string) => {
      nodesStore.update((current) => current.filter((node) => node.id !== nodeId));
      edgesStore.update((current) =>
        current.filter((edge) => edge.source !== nodeId && edge.target !== nodeId)
      );
    },
    addEdge: (connection: Connection) => {
      const newEdge: Edge = {
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

      edgesStore.update((current) => [...current, newEdge]);
    },
    updateMetadata: (metadata: Partial<CrewMetadata>) => {
      metadataStore.update((current) => ({ ...current, ...metadata }));
    },
    exportToJSON: () => {
      const currentMetadata = get(metadataStore);
      const currentNodes = get(nodesStore);
      const currentEdges = get(edgesStore);
      const executionOrder = buildExecutionOrder(currentNodes, currentEdges);

      const agents = executionOrder.map((node) => ({
        agent_id: node.data.agent_id,
        name: node.data.name,
        agent_class: node.data.agent_class,
        config: node.data.config,
        ...(node.data.tools && node.data.tools.length > 0 && { tools: node.data.tools }),
        system_prompt: node.data.system_prompt
      }));

      return {
        name: currentMetadata.name,
        description: currentMetadata.description,
        execution_mode: currentMetadata.execution_mode,
        agents
      };
    },
    reset: () => {
      const resetState = createInitialState();
      metadataStore.set(resetState.metadata);
      nodesStore.set(resetState.nodes);
      edgesStore.set(resetState.edges);
      nextNodeIdStore.set(resetState.nextNodeId);
    }
  };
}

function buildExecutionOrder(nodes: Node<AgentNodeData>[], edges: Edge[]) {
  if (nodes.length === 0) {
    return [];
  }

  const graph = new Map<string, string[]>();
  const inDegree = new Map<string, number>();

  for (const node of nodes) {
    graph.set(node.id, []);
    inDegree.set(node.id, 0);
  }

  for (const edge of edges) {
    graph.get(edge.source)?.push(edge.target);
    inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1);
  }

  const queue: Node<AgentNodeData>[] = [];
  for (const node of nodes) {
    if ((inDegree.get(node.id) ?? 0) === 0) {
      queue.push(node);
    }
  }

  const sorted: Node<AgentNodeData>[] = [];
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));

  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) continue;
    sorted.push(current);

    const neighbors = graph.get(current.id) ?? [];
    for (const neighborId of neighbors) {
      const nextDegree = (inDegree.get(neighborId) ?? 0) - 1;
      inDegree.set(neighborId, nextDegree);
      if (nextDegree === 0) {
        const neighbor = nodeMap.get(neighborId);
        if (neighbor) {
          queue.push(neighbor);
        }
      }
    }
  }

  for (const node of nodes) {
    if (!sorted.find((entry) => entry.id === node.id)) {
      sorted.push(node);
    }
  }

  return sorted;
}

export const crewStore = createCrewStore();
