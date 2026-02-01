<script lang="ts">
    import type { Widget } from "../../domain/widget.svelte.js";
    import type { ConfigTab } from "../../domain/types.js";
    import type { DataSourceConfig } from "../../domain/data-source.svelte.js";
    import type { QSDataSourceConfig } from "../../domain/qs-datasource.svelte.js";
    import DataSourceConfigTab from "../settings/data-source-config-tab.svelte";
    import QSConfigTab from "../settings/qs-config-tab.svelte";
    import SimpleTableDataTab from "../settings/simple-table-data-tab.svelte";
    import SimpleTableSettingsTab from "../settings/simple-table-settings-tab.svelte";
    import TableDataTab from "../settings/table-data-tab.svelte";
    import TableSettingsTab from "../settings/table-settings-tab.svelte";
    import HtmlEditorTab from "../settings/html-editor-tab.svelte";
    import MarkdownEditorTab from "../settings/markdown-editor-tab.svelte";
    import { QSWidget } from "../../domain/qs-widget.svelte.js";
    import { HtmlWidget } from "../../domain/html-widget.svelte.js";
    import { MarkdownWidget } from "../../domain/markdown-widget.svelte.js";
    import {
        SimpleTableWidget,
        type DataSourceType as SimpleDataSourceType,
        type JsonDataSourceConfig as SimpleJsonConfig,
        type ColumnConfig,
        type TotalType,
    } from "../../domain/simple-table-widget.svelte.js";
    import {
        TableWidget,
        type DataSourceType as TableDataSourceType,
        type JsonDataSourceConfig as TableJsonConfig,
        type GridType,
        type GridConfig,
    } from "../../domain/table-widget.svelte.js";

    import {
        BasicChartWidget,
        type ChartEngine,
    } from "../../domain/basic-chart-widget.svelte.js";
    import {
        MapWidget,
        type MapConfig,
        type MapJsonDataSourceConfig,
    } from "../../domain/map-widget.svelte.js";
    import { LayerChartWidget } from "../../domain/layer-chart-widget.svelte.js";
    import ChartSettingsTab from "../settings/chart-settings-tab.svelte";
    import ChartDataTab, {
        type DataWidgetLike,
    } from "../settings/chart-data-tab.svelte";
    import ChartEngineTab from "../settings/chart-engine-tab.svelte";
    import MapConfigTab from "../settings/map-config-tab.svelte";
    import {
        BaseChartWidget,
        type ChartType,
    } from "../../domain/base-chart-widget.svelte.js";
    import { SnapshotService } from '$lib/share/snapshot-service';

    // ... imports ...

    interface Props {
        widget: Widget;
        onClose: () => void;
    }

    let { widget, onClose }: Props = $props();

    // Tab state
    let activeTabId = $state("general");
    let renderedTabs = $state<Set<string>>(new Set(["general"]));

    // General tab form state
    let title = $state(widget.title);
    let icon = $state(widget.icon);
    let titleColor = $state(widget.titleColor);
    let titleBackground = $state(widget.titleBackground);
    let closable = $state(widget.closable);
    let chromeHidden = $state(widget.chromeHidden);
    let translucent = $state(widget.translucent);

    // DataSource config state
    let pendingDataSourceConfig = $state<DataSourceConfig | null>(null);

    // Chart config state
    let pendingChartSettings = $state<{
        chartType?: ChartType;
        xAxis?: string;
        yAxis?: string;
        labelColumn?: string;
        dataColumn?: string;
    } | null>(null);

    let pendingChartDataConfig = $state<{
        dataSourceType: "rest" | "qs" | "json";
        restConfig?: DataSourceConfig;
        qsConfig?: QSDataSourceConfig;
        jsonConfig?: {
            mode: "inline" | "url";
            json?: string;
            url?: string;
        };
    } | null>(null);
    let pendingChartEngine = $state<ChartEngine | null>(null);

    let pendingMapDataConfig = $state<{
        dataSourceType: "rest" | "qs" | "json";
        restConfig?: DataSourceConfig;
        qsConfig?: QSDataSourceConfig;
        jsonConfig?: MapJsonDataSourceConfig;
    } | null>(null);

    let pendingMapSettings = $state<MapConfig | null>(null);

    // SimpleTableWidget config state
    let pendingSimpleTableDataConfig = $state<{
        dataSourceType: SimpleDataSourceType;
        restConfig?: DataSourceConfig;
        qsConfig?: QSDataSourceConfig;
        jsonConfig?: SimpleJsonConfig;
    } | null>(null);
    let pendingSimpleTableSettings = $state<{
        zebra?: boolean;
        totals?: TotalType;
        columns?: ColumnConfig[];
    } | null>(null);

    // TableWidget config state
    let pendingTableDataConfig = $state<{
        dataSourceType: TableDataSourceType;
        restConfig?: DataSourceConfig;
        qsConfig?: QSDataSourceConfig;
        jsonConfig?: TableJsonConfig;
    } | null>(null);
    let pendingTableSettings = $state<{
        gridType?: GridType;
        gridConfig?: Partial<GridConfig>;
    } | null>(null);

    let pendingQSConfig = $state<QSDataSourceConfig | null>(null);

    // Content widget config state (for HTML/Markdown widgets)
    let pendingContentConfig = $state<{ content: string } | null>(null);

    // Widget type checks
    const isSimpleTable = widget instanceof SimpleTableWidget;
    const isTableWidget = widget instanceof TableWidget;
    const isHtmlWidget = widget instanceof HtmlWidget;
    const isMarkdownWidget = widget instanceof MarkdownWidget;
    const isContentWidget = isHtmlWidget || isMarkdownWidget;

    // Check for chart widgets
    const isChartWidget =
        widget instanceof BaseChartWidget || widget instanceof LayerChartWidget;
    const isBasicChart = widget instanceof BasicChartWidget;
    const isMapWidget = widget instanceof MapWidget;

    // Get all tabs (general + datasource if applicable + content for HTML/Markdown + custom)
    // For content widgets, we DON'T include the default custom tabs from getConfigTabs()
    // because we provide our own WYSIWYG editor
    const customTabs = isContentWidget ? [] : widget.getConfigTabs();
    const allTabs: Array<{ id: string; label: string; icon?: string }> = [
        { id: "general", label: "General", icon: "⚙️" },
        // SimpleTableWidget has its own data & table tabs
        ...(isSimpleTable
            ? [
                  { id: "datasource", label: "Data Source", icon: "🔗" },
                  { id: "tablesettings", label: "Table", icon: "▦" },
              ]
            : isTableWidget
              ? [
                    { id: "datasource", label: "Data Source", icon: "🔗" },
                    { id: "tablesettings", label: "Table Config", icon: "📊" },
                ]
              : isContentWidget
                ? [{ id: "content", label: "Content", icon: "📝" }]
                : isChartWidget
                  ? isBasicChart
                      ? [
                            {
                                id: "datasource",
                                label: "Data Source",
                                icon: "🔗",
                            },
                            {
                                id: "chartengine",
                                label: "Chart Engine",
                                icon: "🧩",
                            },
                            {
                                id: "chartsettings",
                                label: "Chart Options",
                                icon: "📊",
                            },
                        ]
                      : [
                            {
                                id: "datasource",
                                label: "Data Source",
                                icon: "🔗",
                            },
                            {
                                id: "chartsettings",
                                label: "Chart Options",
                                icon: "📊",
                            },
                        ]
                  : isMapWidget
                    ? [
                          {
                              id: "datasource",
                              label: "Data Source",
                              icon: `<svg class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.213 9.787a3.391 3.391 0 0 0-4.795 0l-3.425 3.426a3.39 3.39 0 0 0 4.795 4.794l.321-.304m-.321-4.49a3.39 3.39 0 0 0 4.795 0l3.424-3.426a3.39 3.39 0 0 0-4.794-4.795l-1.028.961"/></svg>`,
                          },
                          { id: "mapsettings", label: "Map", icon: `<svg class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 17.345a4.76 4.76 0 0 0 2.558 1.618c2.274.589 4.512-.446 4.999-2.31.487-1.866-1.273-3.9-3.546-4.49-2.273-.59-4.015-2.623-3.528-4.489.487-1.865 2.724-2.899 4.998-2.309 1.487.387 2.454 1.257 2.923 2.14m-3.999 1.46c2.274.59 4.512-.447 4.999-2.31.487-1.866-1.273-3.901-3.546-4.49-2.273-.59-4.015-2.624-3.528-4.49.487-1.865 2.724-2.899 4.998-2.309 1.487.387 2.454 1.257 2.923 2.14"/></svg>` },
                      ]
                    : widget.hasDataSource
                      ? [{ id: "datasource", label: "Data Source", icon: `<svg class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.213 9.787a3.391 3.391 0 0 0-4.795 0l-3.425 3.426a3.39 3.39 0 0 0 4.795 4.794l.321-.304m-.321-4.49a3.39 3.39 0 0 0 4.795 0l3.424-3.426a3.39 3.39 0 0 0-4.794-4.795l-1.028.961"/></svg>` }]
                      : []),
        ...customTabs.map((t) => ({ id: t.id, label: t.label, icon: t.icon })),
        // Always add Share tab
        { id: "share", label: "Share", icon: `<svg class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h6l2 4m-8-4v8m0-8V6a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v9h2m8 0H9m4 0h2m4 0h2v-4m0 0h-5m3.5 5.5a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Zm-10 0a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z"/></svg>` },
    ];

    function switchTab(tabId: string) {
        activeTabId = tabId;
        if (!renderedTabs.has(tabId)) {
            renderedTabs = new Set([...renderedTabs, tabId]);
        }
    }

    async function handleSave() {
        // General tab config
        const config: Record<string, unknown> = {
            title,
            icon,
            closable,
            chromeHidden,
            translucent,
            style: {
                titleColor,
                titleBackground,
            },
        };
        if (isBasicChart) {
            const chartWidget = widget as BasicChartWidget;
            config.chartEngine = pendingChartEngine ?? chartWidget.chartEngine;
        }

        // Collect from custom tabs
        for (const tab of customTabs) {
            const tabConfig = tab.save();
            Object.assign(config, tabConfig);
        }

        widget.onConfigSave(config);

        // Apply DataSource config if modified
        if (pendingDataSourceConfig && pendingDataSourceConfig.url) {
            widget.setDataSource(pendingDataSourceConfig);
        }

        // Apply QS Config if modified
        if (pendingQSConfig && pendingQSConfig.slug) {
            if (widget instanceof QSWidget) {
                widget.setQSConfig(pendingQSConfig);
            }
        }

        // Apply SimpleTableWidget config if modified
        if (widget instanceof SimpleTableWidget) {
            if (pendingSimpleTableDataConfig) {
                widget.setDataSourceType(
                    pendingSimpleTableDataConfig.dataSourceType,
                );
                if (pendingSimpleTableDataConfig.restConfig) {
                    widget.setRestConfig(
                        pendingSimpleTableDataConfig.restConfig,
                    );
                }
                if (pendingSimpleTableDataConfig.qsConfig) {
                    widget.setQSConfig(pendingSimpleTableDataConfig.qsConfig);
                }
                if (pendingSimpleTableDataConfig.jsonConfig) {
                    widget.setJsonConfig(
                        pendingSimpleTableDataConfig.jsonConfig,
                    );
                }
                // Reload data after config change
                widget.loadData();
            }
            if (pendingSimpleTableSettings) {
                widget.setTableConfig(pendingSimpleTableSettings);
            }
        }

        // Apply TableWidget config if modified
        if (widget instanceof TableWidget) {
            if (pendingTableDataConfig) {
                widget.setDataSourceType(pendingTableDataConfig.dataSourceType);
                if (pendingTableDataConfig.restConfig) {
                    widget.setRestConfig(pendingTableDataConfig.restConfig);
                }
                if (pendingTableDataConfig.qsConfig) {
                    widget.setQSConfig(pendingTableDataConfig.qsConfig);
                }
                if (pendingTableDataConfig.jsonConfig) {
                    widget.setJsonConfig(pendingTableDataConfig.jsonConfig);
                }
                // Reload data after config change
                widget.loadData();
            }
            if (pendingTableSettings) {
                if (pendingTableSettings.gridType) {
                    widget.setGridType(pendingTableSettings.gridType);
                }
                if (pendingTableSettings.gridConfig) {
                    widget.setGridConfig(pendingTableSettings.gridConfig);
                }
            }
        }

        // Apply Content widget config if modified (HTML/Markdown)
        if (pendingContentConfig) {
            if (
                widget instanceof HtmlWidget ||
                widget instanceof MarkdownWidget
            ) {
                widget.content = pendingContentConfig.content;
            }
        }

        // Apply ChartWidget config if modified (charts also use BaseChartWidget)
        if (isChartWidget) {
            if (pendingChartDataConfig) {
                // We need to cast to BaseChartWidget or Access the methods safely
                // Since we know isChartWidget is true, it is safe.
                const chartWidget =
                    widget as unknown as import("../../domain/base-chart-widget.svelte.js").BaseChartWidget;

                chartWidget.setDataSourceType(
                    pendingChartDataConfig.dataSourceType,
                );
                if (pendingChartDataConfig.restConfig) {
                    chartWidget.setRestConfig(
                        pendingChartDataConfig.restConfig,
                    );
                }
                if (pendingChartDataConfig.qsConfig) {
                    chartWidget.setQSConfig(pendingChartDataConfig.qsConfig);
                }
                if (pendingChartDataConfig.jsonConfig) {
                    chartWidget.setJsonConfig(
                        pendingChartDataConfig.jsonConfig,
                    );
                }
                // Reload data after config change
                chartWidget.loadData();
            }

            if (pendingChartSettings) {
                // Cast to BaseChartWidget to access methods
                const chartWidget =
                    widget as unknown as import("../../domain/base-chart-widget.svelte.js").BaseChartWidget;

                chartWidget.setChartConfig(pendingChartSettings);
            }
        }

        if (widget instanceof MapWidget) {
            if (pendingMapDataConfig) {
                widget.setDataSourceType(pendingMapDataConfig.dataSourceType);
                if (pendingMapDataConfig.restConfig) {
                    widget.setRestConfig(pendingMapDataConfig.restConfig);
                }
                if (pendingMapDataConfig.qsConfig) {
                    widget.setQSConfig(pendingMapDataConfig.qsConfig);
                }
                if (pendingMapDataConfig.jsonConfig) {
                    widget.setJsonConfig(pendingMapDataConfig.jsonConfig);
                }
                widget.loadData();
            }

            if (pendingMapSettings) {
                widget.setMapConfig(pendingMapSettings);
            }
        }

        onClose();
    }

    function handleDataSourceConfigChange(config: DataSourceConfig) {
        pendingDataSourceConfig = config;
    }

    function handleQSConfigChange(config: QSDataSourceConfig) {
        pendingQSConfig = config;
    }

    function handleSimpleTableDataChange(
        config: typeof pendingSimpleTableDataConfig,
    ) {
        pendingSimpleTableDataConfig = config;
    }

    function handleSimpleTableSettingsChange(
        config: typeof pendingSimpleTableSettings,
    ) {
        pendingSimpleTableSettings = config;
    }

    function handleTableDataChange(config: typeof pendingTableDataConfig) {
        pendingTableDataConfig = config;
    }

    function handleTableSettingsChange(config: typeof pendingTableSettings) {
        pendingTableSettings = config;
    }

    function handleChartSettingsChange(config: typeof pendingChartSettings) {
        pendingChartSettings = config;
    }

    function handleChartEngineChange(config: { chartEngine: ChartEngine }) {
        pendingChartEngine = config.chartEngine;
    }

    function handleChartDataChange(config: typeof pendingChartDataConfig) {
        pendingChartDataConfig = config;
    }

    function handleChartDataApply() {
        if (isChartWidget && pendingChartDataConfig) {
            const chartWidget =
                widget as unknown as import("../../domain/base-chart-widget.svelte.js").BaseChartWidget;

            chartWidget.setDataSourceType(
                pendingChartDataConfig.dataSourceType,
            );
            if (pendingChartDataConfig.restConfig) {
                chartWidget.setRestConfig(pendingChartDataConfig.restConfig);
            }
            if (pendingChartDataConfig.qsConfig) {
                chartWidget.setQSConfig(pendingChartDataConfig.qsConfig);
            }
            if (pendingChartDataConfig.jsonConfig) {
                chartWidget.setJsonConfig(pendingChartDataConfig.jsonConfig);
            }
            // Reload data immediately
            chartWidget.loadData();
        }
    }

    function handleMapDataChange(config: typeof pendingMapDataConfig) {
        pendingMapDataConfig = config;
    }

    function handleMapSettingsChange(config: typeof pendingMapSettings) {
        pendingMapSettings = config;
    }

    function handleMapDataApply() {
        if (widget instanceof MapWidget && pendingMapDataConfig) {
            widget.setDataSourceType(pendingMapDataConfig.dataSourceType);
            if (pendingMapDataConfig.restConfig) {
                widget.setRestConfig(pendingMapDataConfig.restConfig);
            }
            if (pendingMapDataConfig.qsConfig) {
                widget.setQSConfig(pendingMapDataConfig.qsConfig);
            }
            if (pendingMapDataConfig.jsonConfig) {
                widget.setJsonConfig(pendingMapDataConfig.jsonConfig);
            }
            widget.loadData();
        }
    }

    function handleTableDataApply() {
        if (widget instanceof TableWidget && pendingTableDataConfig) {
            widget.setDataSourceType(pendingTableDataConfig.dataSourceType);
            if (pendingTableDataConfig.restConfig) {
                widget.setRestConfig(pendingTableDataConfig.restConfig);
            }
            if (pendingTableDataConfig.qsConfig) {
                widget.setQSConfig(pendingTableDataConfig.qsConfig);
            }
            if (pendingTableDataConfig.jsonConfig) {
                widget.setJsonConfig(pendingTableDataConfig.jsonConfig);
            }
            widget.loadData();
        }
    }

    function handleSimpleTableDataApply() {
        if (
            widget instanceof SimpleTableWidget &&
            pendingSimpleTableDataConfig
        ) {
            widget.setDataSourceType(
                pendingSimpleTableDataConfig.dataSourceType,
            );
            if (pendingSimpleTableDataConfig.restConfig) {
                widget.setRestConfig(pendingSimpleTableDataConfig.restConfig);
            }
            if (pendingSimpleTableDataConfig.qsConfig) {
                widget.setQSConfig(pendingSimpleTableDataConfig.qsConfig);
            }
            if (pendingSimpleTableDataConfig.jsonConfig) {
                widget.setJsonConfig(pendingSimpleTableDataConfig.jsonConfig);
            }
            widget.loadData();
        }
    }

    function handleContentConfigChange(config: { content: string }) {
        pendingContentConfig = config;
    }

    function handleOverlayClick(e: MouseEvent) {
        if (e.target === e.currentTarget) {
            onClose();
        }
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === "Escape") {
            onClose();
        }
    }

    function handleDialogClick(e: MouseEvent) {
        e.stopPropagation();
    }

    function handleOverlayPointerDown(e: PointerEvent) {
        e.stopPropagation();
    }

    function handleDialogPointerDown(e: PointerEvent) {
        e.stopPropagation();
    }

    $effect(() => {
        const activeCustomTab = customTabs.find(
            (tab) => tab.id === activeTabId,
        );
        if (!activeCustomTab || !renderedTabs.has(activeCustomTab.id)) {
            return;
        }

        activeCustomTab.onShow?.();
        const container = document.querySelector(
            `.tab-content[data-tab-id="${activeCustomTab.id}"]`,
        );
        if (container) {
            activeCustomTab.render(container as HTMLElement, widget);
        }
    });
