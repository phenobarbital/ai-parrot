// dock-layout-picker.ts - Modal for selecting dock layout templates
import { el, on, stop } from "./utils.js";
export class DockLayoutPicker {
    dockLayout;
    modal = null;
    disposers = [];
    constructor(dockLayout) {
        this.dockLayout = dockLayout;
    }
    show() {
        if (this.modal)
            return;
        const templates = this.dockLayout.getAvailableTemplates();
        const currentTemplate = this.dockLayout.getCurrentTemplate();
        // Create modal overlay
        const overlay = el("div", { class: "dock-picker-overlay" });
        Object.assign(overlay.style, {
            position: "fixed",
            inset: "0",
            background: "rgba(0, 0, 0, 0.7)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: "100000",
        });
        // Modal content
        const modal = el("div", { class: "dock-picker-modal" });
        Object.assign(modal.style, {
            background: "var(--surface, #1a1a2e)",
            borderRadius: "12px",
            padding: "24px",
            minWidth: "480px",
            maxWidth: "90vw",
            maxHeight: "80vh",
            overflow: "auto",
            boxShadow: "0 20px 60px rgba(0, 0, 0, 0.5)",
        });
        // Header
        const header = el("div", { class: "dock-picker-header" });
        Object.assign(header.style, {
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: "20px",
        });
        const title = el("h2", {}, "Choose Layout");
        Object.assign(title.style, {
            margin: "0",
            fontSize: "18px",
            fontWeight: "600",
            color: "var(--text, #fff)",
        });
        const closeBtn = el("button", { class: "dock-picker-close" }, "×");
        Object.assign(closeBtn.style, {
            background: "transparent",
            border: "none",
            color: "var(--text-muted, #888)",
            fontSize: "24px",
            cursor: "pointer",
            padding: "0 8px",
        });
        header.append(title, closeBtn);
        // Template grid
        const grid = el("div", { class: "dock-picker-grid" });
        Object.assign(grid.style, {
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: "16px",
        });
        for (const template of templates) {
            const isActive = currentTemplate?.id === template.id;
            const card = this.createTemplateCard(template, isActive);
            grid.appendChild(card);
        }
        modal.append(header, grid);
        overlay.appendChild(modal);
        // Close handlers
        this.disposers.push(on(closeBtn, "click", () => this.hide()), on(overlay, "click", (ev) => {
            if (ev.target === overlay)
                this.hide();
        }), on(window, "keydown", (ev) => {
            if (ev.key === "Escape")
                this.hide();
        }));
        document.body.appendChild(overlay);
        this.modal = overlay;
    }
    createTemplateCard(template, isActive) {
        const card = el("button", {
            class: `dock-picker-card ${isActive ? "dock-picker-card-active" : ""}`,
            "data-template-id": template.id
        });
        Object.assign(card.style, {
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: "8px",
            padding: "16px",
            background: isActive ? "var(--accent, #3b82f6)" : "var(--surface-dim, #151525)",
            border: `2px solid ${isActive ? "var(--accent, #3b82f6)" : "var(--border, #333)"}`,
            borderRadius: "8px",
            cursor: "pointer",
            transition: "all 150ms ease",
        });
        // Preview
        const preview = this.createLayoutPreview(template);
        // Label
        const label = el("span", {}, template.name);
        Object.assign(label.style, {
            fontSize: "12px",
            color: isActive ? "#fff" : "var(--text-muted, #888)",
            fontWeight: isActive ? "600" : "400",
        });
        card.append(preview, label);
        // Hover effect
        on(card, "mouseenter", () => {
            if (!isActive) {
                card.style.borderColor = "var(--accent, #3b82f6)";
                card.style.background = "var(--surface, #1a1a2e)";
            }
        });
        on(card, "mouseleave", () => {
            if (!isActive) {
                card.style.borderColor = "var(--border, #333)";
                card.style.background = "var(--surface-dim, #151525)";
            }
        });
        // Click to apply
        this.disposers.push(on(card, "click", () => {
            this.dockLayout.applyTemplate(template);
            this.hide();
        }));
        return card;
    }
    createLayoutPreview(template) {
        const preview = el("div", { class: "dock-picker-preview" });
        Object.assign(preview.style, {
            width: "80px",
            height: "60px",
            display: "flex",
            gap: "2px",
            background: "var(--border, #333)",
            borderRadius: "4px",
            padding: "2px",
            overflow: "hidden",
        });
        this.buildPreviewStructure(template.structure, preview);
        return preview;
    }
    buildPreviewStructure(structure, container) {
        if (structure.type === "pane") {
            const pane = el("div");
            Object.assign(pane.style, {
                flex: "1",
                background: "var(--surface, #1a1a2e)",
                borderRadius: "2px",
            });
            container.appendChild(pane);
            return;
        }
        const isRow = structure.type === "row";
        Object.assign(container.style, {
            flexDirection: isRow ? "row" : "column",
        });
        const sizes = structure.sizes ?? structure.children.map(() => 100 / structure.children.length);
        structure.children.forEach((child, i) => {
            const childEl = el("div");
            Object.assign(childEl.style, {
                flex: `0 0 ${sizes[i]}%`,
                display: "flex",
                gap: "2px",
            });
            if (child.type === "pane") {
                Object.assign(childEl.style, {
                    background: "var(--surface, #1a1a2e)",
                    borderRadius: "2px",
                });
            }
            else {
                this.buildPreviewStructure(child, childEl);
            }
            container.appendChild(childEl);
        });
    }
    hide() {
        if (!this.modal)
            return;
        for (const d of this.disposers)
            d();
        this.disposers = [];
        this.modal.remove();
        this.modal = null;
    }
    destroy() {
        this.hide();
    }
}
/** Show the layout picker modal for a DockLayout */
export function showLayoutPicker(dockLayout) {
    const picker = new DockLayoutPicker(dockLayout);
    picker.show();
    return picker;
}
//# sourceMappingURL=dock-layout-picker.js.map