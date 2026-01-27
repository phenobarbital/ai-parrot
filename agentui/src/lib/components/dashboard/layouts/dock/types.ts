export type DockNodeType = 'row' | 'col' | 'pane';

export interface DockNode {
    id: string;
    type: DockNodeType;
    children: string[]; // IDs of children (if row/col)
    paneId?: string; // ID of pane (if type='pane')
    size?: number; // Flex basis %
}

export interface DockPane {
    id: string;
    widgets: string[]; // Widget IDs
    activeWidgetId: string | null;
}

export interface DockState {
    rootId: string;
    nodes: Record<string, DockNode>;
    panes: Record<string, DockPane>;
}