</script>

<svelte:window onkeydown={handleKeydown} />

<div
    class="modal-overlay"
    onclick={handleOverlayClick}
    onpointerdown={handleOverlayPointerDown}
    role="dialog"
    aria-modal="true"
>
    <div
        class="modal-dialog"
        onclick={handleDialogClick}
        onpointerdown={handleDialogPointerDown}
    >
        <!-- Header -->
        <header class="modal-header">
            <h2 class="modal-title">
                <span class="title-icon">{widget.icon}</span>
                {widget.title} Settings
            </h2>
            <button class="close-btn" type="button" onclick={onClose}>×</button>
        </header>

        <!-- Tab bar -->
        <nav class="tab-bar">
            {#each allTabs as tab (tab.id)}
                <button
                    class="tab-btn"
                    class:active={activeTabId === tab.id}
                    type="button"
                    onclick={() => switchTab(tab.id)}
                >
                    {#if tab.icon}<span class="tab-icon">{@html tab.icon}</span>{/if}
                    {tab.label}
                </button>
            {/each}
        </nav>

        <!-- Content -->
        <div class="modal-content">
            <!-- General Tab -->
            <div class="tab-content" class:active={activeTabId === "general"}>
                <div class="form-group">
                    <label for="widget-title">Title</label>
                    <input id="widget-title" type="text" bind:value={title} />
                </div>

                <div class="form-group">
                    <label for="widget-icon">Icon</label>
                    <input
                        id="widget-icon"
                        type="text"
                        bind:value={icon}
                        class="icon-input"
                    />
                </div>

                <div class="form-row">
                    <div class="form-group">
                        <label for="title-color">Title Color</label>
                        <input
                            id="title-color"
                            type="color"
                            bind:value={titleColor}
                        />
                    </div>
                    <div class="form-group">
                        <label for="title-bg">Header Background</label>
                        <input
                            id="title-bg"
                            type="color"
                            bind:value={titleBackground}
                        />
                    </div>
                </div>

                <div class="form-group checkbox-group">
                    <input
                        id="widget-closable"
                        type="checkbox"
                        bind:checked={closable}
                    />
                    <label for="widget-closable"
                        >Allow closing this widget</label
                    >
                </div>

                <div class="form-group checkbox-group">
                    <input
                        id="widget-chrome"
                        type="checkbox"
                        bind:checked={chromeHidden}
                    />
                    <label for="widget-chrome"
                        >Frameless widget (hide title & status bars)</label
                    >
                </div>

                <div class="form-group checkbox-group nested">
                    <input
                        id="widget-translucent"
                        type="checkbox"
                        bind:checked={translucent}
                        disabled={!chromeHidden}
                    />
                    <label for="widget-translucent"
                        >Semi-transparent background</label
                    >
                </div>
            </div>

            <!-- DataSource Tab -->
            {#if (widget.hasDataSource || isChartWidget || isMapWidget) && !(widget instanceof QSWidget) && !(widget instanceof SimpleTableWidget) && !(widget instanceof TableWidget)}
                <div
                    class="tab-content"
                    class:active={activeTabId === "datasource"}
                >
                    {#if isChartWidget}
                        <ChartDataTab
                            widget={widget as BaseChartWidget}
                            onConfigChange={handleChartDataChange}
                            onApply={handleChartDataApply}
                        />
                    {:else if isMapWidget}
                        <ChartDataTab
                            widget={widget as MapWidget}
                            onConfigChange={handleMapDataChange}
                            onApply={handleMapDataApply}
                        />
                    {:else}
                        <DataSourceConfigTab
                            {widget}
                            onConfigChange={handleDataSourceConfigChange}
                        />
                    {/if}
                </div>
            {/if}

            <!-- Chart Engine Tab -->
            {#if isBasicChart}
                <div
                    class="tab-content"
                    class:active={activeTabId === "chartengine"}
                >
                    <ChartEngineTab
                        widget={widget as BasicChartWidget}
                        onConfigChange={handleChartEngineChange}
                    />
                </div>
            {/if}

            <!-- Chart Settings Tab -->
            {#if isChartWidget}
                <div
                    class="tab-content"
                    class:active={activeTabId === "chartsettings"}
                >
                    <ChartSettingsTab
                        widget={widget as any}
                        onConfigChange={handleChartSettingsChange}
                    />
                </div>
            {/if}

            {#if isMapWidget}
                <div
                    class="tab-content"
                    class:active={activeTabId === "mapsettings"}
                >
                    <MapConfigTab
                        widget={widget as MapWidget}
                        onConfigChange={handleMapSettingsChange}
                    />
                </div>
            {/if}

            <!-- QSDataSource Tab -->
            {#if widget instanceof QSWidget}
                <div
                    class="tab-content"
                    class:active={activeTabId === "datasource"}
                >
                    <QSConfigTab
                        {widget}
                        onConfigChange={handleQSConfigChange}
                    />
                </div>
            {/if}

            <!-- SimpleTableWidget Data Tab -->
            {#if widget instanceof SimpleTableWidget}
                <div
                    class="tab-content"
                    class:active={activeTabId === "datasource"}
                >
                    <ChartDataTab
                        widget={widget as unknown as DataWidgetLike}
                        onConfigChange={handleSimpleTableDataChange}
                        onApply={handleSimpleTableDataApply}
                    />
                </div>
                <div
                    class="tab-content"
                    class:active={activeTabId === "tablesettings"}
                >
                    <SimpleTableSettingsTab
                        {widget}
                        onConfigChange={handleSimpleTableSettingsChange}
                    />
                </div>
            {/if}

            <!-- TableWidget Tabs -->
            {#if widget instanceof TableWidget}
                <div
                    class="tab-content"
                    class:active={activeTabId === "datasource"}
                >
                    <ChartDataTab
                        widget={widget as unknown as DataWidgetLike}
                        onConfigChange={handleTableDataChange}
                        onApply={handleTableDataApply}
                    />
                </div>
                <div
                    class="tab-content"
                    class:active={activeTabId === "tablesettings"}
                >
                    <TableSettingsTab
                        {widget}
                        onConfigChange={handleTableSettingsChange}
                    />
                </div>
            {/if}

            <!-- Content Widget Tab (HTML/Markdown) -->
            {#if isHtmlWidget}
                <div
                    class="tab-content"
                    class:active={activeTabId === "content"}
                >
                    <HtmlEditorTab
                        widget={widget as import("../../domain/html-widget.svelte.js").HtmlWidget}
                        onChange={handleContentConfigChange}
                    />
                </div>

            {/if}

            <!-- Share Tab -->
            {#if activeTabId === "share"}
                <div class="tab-content" class:active={true}>
                    <div class="share-container">
                        <h3>Share Widget</h3>
                        <p class="share-description">
                            Share this widget using the link below. The link will open a standalone view of this widget.
                        </p>
                        
                        {#await SnapshotService.createWidgetSnapshot(widget)}
                             <p>Generating link...</p>
                        {:then snapshotId}
                             {@const generatedUrl = `${window.location.origin}/share/widgets/${snapshotId}`}
                             <div class="share-input-group">
                                <input 
                                    readonly 
                                    value={generatedUrl} 
                                    onclick={(e) => e.currentTarget.select()}
                                    class="share-input"
                                />
                                <button 
                                    class="copy-btn" 
                                    type="button"
                                    onclick={() => {
                                        navigator.clipboard.writeText(generatedUrl);
                                    }}
                                >
                                    Copy Link
                                </button>
                            </div>
                        {/await}
                        
                        <div class="share-note">
                            <small>⚠️ Don't forget to <strong>Save</strong> your changes for the shared link to reflect the latest updates.</small>
                        </div>
                    </div>
                </div>
            {/if}
            {#if isMarkdownWidget}
                <div
                    class="tab-content"
                    class:active={activeTabId === "content"}
                >
                    <MarkdownEditorTab
                        widget={widget as import("../../domain/markdown-widget.svelte.js").MarkdownWidget}
                        onChange={handleContentConfigChange}
                    />
                </div>
            {/if}

            <!-- Custom tabs render here -->
            {#each customTabs as tab (tab.id)}
                {#if renderedTabs.has(tab.id)}
                    <div
                        class="tab-content custom-tab"
                        class:active={activeTabId === tab.id}
                        data-tab-id={tab.id}
                    >
                        <!-- Custom tabs render via DOM manipulation -->
                    </div>
                {/if}
            {/each}
        </div>

        <!-- Footer -->
        <footer class="modal-footer">
            <button class="btn-cancel" type="button" onclick={onClose}
                >Cancel</button
            >
            <button class="btn-save" type="button" onclick={handleSave}
                >Save</button
            >
        </footer>
    </div>
</div>

<style>
    .modal-overlay {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 200000;
        animation: fadeIn 0.15s ease-out;
        pointer-events: auto;
    }

    @keyframes fadeIn {
        from {
            opacity: 0;
        }
        to {
            opacity: 1;
        }
    }

    .modal-dialog {
        background: var(--surface, #fff);
        border-radius: 12px;
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
        width: 500px;
        max-width: 95vw;
        max-height: 90vh;
        display: flex;
        flex-direction: column;
        overflow: hidden;
        animation: slideIn 0.15s ease-out;
    }

    @keyframes slideIn {
        from {
            opacity: 0;
            transform: scale(0.95) translateY(-10px);
        }
        to {
            opacity: 1;
            transform: scale(1) translateY(0);
        }
    }

    .modal-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 20px;
        border-bottom: 1px solid var(--border, #e8eaed);
        background: var(--surface-2, #f8f9fa);
    }

    .modal-title {
        margin: 0;
        font-size: 1.1rem;
        font-weight: 600;
        color: var(--text, #202124);
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .title-icon {
        font-size: 1.2rem;
    }

    .close-btn {
        background: transparent;
        border: none;
        font-size: 1.5rem;
        color: var(--text-2, #5f6368);
        cursor: pointer;
        padding: 0 4px;
    }

    .close-btn:hover {
        color: var(--text, #202124);
    }

    .tab-bar {
        display: flex;
        padding: 0 16px;
        border-bottom: 1px solid var(--border, #e8eaed);
        background: var(--surface-2, #f8f9fa);
    }

    .tab-btn {
        padding: 12px 16px;
        background: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        color: var(--text-2, #5f6368);
        cursor: pointer;
        font-size: 0.9rem;
        display: flex;
        align-items: center;
        gap: 6px;
        transition: all 0.15s;
    }

    .tab-btn:hover {
        color: var(--text, #202124);
    }

    .tab-btn.active {
        color: var(--primary, #1a73e8);
        border-bottom-color: var(--primary, #1a73e8);
        font-weight: 500;
    }

    .tab-icon {
        font-size: 1rem;
    }

    .modal-content {
        flex: 1;
        padding: 24px;
        overflow-y: auto;
    }

    .tab-content {
        display: none;
    }

    .tab-content.active {
        display: block;
    }

    .form-group {
        margin-bottom: 20px;
    }

    .form-group label {
        display: block;
        margin-bottom: 6px;
        font-size: 0.875rem;
        font-weight: 500;
        color: var(--text, #202124);
    }

    .form-group input[type="text"] {
        width: 100%;
        padding: 10px 12px;
        font-size: 0.95rem;
        border: 1px solid var(--border, #dadce0);
        border-radius: 6px;
        background: var(--surface, #fff);
        transition: border-color 0.15s;
    }

    .form-group input[type="text"]:focus {
        outline: none;
        border-color: var(--primary, #1a73e8);
        box-shadow: 0 0 0 3px rgba(26, 115, 232, 0.12);
    }

    .icon-input {
        width: 80px !important;
        text-align: center;
    }

    .form-row {
        display: flex;
        gap: 20px;
    }

    .form-group input[type="color"] {
        width: 50px;
        height: 36px;
        padding: 2px;
        border: 1px solid var(--border, #dadce0);
        border-radius: 4px;
        cursor: pointer;
    }

    .checkbox-group {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .checkbox-group label {
        margin-bottom: 0;
        font-weight: 400;
    }

    .checkbox-group input[type="checkbox"] {
        width: 18px;
        height: 18px;
        cursor: pointer;
    }

    .checkbox-group.nested {
        margin-left: 22px;
        color: var(--text-2, #6b7280);
    }

    .modal-footer {
        display: flex;
        justify-content: flex-end;
        gap: 12px;
        padding: 16px 20px;
        border-top: 1px solid var(--border, #e8eaed);
        background: var(--surface-2, #f8f9fa);
    }

    .btn-cancel,
    .btn-save {
        padding: 10px 20px;
        font-size: 0.9rem;
        font-weight: 500;
        border-radius: 6px;
        cursor: pointer;
        transition: all 0.15s;
    }

    .btn-cancel {
        background: transparent;
        border: 1px solid var(--border, #dadce0);
        color: var(--text-2, #5f6368);
    }

    .btn-cancel:hover {
        background: var(--surface-2, #f8f9fa);
    }

    .btn-save {
        background: var(--primary, #1a73e8);
        border: none;
        color: white;
    }

    .btn-save:hover {
        background: var(--primary-dark, #1557b0);
    }
    .share-container {
        padding: 1rem;
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }
    
    .share-description {
        color: var(--text-2, #5f6368);
        margin: 0;
    }
    
    .share-input-group {
        display: flex;
        gap: 0.5rem;
    }
    
    .share-input {
        flex: 1;
        padding: 8px 12px;
        border: 1px solid var(--border, #dfe1e5);
        border-radius: 4px;
        background: var(--surface-2, #f1f3f4);
        font-family: monospace;
        color: var(--text, #202124);
    }
    
    .copy-btn {
        padding: 8px 16px;
        background: var(--surface, #fff);
        border: 1px solid var(--border, #dfe1e5);
        border-radius: 4px;
        cursor: pointer;
        font-weight: 500;
        color: var(--primary, #1a73e8);
    }
    
    .copy-btn:hover {
        background: var(--primary-light, #e8f0fe);
    }
    
    .share-note {
        /* User Note: Ensure dashboard is saved */
        padding: 0.75rem;
        background: var(--warning-bg, #fef7e0);
        border: 1px solid var(--warning-border, #feebc8);
        border-radius: 4px;
        color: var(--warning-text, #b7791f);
    }
</style>
