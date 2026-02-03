import ELK from 'elkjs/lib/elk.bundled.js';

const elk = new ELK();

// Layout options matching Svelte Flow examples but tailored for horizontal flow
export async function getLayoutedElements(nodes: any[], edges: any[], direction = 'RIGHT') {
    const isHorizontal = direction === 'RIGHT' || direction === 'LEFT';

    const graph = {
        id: 'root',
        layoutOptions: {
            'elk.algorithm': 'layered',
            'elk.direction': direction,
            'elk.spacing.nodeNode': '120',
            'elk.layered.spacing.nodeNodeBetweenLayers': '150'
        },
        children: nodes.map((node) => ({
            id: node.id,
            width: 256, // Match w-64
            height: 140 // Approximately height of compact card
        })),
        edges: edges.map((edge) => ({
            id: edge.id,
            sources: [edge.source],
            targets: [edge.target]
        }))
    };

    const layoutedGraph = await elk.layout(graph);

    return {
        nodes: nodes.map((node) => {
            // @ts-ignore
            const layoutedNode = layoutedGraph.children.find((n) => n.id === node.id);
            return {
                ...node,
                position: { x: layoutedNode?.x ?? node.position.x, y: layoutedNode?.y ?? node.position.y }
            };
        }),
        edges
    };
}
