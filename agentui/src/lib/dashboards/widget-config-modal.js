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
    renderedTabs = new Set();
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
            background: "var(--db-surface)",
            borderRadius: "12px",
            width: "900px",
            height: "700px",
            maxWidth: "95vw",
            maxHeight: "95vh",
            minWidth: "500px",
            minHeight: "400px",
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            boxShadow: "0 20px 60px rgba(0, 0, 0, 0.3)",
            resize: "both",
            color: "var(--db-text)",
        });
        // Header
        const header = el("div", { class: "widget-config-header" });
        Object.assign(header.style, {
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "16px 20px",
            borderBottom: "1px solid var(--db-border)",
            background: "var(--db-surface-2)",
        });
        const title = el("h2", {}, `⚙️ ${this.widget.getTitle()} Settings`);
        Object.assign(title.style, {
            margin: "0",
            fontSize: "16px",
            fontWeight: "600",
            color: "var(--db-text)",
        });
        const closeBtn = el("button", { class: "widget-config-close", type: "button" }, "×");
        Object.assign(closeBtn.style, {
            background: "transparent",
            border: "none",
            fontSize: "24px",
            color: "var(--db-text-muted)",
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
            borderBottom: "1px solid var(--db-border)",
            background: "var(--db-surface-2)",
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
                borderBottom: tab.id === this.activeTabId ? "2px solid var(--db-accent)" : "2px solid transparent",
                color: tab.id === this.activeTabId ? "var(--db-accent)" : "var(--db-text-2)",
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
        // Create containers but don't render content yet (Lazy Loading)
        for (const tab of this.tabs) {
            const tabContent = el("div", { class: "widget-config-tab-content", "data-tab-id": tab.id });
            const isActive = tab.id === this.activeTabId;
            tabContent.style.display = isActive ? "block" : "none";
            this.tabContents.set(tab.id, tabContent);
            contentArea.appendChild(tabContent);
            // Only render active tab content
            if (isActive) {
                tab.render(tabContent, this.widget);
                this.renderedTabs.add(tab.id);
            }
        }
        // Footer with buttons
        const footer = el("div", { class: "widget-config-footer" });
        Object.assign(footer.style, {
            display: "flex",
            justifyContent: "flex-end",
            gap: "12px",
            padding: "16px 20px",
            borderTop: "1px solid var(--db-border)",
            background: "var(--db-surface-2)",
        });
        const cancelBtn = el("button", { class: "widget-config-btn", type: "button" }, "Cancel");
        Object.assign(cancelBtn.style, {
            padding: "10px 20px",
            borderRadius: "6px",
            border: "1px solid var(--db-border)",
            background: "transparent",
            color: "var(--db-text)",
            cursor: "pointer",
            fontSize: "13px",
        });
        const saveBtn = el("button", { class: "widget-config-btn-primary", type: "button" }, "Save");
        Object.assign(saveBtn.style, {
            padding: "10px 20px",
            borderRadius: "6px",
            border: "none",
            background: "var(--db-accent)",
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
            btnEl.style.borderBottomColor = isActive ? "var(--db-accent)" : "transparent";
            btnEl.style.color = isActive ? "var(--db-accent)" : "var(--db-text-2)";
            btnEl.style.fontWeight = isActive ? "600" : "400";
        });
        // Show/hide content and lazy render
        this.tabContents.forEach((content, id) => {
            const isActive = id === tabId;
            content.style.display = isActive ? "block" : "none";
            if (isActive && !this.renderedTabs.has(id)) {
                // Render specific tab on demand
                const tab = this.tabs.find(t => t.id === id);
                if (tab) {
                    tab.render(content, this.widget);
                    this.renderedTabs.add(id);
                }
            }
        });
        // Notify active tab
        const activeTab = this.tabs.find(t => t.id === tabId);
        if (activeTab?.onShow) {
            activeTab.onShow();
        }
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
    let titleColorInput;
    let titleBgInput;
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
            Object.assign(titleLabel.style, { display: "block", marginBottom: "6px", fontSize: "13px", fontWeight: "500", color: "var(--db-text)" });
            titleInput = el("input", { type: "text", value: widget.getTitle() });
            Object.assign(titleInput.style, { width: "100%", padding: "10px", borderRadius: "6px", border: "1px solid var(--db-border)", background: "var(--db-surface)", color: "var(--db-text)" });
            titleGroup.append(titleLabel, titleInput);
            // Icon field
            const iconGroup = el("div", { class: "config-field" });
            Object.assign(iconGroup.style, { marginBottom: "16px" });
            const iconLabel = el("label", {}, "Icon");
            Object.assign(iconLabel.style, { display: "block", marginBottom: "6px", fontSize: "13px", fontWeight: "500", color: "var(--db-text)" });
            iconInput = el("input", { type: "text", value: widget.getIcon() });
            Object.assign(iconInput.style, { width: "80px", padding: "10px", borderRadius: "6px", border: "1px solid var(--db-border)", background: "var(--db-surface)", color: "var(--db-text)", textAlign: "center" });
            iconGroup.append(iconLabel, iconInput);
            // Colors
            const colorsGroup = el("div", { class: "config-field" });
            Object.assign(colorsGroup.style, { marginBottom: "16px", display: "flex", gap: "20px" });
            // Text Color
            const textColorContainer = el("div", {});
            const textColorLabel = el("label", {}, "Title Color");
            Object.assign(textColorLabel.style, { display: "block", marginBottom: "6px", fontSize: "13px", fontWeight: "500", color: "var(--db-text)" });
            titleColorInput = el("input", { type: "color", value: widget.getTitleColor() || "#000000" });
            textColorContainer.append(textColorLabel, titleColorInput);
            // Bg Color
            const bgColorContainer = el("div", {});
            const bgColorLabel = el("label", {}, "Header Background");
            Object.assign(bgColorLabel.style, { display: "block", marginBottom: "6px", fontSize: "13px", fontWeight: "500", color: "var(--db-text)" });
            titleBgInput = el("input", { type: "color", value: widget.getTitleBackground() || "#ffffff" });
            bgColorContainer.append(bgColorLabel, titleBgInput);
            colorsGroup.append(textColorContainer, bgColorContainer);
            // Closable checkbox
            const closableGroup = el("div", { class: "config-field" });
            Object.assign(closableGroup.style, { marginBottom: "16px", display: "flex", alignItems: "center", gap: "8px" });
            closableCheckbox = el("input", { type: "checkbox", checked: widget.isClosable() ? "checked" : "" });
            const closableLabel = el("label", {}, "Allow closing this widget");
            Object.assign(closableLabel.style, { fontSize: "13px", color: "var(--db-text)" });
            closableGroup.append(closableCheckbox, closableLabel);
            container.append(titleGroup, iconGroup, colorsGroup, closableGroup);
        },
        save() {
            return {
                title: titleInput?.value,
                icon: iconInput?.value,
                style: {
                    titleColor: titleColorInput?.value,
                    titleBackground: titleBgInput?.value
                },
                closable: closableCheckbox?.checked
            };
        }
    };
}
/**
 * Create the "Share" tab for widgets.
 */
