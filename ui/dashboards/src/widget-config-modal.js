// widget-config-modal.ts - Tabbed configuration modal for widgets
import { el, on, stop } from "./utils.js";
/**
 * Widget configuration modal with tabbed interface.
 */
export class WidgetConfigModal {
    widget;
    tabs;
    modal = null;
    disposers = [];
    activeTabId = "";
    tabContents = new Map();
    constructor(widget, tabs) {
        this.widget = widget;
        this.tabs = tabs;
    }
    show() {
        if (this.modal)
            return;
        if (this.tabs.length === 0)
            return;
        this.activeTabId = this.tabs[0].id;
        // Overlay
        const overlay = el("div", { class: "widget-config-overlay" });
        Object.assign(overlay.style, {
            position: "fixed",
            inset: "0",
            background: "rgba(0, 0, 0, 0.6)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: "100000",
        });
        // Modal
        const modal = el("div", { class: "widget-config-modal" });
        Object.assign(modal.style, {
            background: "var(--modal-bg, #fff)",
            borderRadius: "12px",
            width: "500px",
            maxWidth: "90vw",
            maxHeight: "80vh",
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            boxShadow: "0 20px 60px rgba(0, 0, 0, 0.3)",
        });
        // Header
        const header = el("div", { class: "widget-config-header" });
        Object.assign(header.style, {
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "16px 20px",
            borderBottom: "1px solid var(--border, #ddd)",
            background: "var(--modal-header-bg, #f8f9fa)",
        });
        const title = el("h2", {}, `⚙️ ${this.widget.getTitle()} Settings`);
        Object.assign(title.style, {
            margin: "0",
            fontSize: "16px",
            fontWeight: "600",
            color: "var(--text, #333)",
        });
        const closeBtn = el("button", { class: "widget-config-close", type: "button" }, "×");
        Object.assign(closeBtn.style, {
            background: "transparent",
            border: "none",
            fontSize: "24px",
            color: "var(--text-muted, #666)",
            cursor: "pointer",
            padding: "0 8px",
        });
        header.append(title, closeBtn);
        // Tab bar
        const tabBar = el("div", { class: "widget-config-tabs" });
        Object.assign(tabBar.style, {
            display: "flex",
            gap: "0",
            padding: "0 16px",
            borderBottom: "1px solid var(--border, #ddd)",
            background: "var(--modal-header-bg, #f8f9fa)",
        });
        for (const tab of this.tabs) {
            const tabBtn = el("button", {
                class: `widget-config-tab ${tab.id === this.activeTabId ? "active" : ""}`,
                type: "button",
                "data-tab-id": tab.id
            }, `${tab.icon ?? ""} ${tab.label}`);
            Object.assign(tabBtn.style, {
                padding: "12px 16px",
                background: "transparent",
                border: "none",
                borderBottom: tab.id === this.activeTabId ? "2px solid var(--accent, #3b82f6)" : "2px solid transparent",
                color: tab.id === this.activeTabId ? "var(--accent, #3b82f6)" : "var(--text-muted, #666)",
                cursor: "pointer",
                fontSize: "13px",
                fontWeight: tab.id === this.activeTabId ? "600" : "400",
            });
            this.disposers.push(on(tabBtn, "click", () => this.switchTab(tab.id, tabBar, contentArea)));
            tabBar.appendChild(tabBtn);
        }
        // Content area
        const contentArea = el("div", { class: "widget-config-content" });
        Object.assign(contentArea.style, {
            flex: "1",
            padding: "20px",
            overflow: "auto",
        });
        // Create content for each tab
        for (const tab of this.tabs) {
            const tabContent = el("div", { class: "widget-config-tab-content", "data-tab-id": tab.id });
            tabContent.style.display = tab.id === this.activeTabId ? "block" : "none";
            tab.render(tabContent, this.widget);
            this.tabContents.set(tab.id, tabContent);
            contentArea.appendChild(tabContent);
        }
        // Footer with buttons
        const footer = el("div", { class: "widget-config-footer" });
        Object.assign(footer.style, {
            display: "flex",
            justifyContent: "flex-end",
            gap: "12px",
            padding: "16px 20px",
            borderTop: "1px solid var(--border, #ddd)",
            background: "var(--modal-footer-bg, #f8f9fa)",
        });
        const cancelBtn = el("button", { class: "widget-config-btn", type: "button" }, "Cancel");
        Object.assign(cancelBtn.style, {
            padding: "10px 20px",
            borderRadius: "6px",
            border: "1px solid var(--border, #ddd)",
            background: "transparent",
            color: "var(--text, #333)",
            cursor: "pointer",
            fontSize: "13px",
        });
        const saveBtn = el("button", { class: "widget-config-btn-primary", type: "button" }, "Save");
        Object.assign(saveBtn.style, {
            padding: "10px 20px",
            borderRadius: "6px",
            border: "none",
            background: "var(--accent, #3b82f6)",
            color: "#fff",
            cursor: "pointer",
            fontSize: "13px",
            fontWeight: "600",
        });
        footer.append(cancelBtn, saveBtn);
        modal.append(header, tabBar, contentArea, footer);
        overlay.appendChild(modal);
        // Event handlers
        this.disposers.push(on(closeBtn, "click", () => this.hide()), on(cancelBtn, "click", () => this.hide()), on(saveBtn, "click", () => this.save()), on(overlay, "click", (ev) => {
            if (ev.target === overlay)
                this.hide();
        }), on(window, "keydown", (ev) => {
            if (ev.key === "Escape")
                this.hide();
        }));
        document.body.appendChild(overlay);
        this.modal = overlay;
    }
    switchTab(tabId, tabBar, contentArea) {
        this.activeTabId = tabId;
        // Update tab buttons
        tabBar.querySelectorAll(".widget-config-tab").forEach(btn => {
            const btnEl = btn;
            const isActive = btnEl.dataset.tabId === tabId;
            btnEl.style.borderBottomColor = isActive ? "var(--accent, #3b82f6)" : "transparent";
            btnEl.style.color = isActive ? "var(--accent, #3b82f6)" : "var(--text-muted, #666)";
            btnEl.style.fontWeight = isActive ? "600" : "400";
        });
        // Show/hide content
        this.tabContents.forEach((content, id) => {
            content.style.display = id === tabId ? "block" : "none";
        });
    }
    save() {
        const config = {};
        for (const tab of this.tabs) {
            const tabConfig = tab.save();
            Object.assign(config, tabConfig);
        }
        // Call widget's onConfigSave hook
        this.widget.onConfigSave(config);
        this.hide();
    }
    hide() {
        if (!this.modal)
            return;
        for (const d of this.disposers)
            d();
        this.disposers = [];
        this.tabContents.clear();
        this.modal.remove();
        this.modal = null;
    }
}
/**
 * Create the default "General" tab for all widgets.
 */
