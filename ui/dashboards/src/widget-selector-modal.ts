import { el, on, type Dispose } from "./utils.js";

export interface WidgetType {
    label: string;
    type: string;
    icon?: string; // Emoji or generic icon if not provided
    description?: string;
}

export interface WidgetSelection {
    type: string;
    name: string;
}

/**
 * A modal dialog for selecting a widget type and defining its name.
 */
export class WidgetSelectorModal {
    private modal: HTMLElement | null = null;
    private disposers: Dispose[] = [];
    private resolve: ((value: WidgetSelection | null) => void) | null = null;
    private nameInput: HTMLInputElement | null = null;
    private selectedType: string | null = null;

    constructor(private widgetTypes: WidgetType[]) { }

    static async select(widgetTypes: WidgetType[]): Promise<WidgetSelection | null> {
        const modal = new WidgetSelectorModal(widgetTypes);
        return modal.show();
    }

    show(): Promise<WidgetSelection | null> {
        return new Promise((resolve) => {
            this.resolve = resolve;
            this.render();
        });
    }

    private render(): void {
        // Overlay
        const overlay = el("div", { class: "widget-modal-overlay" });
        Object.assign(overlay.style, {
            position: "fixed",
            inset: "0",
            background: "rgba(0, 0, 0, 0.6)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: "100005", // Higher than everything
            opacity: "0",
            transition: "opacity 0.2s ease"
        });

        // Modal Content
        const modal = el("div", { class: "widget-modal" });
        // Styles will be largely in CSS, but base layout here
        Object.assign(modal.style, {
            background: "var(--surface, #fff)",
            width: "800px",
            maxWidth: "95vw",
            height: "600px",
            maxHeight: "90vh",
            display: "flex",
            flexDirection: "column",
            borderRadius: "8px",
            boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.25)",
            overflow: "hidden",
            transform: "scale(0.95)",
            transition: "transform 0.2s ease"
        });

        // Header
        const header = el("div", { class: "widget-modal-header" });
        const title = el("h2", {}, "Add a Runtime Widget");
        const closeBtn = el("button", { class: "widget-modal-close" }, "×");

        on(closeBtn, "click", () => this.cancel());

        header.append(title, closeBtn);

        // Name Input Section
        const inputSection = el("div", { class: "widget-modal-input-section" });
        const inputLabel = el("label", {}, "Widget Name:");
        this.nameInput = el("input", {
            type: "text",
            value: "New Widget",
            class: "widget-modal-name-input",
            placeholder: "Enter widget name..."
        }) as HTMLInputElement;

        on(this.nameInput, "keydown", (e: KeyboardEvent) => {
            if (e.key === "Escape") this.cancel();
            if (e.key === "Enter") this.confirm();
        });

        inputSection.append(inputLabel, this.nameInput);

        // Grid Section
        const gridContainer = el("div", { class: "widget-modal-grid-container" });
        const grid = el("div", { class: "widget-modal-grid" });

        const cards: HTMLElement[] = [];
        const addBtn = el("button", { class: "widget-modal-btn confirm", disabled: "" }, "Add Widget");

        this.widgetTypes.forEach(wt => {
            const card = el("div", { class: "widget-card", "data-type": wt.type });

            const icon = el("div", { class: "widget-card-icon" }, wt.icon || "🧩");
            const label = el("div", { class: "widget-card-label" }, wt.label);
            const desc = el("div", { class: "widget-card-desc" }, wt.description || "Generic widget");

            const info = el("div", { class: "widget-card-info" }, "ℹ");

            card.append(icon, label, desc, info);

            on(card, "click", () => {
                this.selectedType = wt.type;
                cards.forEach(c => c.classList.remove("selected"));
                card.classList.add("selected");
                addBtn.removeAttribute("disabled");
                addBtn.classList.remove("disabled");
            });

            cards.push(card);
            grid.appendChild(card);
        });

        gridContainer.appendChild(grid);

        // Footer
        const footer = el("div", { class: "widget-modal-footer" });
        const cancelBtn = el("button", { class: "widget-modal-btn cancel" }, "Cancel");

        on(cancelBtn, "click", () => this.cancel());
        on(addBtn, "click", () => this.confirm());

        footer.append(cancelBtn, addBtn);

        modal.append(header, inputSection, gridContainer, footer);
        overlay.appendChild(modal);
        document.body.appendChild(overlay);
        this.modal = overlay;

        // Animate
        requestAnimationFrame(() => {
            overlay.style.opacity = "1";
            modal.style.transform = "scale(1)";
            this.nameInput?.focus();
            this.nameInput?.select();
        });

        // Close on outside
        this.disposers.push(
            on(overlay, "click", (e) => {
                if (e.target === overlay) this.cancel();
            })
        );
    }

    private confirm(): void {
        const name = this.nameInput?.value.trim() || "New Widget";
        if (this.resolve && this.selectedType) {
            this.resolve({ type: this.selectedType, name });
            this.cleanup();
        }
    }

    private cancel(): void {
        if (this.resolve) this.resolve(null);
        this.cleanup();
    }

    private cleanup(): void {
        if (this.modal) {
            this.modal.style.opacity = "0";
            const m = this.modal.querySelector(".widget-modal") as HTMLElement;
            if (m) m.style.transform = "scale(0.95)";

            setTimeout(() => {
                this.modal?.remove();
                this.modal = null;
            }, 200);
        }
        this.disposers.forEach(d => d());
        this.disposers = [];
        this.resolve = null;
    }
}
