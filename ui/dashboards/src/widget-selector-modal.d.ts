export interface WidgetType {
    label: string;
    type: string;
    icon?: string;
    description?: string;
}
export interface WidgetSelection {
    type: string;
    name: string;
}
/**
 * A modal dialog for selecting a widget type and defining its name.
 */
export declare class WidgetSelectorModal {
    private widgetTypes;
    private modal;
    private disposers;
    private resolve;
    private nameInput;
    private selectedType;
    constructor(widgetTypes: WidgetType[]);
    static select(widgetTypes: WidgetType[]): Promise<WidgetSelection | null>;
    show(): Promise<WidgetSelection | null>;
    private render;
    private confirm;
    private cancel;
    private cleanup;
}
//# sourceMappingURL=widget-selector-modal.d.ts.map