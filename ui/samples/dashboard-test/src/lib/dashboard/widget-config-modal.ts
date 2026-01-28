// widget-config-modal.ts - Tabbed configuration modal for widgets
import { el, on, stop, type Dispose } from "./utils.js";
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
export class WidgetConfigModal {
    private modal: HTMLElement | null = null;
    private disposers: Dispose[] = [];
    private activeTabId: string = "";
    private tabContents = new Map<string, HTMLElement>();
    private renderedTabs = new Set<string>();

    constructor(
        private widget: Widget,
        private tabs: ConfigTab[]
    ) { }

    show(): void {
        if (this.modal) return;
        if (this.tabs.length === 0) return;

        this.activeTabId = this.tabs[0]!.id;

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

            this.disposers.push(
                on(tabBtn, "click", () => this.switchTab(tab.id, tabBar, contentArea))
            );

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
        this.disposers.push(
            on(closeBtn, "click", () => this.hide()),
            on(cancelBtn, "click", () => this.hide()),
            on(saveBtn, "click", () => this.save()),
            on(overlay, "click", (ev) => {
                if (ev.target === overlay) this.hide();
            }),
            on(window, "keydown", (ev) => {
                if ((ev as KeyboardEvent).key === "Escape") this.hide();
            })
        );

        document.body.appendChild(overlay);
        this.modal = overlay;
    }

    private switchTab(tabId: string, tabBar: HTMLElement, contentArea: HTMLElement): void {
        this.activeTabId = tabId;

        // Update tab buttons
        tabBar.querySelectorAll(".widget-config-tab").forEach(btn => {
            const btnEl = btn as HTMLElement;
            const isActive = btnEl.dataset.tabId === tabId;
            btnEl.style.borderBottomColor = isActive ? "var(--accent, #3b82f6)" : "transparent";
            btnEl.style.color = isActive ? "var(--accent, #3b82f6)" : "var(--text-muted, #666)";
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

    private save(): void {
        const config: Record<string, unknown> = {};

        for (const tab of this.tabs) {
            const tabConfig = tab.save();
            Object.assign(config, tabConfig);
        }

        // Call widget's onConfigSave hook
        (this.widget as any).onConfigSave(config);

        this.hide();
    }

    hide(): void {
        if (!this.modal) return;

        for (const d of this.disposers) d();
        this.disposers = [];
        this.tabContents.clear();

        this.modal.remove();
        this.modal = null;
    }
}

/**
 * Create the default "General" tab for all widgets.
 */
export function createGeneralTab(widget: Widget): ConfigTab {
    let titleInput: HTMLInputElement;
    let iconInput: HTMLInputElement;
    let closableCheckbox: HTMLInputElement;
    let titleColorInput: HTMLInputElement;
    let titleBgInput: HTMLInputElement;
    let isSystemCheckbox: HTMLInputElement;

    return {
        id: "general",
        label: "General",
        icon: "⚙️",
        render(container: HTMLElement) {
            container.innerHTML = "";

            // Title field
            const titleGroup = el("div", { class: "config-field" });
            Object.assign(titleGroup.style, { marginBottom: "16px" });
            titleGroup.append(
                el("label", { style: "display:block; margin-bottom:6px; font-size:13px; font-weight:500;" }, "Title"),
                titleInput = el("input", { type: "text", value: widget.getTitle() }) as HTMLInputElement
            );
            Object.assign(titleInput.style, { width: "100%", padding: "10px", borderRadius: "6px", border: "1px solid #ddd" });

            // Icon field
            const iconGroup = el("div", { class: "config-field" });
            Object.assign(iconGroup.style, { marginBottom: "16px" });
            iconGroup.append(
                el("label", { style: "display:block; margin-bottom:6px; font-size:13px; font-weight:500;" }, "Icon"),
                iconInput = el("input", { type: "text", value: widget.getIcon() }) as HTMLInputElement
            );
            Object.assign(iconInput.style, { width: "80px", padding: "10px", borderRadius: "6px", border: "1px solid #ddd", textAlign: "center" });

            // Colors
            const colorsGroup = el("div", { class: "config-field" });
            Object.assign(colorsGroup.style, { marginBottom: "16px", display: "flex", gap: "20px" });

            // Text Color
            const textColorContainer = el("div", {});
            textColorContainer.append(
                el("label", { style: "display:block; margin-bottom:6px; font-size:13px; font-weight:500;" }, "Title Color"),
                titleColorInput = el("input", { type: "color", value: (widget as any).getTitleColor() || "#000000" }) as HTMLInputElement
            );
            // Bg Color
            const bgColorContainer = el("div", {});
            bgColorContainer.append(
                el("label", { style: "display:block; margin-bottom:6px; font-size:13px; font-weight:500;" }, "Header Background"),
                titleBgInput = el("input", { type: "color", value: (widget as any).getTitleBackground() || "#ffffff" }) as HTMLInputElement
            );

            colorsGroup.append(textColorContainer, bgColorContainer);

            // Closable checkbox
            const closableGroup = el("div", { class: "config-field" });
            Object.assign(closableGroup.style, { marginBottom: "16px", display: "flex", alignItems: "center", gap: "8px" });
            closableGroup.append(
                closableCheckbox = el("input", { type: "checkbox", checked: (widget as any).isClosable() ? "checked" : "" }) as HTMLInputElement,
                el("label", { style: "font-size:13px;" }, "Allow closing this widget")
            );

            // Is System checkbox
            const systemGroup = el("div", { class: "config-field" });
            Object.assign(systemGroup.style, { marginBottom: "16px", display: "flex", alignItems: "center", gap: "8px" });
            systemGroup.append(
                isSystemCheckbox = el("input", { type: "checkbox", checked: (widget as any).opts?.is_system ? "checked" : "" }) as HTMLInputElement,
                el("label", { style: "font-size:13px;" }, "Is System Widget (Protected)")
            );

            container.append(titleGroup, iconGroup, colorsGroup, closableGroup, systemGroup);
        },
        save() {
            return {
                title: titleInput?.value,
                icon: iconInput?.value,
                style: {
                    titleColor: titleColorInput?.value,
                    titleBackground: titleBgInput?.value
                },
                closable: closableCheckbox?.checked,
                is_system: isSystemCheckbox?.checked
            };
        }
    };
}

/**
 * Open the configuration modal for a widget.
 */
export function openWidgetConfig(widget: Widget, additionalTabs: ConfigTab[] = []): WidgetConfigModal {
    const tabs = [
        createGeneralTab(widget),
        ...additionalTabs
    ];

    const modal = new WidgetConfigModal(widget, tabs);
    modal.show();
    return modal;
}