export function createGeneralTab(widget) {
    let titleInput;
    let iconInput;
    let closableCheckbox;
    return {
        id: "general",
        label: "General",
        icon: "⚙️",
        render(container) {
            container.innerHTML = "";
            // Title field
            const titleGroup = el("div", { class: "config-field" });
            Object.assign(titleGroup.style, { marginBottom: "16px" });
            const titleLabel = el("label", {}, "Title");
            Object.assign(titleLabel.style, {
                display: "block",
                marginBottom: "6px",
                fontSize: "13px",
                fontWeight: "500",
                color: "var(--text, #333)",
            });
            titleInput = el("input", {
                type: "text",
                value: widget.getTitle(),
                placeholder: "Widget title",
            });
            Object.assign(titleInput.style, {
                width: "100%",
                padding: "10px 12px",
                borderRadius: "6px",
                border: "1px solid var(--border, #ddd)",
                fontSize: "14px",
                boxSizing: "border-box",
            });
            titleGroup.append(titleLabel, titleInput);
            // Icon field
            const iconGroup = el("div", { class: "config-field" });
            Object.assign(iconGroup.style, { marginBottom: "16px" });
            const iconLabel = el("label", {}, "Icon (emoji)");
            Object.assign(iconLabel.style, {
                display: "block",
                marginBottom: "6px",
                fontSize: "13px",
                fontWeight: "500",
                color: "var(--text, #333)",
            });
            iconInput = el("input", {
                type: "text",
                value: widget.getIcon(),
                placeholder: "📦",
            });
            Object.assign(iconInput.style, {
                width: "80px",
                padding: "10px 12px",
                borderRadius: "6px",
                border: "1px solid var(--border, #ddd)",
                fontSize: "18px",
                textAlign: "center",
            });
            iconGroup.append(iconLabel, iconInput);
            // Closable checkbox
            const closableGroup = el("div", { class: "config-field" });
            Object.assign(closableGroup.style, {
                marginBottom: "16px",
                display: "flex",
                alignItems: "center",
                gap: "8px",
            });
            closableCheckbox = el("input", {
                type: "checkbox",
                checked: widget.opts.closable !== false ? "checked" : "",
                id: "config-closable",
            });
            const closableLabel = el("label", { for: "config-closable" }, "Allow closing this widget");
            Object.assign(closableLabel.style, {
                fontSize: "13px",
                color: "var(--text, #333)",
            });
            closableGroup.append(closableCheckbox, closableLabel);
            container.append(titleGroup, iconGroup, closableGroup);
        },
        save() {
            return {
                title: titleInput?.value ?? widget.getTitle(),
                icon: iconInput?.value ?? widget.getIcon(),
                closable: closableCheckbox?.checked ?? true,
            };
        }
    };
}
/**
 * Open the configuration modal for a widget.
 */
export function openWidgetConfig(widget, additionalTabs = []) {
    const tabs = [
        createGeneralTab(widget),
        ...additionalTabs
    ];
    const modal = new WidgetConfigModal(widget, tabs);
    modal.show();
    return modal;
}
//# sourceMappingURL=widget-config-modal.js.map