import { MarkerType } from '@xyflow/svelte';
import { derived, get, writable } from 'svelte/store';

const EDGE_MARKER = {
    type: MarkerType.ArrowClosed,
    width: 20,
    height: 20
};

const createInitialState = () => ({
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
    const nodesStore = writable<any[]>(initialState.nodes);
    const edgesStore = writable<any[]>(initialState.edges);
    const nextNodeIdStore = writable(initialState.nextNodeId);

    const combined = derived(
        [metadataStore, nodesStore, edgesStore, nextNodeIdStore],
        ([$metadata, $nodes, $edges, $nextNodeId]) => ({
            metadata: $metadata,
            nodes: $nodes,
            edges: $edges,
            nextNodeId: $nextNodeId
        })
    );

    function makeAgentNode(id: number, existingNodes: any[]) {
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
        updateAgent: (nodeId: string, updatedData: any) => {
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
        addEdge: (connection: any) => {
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

            edgesStore.update((current) => [...current, newEdge]);
        },
        updateMetadata: (metadata: any) => {
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
        importCrew: (crew: any) => {
            const agents = Array.isArray(crew.agents) ? crew.agents : [];

            const importedNodes = agents.map((agent: any, index: number) => {
                const nodeId = agent.agent_id || `agent-${index + 1}`;
                const rawConfig =
                    agent.config && typeof agent.config === 'object' ? agent.config : {};
                const model = typeof rawConfig.model === 'string' ? rawConfig.model : 'gemini-2.5-pro';
                const temperature = typeof rawConfig.temperature === 'number' ? rawConfig.temperature : 0.7;
                const normalizedConfig = {
                    ...rawConfig,
                    model,
                    temperature
                };
                return {
                    id: nodeId,
                    type: 'agentNode',
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
                };
            });

            const agentIdToNodeId = new Map();
            importedNodes.forEach((node) => {
                agentIdToNodeId.set(node.data.agent_id, node.id);
                agentIdToNodeId.set(node.id, node.id);
            });

            const edges: any[] = [];
            const edgeIds = new Set();
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

            const normalize = (value: any) => {
                if (Array.isArray(value)) {
                    return value.filter((entry) => typeof entry === 'string' && entry.length > 0);
                }
                return typeof value === 'string' && value.length > 0 ? [value] : [];
            };

            const flowRelations = Array.isArray(crew.flow_relations) ? crew.flow_relations : [];

            if (flowRelations.length > 0) {
                flowRelations.forEach((relation: any) => {
                    const sources = normalize(relation.source)
                        .map((agentId: string) => agentIdToNodeId.get(agentId))
                        .filter((value: any) => Boolean(value));
                    const targets = normalize(relation.target)
                        .map((agentId: string) => agentIdToNodeId.get(agentId))
                        .filter((value: any) => Boolean(value));

                    sources.forEach((sourceId: string) => {
                        targets.forEach((targetId: string) => {
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
                    .filter((value) => value !== null);
                const maxNumericId = numericIds.length > 0 ? Math.max(...numericIds as number[]) : 0;
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

function buildExecutionOrder(nodes: any[], edges: any[]) {
    if (nodes.length === 0) {
        return [];
    }

    const graph = new Map();
    const inDegree = new Map();

    for (const node of nodes) {
        graph.set(node.id, []);
        inDegree.set(node.id, 0);
    }

    for (const edge of edges) {
        graph.get(edge.source)?.push(edge.target);
        inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1);
    }

    const queue = [];
    for (const node of nodes) {
        if ((inDegree.get(node.id) ?? 0) === 0) {
            queue.push(node);
        }
    }

    const sorted = [];
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
