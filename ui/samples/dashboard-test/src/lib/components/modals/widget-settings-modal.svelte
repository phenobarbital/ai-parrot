<script lang="ts">
    import type { Widget } from "../../domain/widget.svelte.js";
    import type { ConfigTab } from "../../domain/types.js";
    import type { DataSourceConfig } from "../../domain/data-source.svelte.js";
    import type { QSDataSourceConfig } from "../../domain/qs-datasource.svelte.js";
    import DataSourceConfigTab from "../settings/data-source-config-tab.svelte";
    import QSConfigTab from "../settings/qs-config-tab.svelte";
    import SimpleTableDataTab from "../settings/simple-table-data-tab.svelte";
    import SimpleTableSettingsTab from "../settings/simple-table-settings-tab.svelte";
    import { QSWidget } from "../../domain/qs-widget.svelte.js";
    import {
        SimpleTableWidget,
        type DataSourceType,
        type JsonDataSourceConfig,
        type ColumnConfig,
        type TotalType,
    } from "../../domain/simple-table-widget.svelte.js";

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

    // SimpleTableWidget config state
    let pendingSimpleTableDataConfig = $state<{
        dataSourceType: DataSourceType;
        restConfig?: DataSourceConfig;
        qsConfig?: QSDataSourceConfig;
        jsonConfig?: JsonDataSourceConfig;
    } | null>(null);
    let pendingSimpleTableSettings = $state<{
        zebra?: boolean;
        totals?: TotalType;
        columns?: ColumnConfig[];
    } | null>(null);
    let pendingQSConfig = $state<QSDataSourceConfig | null>(null);

    // Get all tabs (general + datasource if applicable + custom)
    const customTabs = widget.getConfigTabs();
    const isSimpleTable = widget instanceof SimpleTableWidget;
    const allTabs: Array<{ id: string; label: string; icon?: string }> = [
        { id: "general", label: "General", icon: "⚙️" },
        // SimpleTableWidget has its own data & table tabs
        ...(isSimpleTable
            ? [
                  { id: "datasource", label: "Data Source", icon: "🔗" },
                  { id: "tablesettings", label: "Table", icon: "▦" },
              ]
            : widget.hasDataSource
              ? [{ id: "datasource", label: "Data Source", icon: "🔗" }]
              : []),
        ...customTabs.map((t) => ({ id: t.id, label: t.label, icon: t.icon })),
    ];

    function switchTab(tabId: string) {
        activeTabId = tabId;
        if (!renderedTabs.has(tabId)) {
            renderedTabs = new Set([...renderedTabs, tabId]);
        }
    }

    function handleSave() {
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
                    {#if tab.icon}<span class="tab-icon">{tab.icon}</span>{/if}
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
            {#if widget.hasDataSource && !(widget instanceof QSWidget) && !(widget instanceof SimpleTableWidget)}
                <div
                    class="tab-content"
                    class:active={activeTabId === "datasource"}
                >
                    <DataSourceConfigTab
                        {widget}
                        onConfigChange={handleDataSourceConfigChange}
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
                    <SimpleTableDataTab
                        {widget}
                        onConfigChange={handleSimpleTableDataChange}
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
</style>
