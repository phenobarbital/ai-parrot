// dashboard-settings-modal.ts - Settings modal for dashboard configuration
import { el, on, type Dispose } from "./utils.js";
import type { DashboardView } from "./dashboard.js";
import { LAYOUT_PRESETS } from "./grid-layout.js";

/**
 * Dashboard settings modal with tabbed interface.
 * - General: Edit title
 * - Layout: Save/Reset layout
 */
export class DashboardSettingsModal {
    private modal: HTMLElement | null = null;
    private disposers: Dispose[] = [];
    private activeTabId: string = "general";
    private dashboard: DashboardView;

    constructor(dashboard: DashboardView) {
        this.dashboard = dashboard;
    }

    show(): void {
        if (this.modal) return;

        // Overlay
        const overlay = el("div", { class: "dashboard-settings-overlay" });
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
        const modal = el("div", { class: "dashboard-settings-modal" });
        Object.assign(modal.style, {
            background: "#fff",
            borderRadius: "12px",
            width: "450px",
            maxWidth: "90vw",
            maxHeight: "80vh",
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            boxShadow: "0 20px 60px rgba(0, 0, 0, 0.3)",
        });

        // Header
        const header = el("div", { class: "dashboard-settings-header" });
        Object.assign(header.style, {
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "16px 20px",
            borderBottom: "1px solid #ddd",
            background: "#f8f9fa",
        });

        const title = el("h2", {}, `⚙️ Dashboard Settings`);
        Object.assign(title.style, { margin: "0", fontSize: "16px", fontWeight: "600" });

        const closeBtn = el("button", { type: "button" }, "×");
        Object.assign(closeBtn.style, {
            background: "transparent",
            border: "none",
            fontSize: "24px",
            cursor: "pointer",
            padding: "0 8px",
        });

        header.append(title, closeBtn);

        // Tab bar
        const tabBar = el("div", { class: "dashboard-settings-tabs" });
        Object.assign(tabBar.style, {
            display: "flex",
            padding: "0 16px",
            borderBottom: "1px solid #ddd",
            background: "#f8f9fa",
        });

        const tabs = [
            { id: "general", label: "⚙️ General" },
            { id: "layout", label: "📐 Layout" },
            { id: "share", label: "🔗 Share" },
        ];

        for (const tab of tabs) {
            const tabBtn = el("button", { type: "button", "data-tab-id": tab.id }, tab.label);
            Object.assign(tabBtn.style, {
                padding: "12px 16px",
                background: "transparent",
                border: "none",
                borderBottom: tab.id === this.activeTabId ? "2px solid #3b82f6" : "2px solid transparent",
                color: tab.id === this.activeTabId ? "#3b82f6" : "#666",
                cursor: "pointer",
                fontSize: "13px",
                fontWeight: tab.id === this.activeTabId ? "600" : "400",
            });

            this.disposers.push(on(tabBtn, "click", () => this.switchTab(tab.id, tabBar, contentArea)));
            tabBar.appendChild(tabBtn);
        }

        // Content area
        const contentArea = el("div", { class: "dashboard-settings-content" });
        Object.assign(contentArea.style, { flex: "1", padding: "20px", overflow: "auto" });

        this.renderTabContent(contentArea);

        // Footer
        const footer = el("div", { class: "dashboard-settings-footer" });
        Object.assign(footer.style, {
            display: "flex",
            justifyContent: "flex-end",
            gap: "12px",
            padding: "16px 20px",
            borderTop: "1px solid #ddd",
            background: "#f8f9fa",
        });

        const closeFooterBtn = el("button", { type: "button" }, "Close");
        Object.assign(closeFooterBtn.style, {
            padding: "10px 20px",
            borderRadius: "6px",
            border: "1px solid #ddd",
            background: "transparent",
            cursor: "pointer",
            fontSize: "13px",
        });

        footer.append(closeFooterBtn);

        modal.append(header, tabBar, contentArea, footer);
        overlay.appendChild(modal);

        // Event handlers
        this.disposers.push(
            on(closeBtn, "click", () => this.hide()),
            on(closeFooterBtn, "click", () => this.hide()),
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
        tabBar.querySelectorAll("button").forEach(btn => {
            const isActive = (btn as HTMLElement).dataset.tabId === tabId;
            (btn as HTMLElement).style.borderBottomColor = isActive ? "#3b82f6" : "transparent";
            (btn as HTMLElement).style.color = isActive ? "#3b82f6" : "#666";
            (btn as HTMLElement).style.fontWeight = isActive ? "600" : "400";
        });

        this.renderTabContent(contentArea);
    }

    private renderTabContent(container: HTMLElement): void {
        container.innerHTML = "";

        if (this.activeTabId === "general") {
            this.renderGeneralTab(container);
        } else if (this.activeTabId === "layout") {
            this.renderLayoutTab(container);
        } else if (this.activeTabId === "share") {
            this.renderShareTab(container);
        }
    }

    private renderGeneralTab(container: HTMLElement): void {
        // Title field
        const titleGroup = el("div", { class: "config-field" });
        Object.assign(titleGroup.style, { marginBottom: "16px" });

        const titleLabel = el("label", {}, "Dashboard Title");
        Object.assign(titleLabel.style, {
            display: "block",
            marginBottom: "6px",
            fontSize: "13px",
            fontWeight: "500",
        });

        const titleInput = el("input", {
            type: "text",
            value: this.dashboard.getTitle(),
        }) as HTMLInputElement;
        Object.assign(titleInput.style, {
            width: "100%",
            padding: "10px 12px",
            borderRadius: "6px",
            border: "1px solid #ddd",
            fontSize: "14px",
            boxSizing: "border-box",
        });

        const saveBtn = el("button", { type: "button" }, "Save Title");
        Object.assign(saveBtn.style, {
            marginTop: "12px",
            padding: "10px 20px",
            borderRadius: "6px",
            border: "none",
            background: "#3b82f6",
            color: "#fff",
            cursor: "pointer",
            fontSize: "13px",
            fontWeight: "600",
        });

        this.disposers.push(on(saveBtn, "click", () => {
            this.dashboard.setTitle(titleInput.value);
            // Show feedback
            saveBtn.textContent = "✓ Saved!";
            setTimeout(() => saveBtn.textContent = "Save Title", 1500);
        }));

        titleGroup.append(titleLabel, titleInput, saveBtn);
        container.appendChild(titleGroup);
    }

    private renderLayoutTab(container: HTMLElement): void {
        // Status display
        const statusGroup = el("div", { class: "layout-status" });
        Object.assign(statusGroup.style, {
            marginBottom: "20px",
            padding: "12px",
            background: "#f0f9ff",
            borderRadius: "8px",
            fontSize: "13px",
        });

        const hasLayout = this.checkHasSavedLayout();
        statusGroup.innerHTML = hasLayout
            ? `<strong>✓ Layout Saved</strong><br><span style="color:#666">Widget positions will be restored on page load.</span>`
            : `<strong>No Saved Layout</strong><br><span style="color:#666">Widget positions will use defaults.</span>`;

        container.appendChild(statusGroup);

        // Buttons
        const buttonGroup = el("div", { class: "layout-buttons" });
        Object.assign(buttonGroup.style, { display: "flex", gap: "12px", flexWrap: "wrap" });

        const saveBtn = el("button", { type: "button" }, "💾 Save Current Layout");
        Object.assign(saveBtn.style, {
            padding: "12px 20px",
            borderRadius: "6px",
            border: "none",
            background: "#10b981",
            color: "#fff",
            cursor: "pointer",
            fontSize: "13px",
            fontWeight: "600",
        });

        const resetBtn = el("button", { type: "button" }, "🔄 Reset to Default");
        Object.assign(resetBtn.style, {
            padding: "12px 20px",
            borderRadius: "6px",
            border: "1px solid #ddd",
            background: "transparent",
            cursor: "pointer",
            fontSize: "13px",
        });

        this.disposers.push(on(saveBtn, "click", () => {
            this.dashboard.saveLayout();
            saveBtn.textContent = "✓ Layout Saved!";
            this.renderLayoutTab(container); // Re-render to update status
        }));

        this.disposers.push(on(resetBtn, "click", () => {
            if (confirm("Reset layout to default positions? This will clear saved layout.")) {
                this.dashboard.resetLayout();
                resetBtn.textContent = "✓ Reset!";
                this.renderLayoutTab(container);
            }
        }));

        buttonGroup.append(saveBtn, resetBtn);
        container.appendChild(buttonGroup);

        // Grid Options (Only shown if in grid mode)
        if (this.dashboard.getLayoutMode() === "grid") {
            const separator = el("hr");
            Object.assign(separator.style, { margin: "20px 0", border: "none", borderTop: "1px solid #eee" });
            container.appendChild(separator);

            const gridTitle = el("h3", {}, "Grid Layout Mode");
            Object.assign(gridTitle.style, { margin: "0 0 12px 0", fontSize: "14px" });
            container.appendChild(gridTitle);

            const gridOptions = el("div", { class: "grid-layout-options" });
            Object.assign(gridOptions.style, {
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "12px"
            });

            const currentPreset = this.dashboard.getGridLayoutPreset();

            Object.values(LAYOUT_PRESETS).forEach(preset => {
                const isSelected = currentPreset === preset.id;
                const option = el("button", { class: "layout-option-card" });
                Object.assign(option.style, {
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    gap: "8px",
                    padding: "12px",
                    background: isSelected ? "var(--accent-light, #eff6ff)" : "#fff",
                    border: `2px solid ${isSelected ? "var(--accent, #3b82f6)" : "#eee"}`,
                    borderRadius: "8px",
                    cursor: "pointer",
                    transition: "all 0.2s"
                });

                // Mini preview
                const preview = el("div");
                Object.assign(preview.style, {
                    display: "grid",
                    gridTemplateColumns: preset.templateColumns.replace("repeat(12, 1fr)", "repeat(4, 1fr)"), // Simplify for preview
                    gap: "2px",
                    width: "100%",
                    height: "40px",
                    marginBottom: "4px"
                });

                // Generate boxes for preview
                const colCount = preset.cols > 4 ? 4 : preset.cols;
                for (let i = 0; i < colCount; i++) {
                    const box = el("div");
                    Object.assign(box.style, {
                        backgroundColor: "#ddd",
                        borderRadius: "2px"
                    });
                    preview.appendChild(box);
                }

                const label = el("span", {}, preset.name);
                Object.assign(label.style, { fontSize: "12px", fontWeight: "600" });

                const desc = el("span", {}, preset.description || "");
                Object.assign(desc.style, { fontSize: "10px", color: "#666" });

                option.append(preview, label, desc);

                on(option, "click", () => {
                    this.dashboard.setGridLayout(preset.id);
                    // Re-render to update selection state
                    this.renderLayoutTab(container);
                });

                gridOptions.appendChild(option);
            });

            container.appendChild(gridOptions);
        }
    }

    private checkHasSavedLayout(): boolean {
        // Check localStorage for this dashboard's layout
        const key = `${this.dashboard.layoutMode}-layout-${this.dashboard.id}`;
        return localStorage.getItem(key) !== null;
    }

    private renderShareTab(container: HTMLElement): void {
        const info = el("div", { class: "share-info" }, "Share this dashboard with others.");
        Object.assign(info.style, { marginBottom: "16px", fontSize: "14px", color: "#666" });

        const urlGroup = el("div", { class: "config-field" });
        Object.assign(urlGroup.style, { marginBottom: "16px" });

        const urlLabel = el("label", {}, "Share URL");
        Object.assign(urlLabel.style, {
            display: "block",
            marginBottom: "6px",
            fontSize: "13px",
            fontWeight: "500",
        });

        const shareUrl = `${window.location.origin}/share/dashboard/${this.dashboard.id}`;

        const urlInput = el("input", {
            type: "text",
            value: shareUrl,
            readonly: "readonly"
        }) as HTMLInputElement;
        Object.assign(urlInput.style, {
            width: "100%",
            padding: "10px 12px",
            borderRadius: "6px",
            border: "1px solid #ddd",
            fontSize: "14px",
            backgroundColor: "#f9f9f9",
            color: "#666",
            boxSizing: "border-box",
        });

        // Copy button
        const copyBtn = el("button", { type: "button" }, "Copy Link");
        Object.assign(copyBtn.style, {
            marginTop: "12px",
            padding: "10px 20px",
            borderRadius: "6px",
            border: "1px solid #ddd",
            background: "#fff",
            cursor: "pointer",
            fontSize: "13px",
            fontWeight: "600",
            display: "flex",
            alignItems: "center",
            gap: "6px"
        });

        this.disposers.push(on(copyBtn, "click", () => {
            urlInput.select();
            navigator.clipboard.writeText(shareUrl).then(() => {
                copyBtn.textContent = "✓ Copied!";
                setTimeout(() => copyBtn.textContent = "Copy Link", 2000);
            });
        }));

        this.disposers.push(on(urlInput, "click", () => urlInput.select()));

        urlGroup.append(urlLabel, urlInput, copyBtn);
        container.appendChild(info);
        container.appendChild(urlGroup);
    }

    hide(): void {
        if (!this.modal) return;

        for (const d of this.disposers) d();
        this.disposers = [];

        this.modal.remove();
        this.modal = null;
    }
}

/**
 * Open the dashboard settings modal.
 */
export function openDashboardSettings(dashboard: DashboardView): DashboardSettingsModal {
    const modal = new DashboardSettingsModal(dashboard);
    modal.show();
    return modal;
}
