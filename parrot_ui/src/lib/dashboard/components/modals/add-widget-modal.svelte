<script lang="ts">
    import type { DashboardTab } from "../../domain/dashboard-tab.svelte.js";
    import type { WidgetType } from "../../domain/types.js";

    interface Props {
        tab: DashboardTab;
        onClose: () => void;
        onAddWidget: (
            widgetType: WidgetType,
            name: string,
            config?: { url?: string },
        ) => void;
    }

    let { tab, onClose, onAddWidget }: Props = $props();

    let widgetName = $state("New Widget");
    let selectedType = $state<WidgetType | null>(null);
    let url = $state("");

    // Check if the selected widget type needs a URL
    let needsUrl = $derived(
        selectedType?.id === "iframe" ||
            selectedType?.id === "image" ||
            selectedType?.id === "youtube" ||
            selectedType?.id === "vimeo" ||
            selectedType?.id === "video" ||
            selectedType?.id === "pdf",
    );

    // Available widget types - extensible
    const widgetTypes: WidgetType[] = [
        {
            id: "blank",
            name: "Blank Widget",
            description: "Empty widget container",
            icon: "📦",
        },
        {
            id: "iframe",
            name: "IFrame Widget",
            description: "Embed external websites",
            icon: "🌐",
        },
        {
            id: "image",
            name: "Image Widget",
            description: "Display an image from URL",
            icon: "🖼️",
        },
        {
            id: "youtube",
            name: "YouTube Widget",
            description: "Embed YouTube video",
            icon: "📺",
        },
        {
            id: "vimeo",
            name: "Vimeo Widget",
            description: "Embed Vimeo video",
            icon: "🎬",
        },
        {
            id: "echarts",
            name: "ECharts",
            description: "Powerful Apache ECharts",
            icon: "📈",
        },
        {
            id: "basicchart",
            name: "Basic Chart",
            description: "Pick Carbon, ECharts, Vega, or Frappe renderers",
            icon: "📊",
        },
        {
            id: "vega",
            name: "Vega Chart",
            description: "Vega-Lite visualization",
            icon: "📊",
        },
        {
            id: "frappe",
            name: "Frappe Chart",
            description: "GitHub-style simple charts",
            icon: "📉",
        },
        {
            id: "carbon",
            name: "Carbon Chart",
            description: "IBM Carbon Design charts",
            icon: "📊",
        },
        {
            id: "layerchart",
            name: "Layer Chart",
            description: "Svelte LayerChart visualization",
            icon: "📈",
        },
        {
            id: "map",
            name: "Map",
            description: "Leaflet-based map widget",
            icon: "🗺️",
        },
        {
            id: "text",
            name: "Text Widget",
            description: "Rich text content",
            icon: "📝",
        },
        {
            id: "clock",
            name: "Clock Widget",
            description: "Display current time",
            icon: "🕐",
        },
        {
            id: "data",
            name: "Data Widget",
            description: "Load data from REST API",
            icon: "📡",
        },
        {
            id: "querysource",
            name: "QuerySource Widget",
            description: "Query data from QuerySource",
            icon: "⚡",
        },
        {
            id: "simpletable",
            name: "Simple Table",
            description: "Table with zebra rows, masks, and totals",
            icon: "▦",
        },
        {
            id: "table",
            name: "Table",
            description: "Advanced table with multiple grid options",
            icon: "📊",
        },
        {
            id: "video",
            name: "Video Widget",
            description: "Play video from URL",
            icon: "🎥",
        },
        {
            id: "pdf",
            name: "PDF Viewer",
            description: "Display PDF documents",
            icon: "📄",
        },
        {
            id: "html",
            name: "HTML Widget",
            description: "Custom HTML content",
            icon: "📰",
        },
        {
            id: "markdown",
            name: "Markdown Widget",
            description: "Markdown formatted content",
            icon: "📝",
        },
    ];

    function handleSubmit() {
        if (selectedType) {
            const config = needsUrl ? { url } : undefined;
            onAddWidget(selectedType, widgetName, config);
            onClose();
        }
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === "Escape") onClose();
    }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
    class="modal-overlay"
    role="dialog"
    aria-modal="true"
    onclick={onClose}
    onkeydown={handleKeydown}