export function createShareTab(widget) {
    return {
        id: "share",
        label: "Share",
        icon: "🔗",
        render(container) {
            container.innerHTML = "";
            const info = el("div", { class: "share-info" }, "Share this widget directly.");
            Object.assign(info.style, { marginBottom: "16px", fontSize: "14px", color: "var(--db-text-2)" });

            const urlGroup = el("div", { class: "config-field" });
            Object.assign(urlGroup.style, { marginBottom: "16px" });

            const urlLabel = el("label", {}, "Widget Share URL");
            Object.assign(urlLabel.style, { display: "block", marginBottom: "6px", fontSize: "13px", fontWeight: "500", color: "var(--db-text)" });

            const widgetId = widget.id || "unknown";
            const shareUrl = `${window.location.origin}/share/widgets/${widgetId}`;

            const urlInput = el("input", { type: "text", value: shareUrl, readonly: "readonly" });
            Object.assign(urlInput.style, {
                width: "100%",
                padding: "10px 12px",
                borderRadius: "6px",
                border: "1px solid var(--db-border)",
                fontSize: "14px",
                backgroundColor: "var(--db-surface-2)",
                color: "var(--db-text-2)",
                boxSizing: "border-box",
            });

            const copyBtn = el("button", { type: "button" }, "Copy Link");
            Object.assign(copyBtn.style, {
                marginTop: "12px",
                padding: "10px 20px",
                borderRadius: "6px",
                border: "1px solid var(--db-border)",
                background: "var(--db-surface)",
                color: "var(--db-text)",
                cursor: "pointer",
                fontSize: "13px",
                fontWeight: "600",
            });

            on(copyBtn, "click", () => {
                urlInput.select();
                navigator.clipboard.writeText(shareUrl).then(() => {
                    copyBtn.textContent = "✓ Copied!";
                    setTimeout(() => copyBtn.textContent = "Copy Link", 2000);
                });
            });

            on(urlInput, "click", () => urlInput.select());

            urlGroup.append(urlLabel, urlInput, copyBtn);
            container.append(info, urlGroup);
        },
        save() { return {}; }
    };
}
/**
 * Open the configuration modal for a widget.
 */
export function openWidgetConfig(widget, additionalTabs = []) {
    const tabs = [
        createGeneralTab(widget),
        createShareTab(widget),
        ...additionalTabs
    ];
    const modal = new WidgetConfigModal(widget, tabs);
    modal.show();
    return modal;
}
//# sourceMappingURL=widget-config-modal.js.map