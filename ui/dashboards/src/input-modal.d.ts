export interface InputModalOptions {
    title: string;
    message?: string;
    defaultValue?: string;
    placeholder?: string;
    confirmLabel?: string;
    cancelLabel?: string;
}
/**
 * A non-blocking modal dialog to replace window.prompt()
 */
export declare class InputModal {
    private options;
    private modal;
    private disposers;
    private resolve;
    private input;
    constructor(options: InputModalOptions);
    static prompt(options: InputModalOptions): Promise<string | null>;
    show(): Promise<string | null>;
    private render;
    private confirm;
    private cancel;
    private cleanup;
}
//# sourceMappingURL=input-modal.d.ts.map