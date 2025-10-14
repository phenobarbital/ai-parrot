import { MarkerType, type Connection, type Edge, type Node } from '@xyflow/svelte';
import { get, writable, type Subscriber, type Unsubscriber, type Writable } from 'svelte/store';

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

const initialState: CrewState = {
  metadata: {
    name: 'research_pipeline',
    description: 'Sequential pipeline for research and writing',
    execution_mode: 'sequential'
  },
  nodes: [],
  edges: [],
  nextNodeId: 1
};

function mapStore<T>(
  subscribeState: (run: Subscriber<CrewState>, invalidate?: (value?: CrewState) => void) => Unsubscriber,
  updateState: (updater: (state: CrewState) => CrewState) => void,
  selector: (state: CrewState) => T,
  assign: (state: CrewState, value: T) => CrewState
): Writable<T> {
  return {
    subscribe(run, invalidate) {
      return subscribeState((state) => run(selector(state)), invalidate);
    },
    set(value) {
      updateState((state) => assign(state, value));
    },
    update(updater) {
      updateState((state) => assign(state, updater(selector(state))));
    }
  };
}

function createCrewStore() {
  const store = writable<CrewState>(initialState);
  const { subscribe, set, update } = store;

  const nodes = mapStore<Node<AgentNodeData>[]>(subscribe, update, (state) => state.nodes, (state, value) => ({
    ...state,
    nodes: value
  }));

  const edges = mapStore<Edge[]>(subscribe, update, (state) => state.edges, (state, value) => ({
    ...state,
    edges: value
  }));

  return {
    subscribe,
    nodes,
    edges,
    addAgent: () => {
      update((state) => {
        const nodeId = `agent-${state.nextNodeId}`;
        const newNode: Node<AgentNodeData> = {
          id: nodeId,
          type: 'agentNode',
          position: {
            x: 100 + state.nodes.length * 50,
            y: 100 + state.nodes.length * 50
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
    updateAgent: (nodeId: string, updatedData: Partial<AgentNodeData>) => {
      update((state) => ({
        ...state,
        nodes: state.nodes.map((node) =>
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
      }));
    },
    deleteAgent: (nodeId: string) => {
      update((state) => ({
        ...state,
        nodes: state.nodes.filter((node) => node.id !== nodeId),
        edges: state.edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId)
      }));
    },
    addEdge: (connection: Connection) => {
      update((state) => {
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

        return {
          ...state,
          edges: [...state.edges, newEdge]
        };
      });
    },
    updateMetadata: (metadata: Partial<CrewMetadata>) => {
      update((state) => ({
        ...state,
        metadata: { ...state.metadata, ...metadata }
      }));
    },
    exportToJSON: () => {
      const currentState = get(store);
      const executionOrder = buildExecutionOrder(currentState.nodes, currentState.edges);

      const agents = executionOrder.map((node) => ({
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
        agents
      };
    },
    reset: () => set(initialState)
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
export type { AgentNodeData };
