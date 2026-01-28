<script lang="ts">
    import { dashboardContainer } from "../../domain/dashboard-container.svelte.js";
    import { Widget } from "../../domain/widget.svelte.js";
    import TabBar from "./tab-bar.svelte";
    import type { WidgetType } from "../../domain/types.js";
    import DashboardTabView from "./dashboard-tab-view.svelte";

    // Explicitly derive state from the singleton to ensure reactivity
    let tabs = $derived(dashboardContainer.tabList);
    let activeId = $derived(dashboardContainer.activeTabId);
    let activeTab = $derived(dashboardContainer.activeTab);

    function handleAddWidget(tab: any, widgetType: WidgetType, name: string) {
        // Create new widget instance
        const newWidget = new Widget({
            title: name,
            icon: widgetType.icon,
        });

        // Add to the layout of the target tab
        tab.layout.addWidget(newWidget);
    }
</script>

<div class="dashboard-container">
    <TabBar
        {tabs}
        {activeId}
        onActivate={(id) => dashboardContainer.activateTab(id)}
        onCreate={() =>
            dashboardContainer.createTab({
                title: `Dashboard ${tabs.length + 1}`,
            })}
        onClose={(id) => dashboardContainer.removeTab(id)}
        onAddWidget={handleAddWidget}
    />

    <div class="dashboard-content">
        {#if activeTab}
            {#key activeTab.id}
                <DashboardTabView tab={activeTab} />
            {/key}
        {:else}
            <div class="empty-state">
                <div class="empty-message">
                    <span class="icon">📊</span>
                    <h2>No Dashboards</h2>
                    <p>Create a new dashboard to get started.</p>
                    <button
                        onclick={() =>
                            dashboardContainer.createTab({
                                title: "My Dashboard",
                            })}
                    >
                        Create Dashboard
                    </button>
                </div>
            </div>
        {/if}
    </div>
</div>

<style>
    .dashboard-container {
        display: flex;
        flex-direction: column;
        height: 100%;
        width: 100%;
        background: var(--bg, #f8f9fa);
    }

    .dashboard-content {
        flex: 1;
        overflow: hidden;
        position: relative;
    }

    .empty-state {
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .empty-message {
        text-align: center;
        color: var(--text-2, #6b7280);
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 1rem;
    }

    .empty-message .icon {
        font-size: 3rem;
    }

    button {
        padding: 8px 16px;
        background: var(--primary, #3b82f6);
        color: white;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        font-weight: 500;
    }
    button:hover {
        background: var(--primary-dark, #2563eb);
    }
</style>
