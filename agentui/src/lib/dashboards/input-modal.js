import { el, on } from "./utils.js";
/**
 * A non-blocking modal dialog to replace window.prompt()
 */
export class InputModal {
    options;
    modal = null;
    disposers = [];
    resolve = null;
    input = null;
    constructor(options) {
        this.options = options;
    }
    static async prompt(options) {
        const modal = new InputModal(options);
        return modal.show();
    }
    show() {
        return new Promise((resolve) => {
            this.resolve = resolve;
            this.render();
        });
    }
    render() {
        // Overlay
        const overlay = el("div", { class: "input-modal-overlay" });
        Object.assign(overlay.style, {
            position: "fixed",
            inset: "0",
            background: "rgba(0, 0, 0, 0.6)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: "100002", // Higher than menus
            opacity: "0",
            transition: "opacity 0.2s ease"
        });
        // Modal
        const modal = el("div", { class: "input-modal" });
        Object.assign(modal.style, {
            background: "var(--surface, #fff)",
            borderRadius: "12px",
            width: "400px",
            maxWidth: "90vw",
            display: "flex",
            flexDirection: "column",
            boxShadow: "0 20px 60px rgba(0, 0, 0, 0.3)",
            color: "var(--text, #333)",
            transform: "scale(0.95)",
            transition: "transform 0.2s ease"
        });
        // Title
        const header = el("div", {});
        Object.assign(header.style, {
            padding: "20px 24px 10px 24px",
        });
        const title = el("h3", {}, this.options.title);
        Object.assign(title.style, {
            margin: "0",
            fontSize: "18px",
            fontWeight: "600"
        });
        header.appendChild(title);
        if (this.options.message) {
            const msg = el("div", {}, this.options.message);
            Object.assign(msg.style, {
                marginTop: "8px",
                fontSize: "14px",
                color: "var(--text-muted, #666)",
                lineHeight: "1.5"
            });
            header.appendChild(msg);
        }
        // Input Area
        const content = el("div", {});
        Object.assign(content.style, {
            padding: "10px 24px"
        });
        this.input = el("input", {
            type: "text",
            value: this.options.defaultValue || "",
            placeholder: this.options.placeholder || ""
        });
        Object.assign(this.input.style, {
            width: "100%",
            padding: "12px",
            borderRadius: "8px",
            border: "1px solid var(--border, #ddd)",
            background: "var(--background, #fff)",
            color: "var(--text, #333)",
            fontSize: "16px",
            outline: "none",
            boxSizing: "border-box"
        });
        // Focus highlight
        this.disposers.push(on(this.input, "focus", () => {
            if (this.input)
                this.input.style.borderColor = "var(--primary, #3b82f6)";
        }), on(this.input, "blur", () => {
            if (this.input)
                this.input.style.borderColor = "var(--border, #ddd)";
        }), on(this.input, "keydown", (e) => {
            if (e.key === "Enter")
                this.confirm();
            if (e.key === "Escape")
                this.cancel();
        }));
        content.appendChild(this.input);
        // Footer / Buttons
        const footer = el("div", {});
        Object.assign(footer.style, {
            display: "flex",
            justifyContent: "flex-end",
            gap: "12px",
            padding: "20px 24px",
            // background: "var(--surface-muted, #f8f9fa)", // Optional footer bg
            // borderTop: "1px solid var(--border, #eee)",
            // borderRadius: "0 0 12px 12px"
        });
        const cancelBtn = el("button", { type: "button" }, this.options.cancelLabel || "Cancel");
        Object.assign(cancelBtn.style, {
            padding: "10px 16px",
            borderRadius: "6px",
            border: "1px solid transparent", // Ghost button
            background: "transparent",
            color: "var(--text-muted, #666)",
            fontSize: "14px",
            fontWeight: "500",
            cursor: "pointer"
        });
        // Hover effect manually or rely on CSS classes if available
        this.disposers.push(on(cancelBtn, "mouseover", () => cancelBtn.style.background = "rgba(0,0,0,0.05)"), on(cancelBtn, "mouseout", () => cancelBtn.style.background = "transparent"));
        const confirmBtn = el("button", { type: "button" }, this.options.confirmLabel || "OK");
        Object.assign(confirmBtn.style, {
            padding: "10px 20px",
            borderRadius: "6px",
            border: "none",
            background: "var(--primary, #3b82f6)",
            color: "#fff",
            fontSize: "14px",
            fontWeight: "600",
            cursor: "pointer",
            boxShadow: "0 2px 4px rgba(59, 130, 246, 0.3)"
        });
        // Hover
        this.disposers.push(on(confirmBtn, "mouseover", () => confirmBtn.style.background = "var(--primary-hover, #2563eb)"), on(confirmBtn, "mouseout", () => confirmBtn.style.background = "var(--primary, #3b82f6)"));
        this.disposers.push(on(cancelBtn, "click", () => this.cancel()), on(confirmBtn, "click", () => this.confirm()));
        footer.append(cancelBtn, confirmBtn);
        modal.append(header, content, footer);
        overlay.appendChild(modal);
        document.body.appendChild(overlay);
        this.modal = overlay;
        // Animate in
        requestAnimationFrame(() => {
            overlay.style.opacity = "1";
            modal.style.transform = "scale(1)";
            this.input?.focus();
            this.input?.select();
        });
        // Close on outside click
        this.disposers.push(on(overlay, "click", (e) => {
            if (e.target === overlay)
                this.cancel();
        }));
    }
    confirm() {
        if (this.resolve && this.input) {
            this.resolve(this.input.value);
        }
        this.cleanup();
    }
    cancel() {
        if (this.resolve) {
            this.resolve(null);
        }
        this.cleanup();
    }
    cleanup() {
        if (this.modal) {
            // Animate out
            this.modal.style.opacity = "0";
            const dialog = this.modal.querySelector(".input-modal");
            if (dialog)
                dialog.style.transform = "scale(0.95)";
            setTimeout(() => {
                this.modal?.remove();
                this.modal = null;
            }, 200);
        }
        this.disposers.forEach(d => d());
        this.disposers = [];
        this.resolve = null;
        this.input = null;
    }
}
//# sourceMappingURL=input-modal.js.map