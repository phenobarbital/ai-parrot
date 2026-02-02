    import { dashboardContainer as defaultContainer, DashboardContainer } from "../../domain/dashboard-container.svelte.js";
    import { IFrameWidget } from "../../domain/iframe-widget.svelte.js";
    // ... imports ...
    import { type DashboardTab } from "../../domain/dashboard-tab.svelte.js";

    let { container = defaultContainer } = $props<{ container?: DashboardContainer }>();

    let showShareModal = $state(false);
    let shareUrl = $state('');

    async function handleShare(tab?: DashboardTab) {
        // Create an immutable snapshot for sharing
        const snapshotId = await SnapshotService.createSnapshot(tab);
        
        // Generate share URL
        shareUrl = `${window.location.origin}/share/dashboards/${snapshotId}`;
        showShareModal = true;
    }

    // Explicitly derive state from the container to ensure reactivity
    let tabs = $derived(container.tabList);
    let activeId = $derived(container.activeTabId);
    let activeTab = $derived(container.activeTab);

    function handleAddWidget(
        tab: any,
        widgetType: WidgetType,
        name: string,
        config?: { url?: string },
    ) {
        let newWidget: Widget;
        switch (widgetType.id) {
            case "iframe":
                newWidget = new IFrameWidget({
                    title: name,
                    icon: widgetType.icon,
                    url: config?.url,
                });
                break;
            // ... (keep cases as is) ...
            default:
                newWidget = new Widget({
                    title: name,
                    icon: widgetType.icon,
                });
        }

        // Add to the layout of the target tab
        if (tab?.layout) {
            tab.layout.addWidget(newWidget);
            container.save().catch(e => console.error('Auto-save failed:', e));
        }
    }
</script>

<div class="dashboard-container">
    {#if !activeTab?.slideshowState.active}
        <TabBar
            {tabs}
            {activeId}
            onActivate={(id) => container.activateTab(id)}
            onCreate={() =>
                container.createTab({
                    title: `Dashboard ${tabs.length + 1}`,
                })}
            onClose={(id) => container.removeTab(id)}
            onAddWidget={handleAddWidget}
            onShare={handleShare}
        />
    {/if}

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
                            container.createTab({
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

{#if showShareModal}
    <ShareModal 
        url={shareUrl} 
        title="Share Dashboard" 
        onClose={() => showShareModal = false} 
    />
{/if}

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
