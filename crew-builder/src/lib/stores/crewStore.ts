import { MarkerType, type Connection, type Edge, type Node } from '@xyflow/svelte';
import { derived, get, writable, type Readable } from 'svelte/store';

export type CrewExecutionMode = 'sequential' | 'parallel' | 'hierarchical' | 'flow';

export interface AgentConfig {
  model: string;
  temperature: number;
  [key: string]: unknown;
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
  execution_mode: CrewExecutionMode;
}

export interface CrewState {
  metadata: CrewMetadata;
  nodes: Node<AgentNodeData>[];
  edges: Edge[];
  nextNodeId: number;
}

interface CrewApiAgent {
  agent_id: string;
  agent_class?: string;
  name?: string;
  config?: Partial<AgentConfig> & Record<string, unknown>;
  tools?: string[];
  system_prompt?: string | null;
}

interface CrewApiFlowRelation {
  source?: string | string[];
  target?: string | string[];
}

interface CrewApiResponse {
  crew_id?: string;
  name?: string | null;
  description?: string | null;
  execution_mode?: CrewExecutionMode;
  agents?: CrewApiAgent[];
  flow_relations?: CrewApiFlowRelation[];
}

const EDGE_MARKER = {
  type: MarkerType.ArrowClosed,
  width: 20,
  height: 20
} as const;

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
    },
    importCrew: (crew: CrewApiResponse) => {
      const agents = Array.isArray(crew.agents) ? crew.agents : [];

      const importedNodes = agents.map((agent, index) => {
        const nodeId = agent.agent_id || `agent-${index + 1}`;
        const rawConfig =
          (agent.config && typeof agent.config === 'object' ? agent.config : {}) as Record<string, unknown>;
        const model = typeof rawConfig.model === 'string' ? (rawConfig.model as string) : 'gemini-2.5-pro';
        const temperature =
          typeof rawConfig.temperature === 'number' ? (rawConfig.temperature as number) : 0.7;
        const normalizedConfig: AgentConfig = {
          ...rawConfig,
          model,
          temperature
        };
        return {
          id: nodeId,
          type: 'agentNode' as const,
          position: {
            x: 200 + (index % 3) * 260,
            y: 120 + Math.floor(index / 3) * 220
          },
          data: {
            agent_id: agent.agent_id ?? `agent_${index + 1}`,
            name: agent.name ?? `Agent ${index + 1}`,
            agent_class: agent.agent_class ?? 'Agent',
            config: normalizedConfig,
            tools: Array.isArray(agent.tools) ? agent.tools : [],
            system_prompt: agent.system_prompt ?? ''
          }
        } satisfies Node<AgentNodeData>;
      });

      const agentIdToNodeId = new Map<string, string>();
      importedNodes.forEach((node) => {
        agentIdToNodeId.set(node.data.agent_id, node.id);
        agentIdToNodeId.set(node.id, node.id);
      });

      const edges: Edge[] = [];
      const edgeIds = new Set<string>();
      const pushEdge = (source: string, target: string) => {
        if (!source || !target || source === target) {
          return;
        }
        let baseId = `${source}-${target}`;
        let uniqueId = baseId;
        let attempt = 1;
        while (edgeIds.has(uniqueId)) {
          uniqueId = `${baseId}-${attempt}`;
          attempt += 1;
        }
        edgeIds.add(uniqueId);
        edges.push({
          id: uniqueId,
          source,
          target,
          type: 'smoothstep',
          animated: true,
          markerEnd: { ...EDGE_MARKER }
        });
      };

      const normalize = (value?: string | string[]) => {
        if (Array.isArray(value)) {
          return value.filter((entry): entry is string => typeof entry === 'string' && entry.length > 0);
        }
        return typeof value === 'string' && value.length > 0 ? [value] : [];
      };

      const flowRelations = Array.isArray(crew.flow_relations) ? crew.flow_relations : [];

      if (flowRelations.length > 0) {
        flowRelations.forEach((relation) => {
          const sources = normalize(relation.source).map((agentId) => agentIdToNodeId.get(agentId)).filter((value): value is string => Boolean(value));
          const targets = normalize(relation.target).map((agentId) => agentIdToNodeId.get(agentId)).filter((value): value is string => Boolean(value));

          sources.forEach((sourceId) => {
            targets.forEach((targetId) => {
              pushEdge(sourceId, targetId);
            });
          });
        });
      } else if ((crew.execution_mode ?? 'sequential') === 'sequential' && importedNodes.length > 1) {
        for (let index = 0; index < importedNodes.length - 1; index += 1) {
          const sourceId = importedNodes[index]?.id;
          const targetId = importedNodes[index + 1]?.id;
          if (sourceId && targetId) {
            pushEdge(sourceId, targetId);
          }
        }
      }

      const nextId = (() => {
        const numericIds = importedNodes
          .map((node) => {
            const match = /^agent-(\d+)$/.exec(node.id);
            return match ? Number.parseInt(match[1], 10) : null;
          })
          .filter((value): value is number => value !== null);
        const maxNumericId = numericIds.length > 0 ? Math.max(...numericIds) : 0;
        return Math.max(importedNodes.length + 1, maxNumericId + 1);
      })();

      metadataStore.set({
        name: crew.name ?? 'untitled_crew',
        description: crew.description ?? '',
        execution_mode: crew.execution_mode ?? 'sequential'
      });
      nodesStore.set(importedNodes);
      edgesStore.set(edges);
      nextNodeIdStore.set(nextId);
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
