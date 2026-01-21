import type { Widget } from "./widget.js";
/**
 * Configuration tab interface.
 * Each widget type can add its own tabs.
 */
export interface ConfigTab {
    id: string;
    label: string;
    icon?: string;
    /** Render the tab content into the container */
    render(container: HTMLElement, widget: Widget): void;
    /** Called when the tab becomes visible */
    onShow?(): void;
    /** Called when saving - return config values from this tab */
    save(): Record<string, unknown>;
}
/**
 * Widget configuration modal with tabbed interface.
 */
export declare class WidgetConfigModal {
    private widget;
    private tabs;
    private modal;
    private disposers;
    private activeTabId;
    private tabContents;
    private renderedTabs;
    constructor(widget: Widget, tabs: ConfigTab[]);
    show(): void;
    private switchTab;
    private save;
    hide(): void;
}
/**
 * Create the default "General" tab for all widgets.
 */
export declare function createGeneralTab(widget: Widget): ConfigTab;
/**
 * Open the configuration modal for a widget.
 */
export declare function openWidgetConfig(widget: Widget, additionalTabs?: ConfigTab[]): WidgetConfigModal;
//# sourceMappingURL=widget-config-modal.d.ts.map