>
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="modal" onclick={(e) => e.stopPropagation()}>
        <div class="modal-header">
            <h2 class="modal-title">Add a Runtime Widget</h2>
            <button type="button" class="close-btn" onclick={onClose}>×</button>
        </div>

        <div class="modal-body">
            <div class="name-row">
                <label for="widget-name">Widget Name:</label>
                <input
                    id="widget-name"
                    type="text"
                    class="name-input"
                    bind:value={widgetName}
                />
            </div>

            {#if needsUrl}
                <div class="name-row">
                    <label for="widget-url">URL:</label>
                    <input
                        id="widget-url"
                        type="text"
                        class="name-input"
                        placeholder="https://example.com"
                        bind:value={url}
                    />
                </div>
            {/if}

            <div class="widget-grid">
                {#each widgetTypes as wtype (wtype.id)}
                    <!-- svelte-ignore a11y_click_events_have_key_events -->
                    <div
                        class="widget-card"
                        class:selected={selectedType?.id === wtype.id}
                        onclick={() => (selectedType = wtype)}
                        role="button"
                        tabindex="0"
                    >
                        <span class="widget-icon">{wtype.icon}</span>
                        <span class="widget-name">{wtype.name}</span>
                        <span class="widget-desc">{wtype.description}</span>
                    </div>
                {/each}
            </div>
        </div>

        <div class="modal-footer">
            <button type="button" class="btn btn-secondary" onclick={onClose}>
                Cancel
            </button>
            <button
                type="button"
                class="btn btn-primary"
                onclick={handleSubmit}
                disabled={!selectedType}
            >
                Add Widget
            </button>
        </div>
    </div>
</div>

<style>
    .modal-overlay {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.4);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
    }

    .modal {
        background: var(--surface, #fff);
        border-radius: 12px;
        width: 600px;
        max-width: 90vw;
        max-height: 85vh;
        display: flex;
        flex-direction: column;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
    }

    .modal-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 20px 24px;
        border-bottom: 1px solid var(--border, #e8eaed);
    }

    .modal-title {
        margin: 0;
        font-size: 1.25rem;
        font-weight: 600;
        color: var(--text, #202124);
    }

    .close-btn {
        width: 32px;
        height: 32px;
        border-radius: 50%;
        border: none;
        background: transparent;
        font-size: 1.5rem;
        color: var(--text-2, #5f6368);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .close-btn:hover {
        background: var(--surface-2, #f1f3f4);
    }

    .modal-body {
        padding: 20px 24px;
        overflow-y: auto;
        flex: 1;
    }

    .name-row {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 20px;
    }

    .name-row label {
        font-size: 0.9rem;
        font-weight: 500;
        color: var(--text-2, #5f6368);
        white-space: nowrap;
    }

    .name-input {
        flex: 1;
        padding: 10px 14px;
        border: 2px solid var(--primary, #1a73e8);
        border-radius: 6px;
        font-size: 0.95rem;
        outline: none;
        background: var(--primary-light, #e8f0fe);
        color: var(--primary, #1a73e8);
    }

    .widget-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 12px;
    }

    .widget-card {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 6px;
        padding: 16px 12px;
        border: 2px solid var(--border, #e8eaed);
        border-radius: 10px;
        cursor: pointer;
        transition:
            border-color 0.15s,
            background 0.15s;
        text-align: center;
    }

    .widget-card:hover {
        background: var(--surface-2, #f8f9fa);
        border-color: var(--border-hover, #dadce0);
    }

    .widget-card.selected {
        border-color: var(--primary, #1a73e8);
        background: var(--primary-light, #e8f0fe);
    }

    .widget-icon {
        font-size: 2rem;
        margin-bottom: 4px;
    }

    .widget-name {
        font-size: 0.9rem;
        font-weight: 500;
        color: var(--text, #202124);
    }

    .widget-desc {
        font-size: 0.75rem;
        color: var(--text-3, #9aa0a6);
    }

    .modal-footer {
        display: flex;
        justify-content: flex-end;
        gap: 12px;
        padding: 16px 24px;
        border-top: 1px solid var(--border, #e8eaed);
    }

    .btn {
        padding: 10px 20px;
        border-radius: 6px;
        font-size: 0.9rem;
        font-weight: 500;
        cursor: pointer;
        border: none;
        transition:
            background 0.15s,
            opacity 0.15s;
    }

    .btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .btn-secondary {
        background: transparent;
        color: var(--text-2, #5f6368);
    }
    .btn-secondary:hover:not(:disabled) {
        background: var(--surface-2, #f1f3f4);
    }

    .btn-primary {
        background: var(--primary, #1a73e8);
        color: white;
    }
    .btn-primary:hover:not(:disabled) {
        background: var(--primary-dark, #1557b0);
    }
</style>
