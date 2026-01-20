import type { DockLayout } from "./dock-layout.js";
export declare class DockLayoutPicker {
    private dockLayout;
    private modal;
    private disposers;
    constructor(dockLayout: DockLayout);
    show(): void;
    private createTemplateCard;
    private createLayoutPreview;
    private buildPreviewStructure;
    hide(): void;
    destroy(): void;
}
/** Show the layout picker modal for a DockLayout */
export declare function showLayoutPicker(dockLayout: DockLayout): DockLayoutPicker;
//# sourceMappingURL=dock-layout-picker.d.ts.map