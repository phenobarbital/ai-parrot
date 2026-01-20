import type { DashboardView } from "./dashboard.js";
/**
 * Dashboard settings modal with tabbed interface.
 * - General: Edit title
 * - Layout: Save/Reset layout
 */
export declare class DashboardSettingsModal {
    private modal;
    private disposers;
    private activeTabId;
    private dashboard;
    constructor(dashboard: DashboardView);
    show(): void;
    private switchTab;
    private renderTabContent;
    private renderGeneralTab;
    private renderLayoutTab;
    private checkHasSavedLayout;
    hide(): void;
}
/**
 * Open the dashboard settings modal.
 */
export declare function openDashboardSettings(dashboard: DashboardView): DashboardSettingsModal;
//# sourceMappingURL=dashboard-settings-modal.d.ts.map