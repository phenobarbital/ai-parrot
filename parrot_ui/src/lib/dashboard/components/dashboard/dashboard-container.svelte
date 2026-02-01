<script lang="ts">
    import { dashboardContainer } from "../../domain/dashboard-container.svelte.js";
    import { IFrameWidget } from "../../domain/iframe-widget.svelte.js";
    import { ImageWidget } from "../../domain/image-widget.svelte.js";
    import { Widget } from "../../domain/widget.svelte.js";
    import { DataWidget } from "../../domain/data-widget.svelte.js";
    import { QSWidget } from "../../domain/qs-widget.svelte.js";
    import { SimpleTableWidget } from "../../domain/simple-table-widget.svelte.js";
    import { TableWidget } from "../../domain/table-widget.svelte.js";
    import { VideoWidget } from "../../domain/video-widget.svelte.js";
    import { YouTubeWidget } from "../../domain/youtube-widget.svelte.js";
    import { VimeoWidget } from "../../domain/vimeo-widget.svelte.js";
    import { PdfWidget } from "../../domain/pdf-widget.svelte.js";
    import { HtmlWidget } from "../../domain/html-widget.svelte.js";
    import { MarkdownWidget } from "../../domain/markdown-widget.svelte.js";
    import { EchartsWidget } from "../../domain/echarts-widget.svelte.js";
    import { VegaChartWidget } from "../../domain/vega-chart-widget.svelte.js";
    import { FrappeChartWidget } from "../../domain/frappe-chart-widget.svelte.js";
    import { CarbonChartsWidget } from "../../domain/carbon-charts-widget.svelte.js";
    import { BasicChartWidget } from "../../domain/basic-chart-widget.svelte.js";
    import { LayerChartWidget } from "../../domain/layer-chart-widget.svelte.js";
    import { MapWidget } from "../../domain/map-widget.svelte.js";
    import { DEFAULT_QS_URL } from "../../domain/qs-datasource.svelte.js";
    import TabBar from "./tab-bar.svelte";
    import type { WidgetType } from "../../domain/types.js";
    import DashboardTabView from "./dashboard-tab-view.svelte";
    import { SnapshotService } from '$lib/share/snapshot-service';
    import ShareModal from "$lib/dashboard/components/modals/ShareModal.svelte";

    import { type DashboardTab } from "../../domain/dashboard-tab.svelte.js";

    let showShareModal = $state(false);
    let shareUrl = $state('');

    async function handleShare(tab?: DashboardTab) {
        // Create an immutable snapshot for sharing
        const snapshotId = await SnapshotService.createSnapshot(tab);
        
        // Generate share URL
        shareUrl = `${window.location.origin}/share/dashboards/${snapshotId}`;
        showShareModal = true;
    }

    // Explicitly derive state from the singleton to ensure reactivity
    let tabs = $derived(dashboardContainer.tabList);
    let activeId = $derived(dashboardContainer.activeTabId);
    let activeTab = $derived(dashboardContainer.activeTab);

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
            case "image":
                newWidget = new ImageWidget({
                    title: name,
                    icon: widgetType.icon,
                    url: config?.url,
                });
                break;
            case "data":
                newWidget = new DataWidget({
                    title: name,
                    icon: widgetType.icon,
                    dataSource: {
                        url:
                            config?.url ??
                            "https://api.restful-api.dev/objects",
                        method: "GET",
                    },
                });
                break;
            case "querysource":
                newWidget = new QSWidget({
                    title: name,
                    icon: widgetType.icon,
                    qsConfig: {
                        slug: config?.url ?? "hisense_stores", // reusing url param for slug if passed
                        baseUrl: DEFAULT_QS_URL,
                    },
                });
                break;
            case "simpletable":
                newWidget = new SimpleTableWidget({
                    title: name,
                    icon: widgetType.icon,
                });
                break;
            case "table":
                newWidget = new TableWidget({
                    title: name,
                    icon: widgetType.icon,
                });
                break;
            case "youtube":
                newWidget = new YouTubeWidget({
                    title: name,
                    icon: widgetType.icon,
                    url: config?.url,
                });
                break;
            case "vimeo":
                newWidget = new VimeoWidget({
                    title: name,
                    icon: widgetType.icon,
                    url: config?.url,
                });
                break;
            case "video":
                newWidget = new VideoWidget({
                    title: name,
                    icon: widgetType.icon,
                    url: config?.url,
                });
                break;
            case "pdf":
                newWidget = new PdfWidget({
                    title: name,
                    icon: widgetType.icon,
                    url: config?.url,
                });
                break;
            case "html":
                newWidget = new HtmlWidget({
                    title: name,
                    icon: widgetType.icon,
                });
                break;
            case "markdown":
                newWidget = new MarkdownWidget({
                    title: name,
                    icon: widgetType.icon,
                });
                break;
            case "markdown":
                newWidget = new MarkdownWidget({
                    title: name,
                    icon: widgetType.icon,
                });
                break;
            case "echarts":
                newWidget = new EchartsWidget({
                    title: name,
                    icon: widgetType.icon,
                });
                break;
            case "basicchart":
                newWidget = new BasicChartWidget({
                    title: name,
                    icon: widgetType.icon,
                });
                break;
            case "vega":
                newWidget = new VegaChartWidget({
                    title: name,
                    icon: widgetType.icon,
                });
                break;
            case "frappe":
                newWidget = new FrappeChartWidget({
                    title: name,
                    icon: widgetType.icon,
                });
                break;
            case "carbon":
                newWidget = new CarbonChartsWidget({
                    title: name,
                    icon: widgetType.icon,
                });
                break;
            case "layerchart":
                newWidget = new LayerChartWidget({
                    title: name,
                    icon: widgetType.icon,
                });
                break;
            case "map":
                newWidget = new MapWidget({
                    title: name,
                    icon: widgetType.icon,
                });
                break;
            default:
                newWidget = new Widget({
                    title: name,
                    icon: widgetType.icon,
                });
        }

        // Add to the layout of the target tab
        if (tab?.layout) {
            tab.layout.addWidget(newWidget);
            dashboardContainer.save().catch(e => console.error('Auto-save failed:', e));
        }
    }
</script>

<div class="dashboard-container">
    {#if !activeTab?.slideshowState.active}
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
