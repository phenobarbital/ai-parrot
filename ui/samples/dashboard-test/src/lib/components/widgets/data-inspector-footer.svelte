<script lang="ts">
    import Grid from "gridjs-svelte";
    import "gridjs/dist/theme/mermaid.css";
    import { dashboardContainer } from "../../domain/dashboard-container.svelte.js";

    interface Props {
        data: unknown;
    }
    let { data }: Props = $props();

    let expanded = $state(false);
    let showMenu = $state(false);

    let isArray = $derived(Array.isArray(data));
    let processedData = $derived.by(() => {
        if (!isArray) return [];
        // Deep clone to unwrap Svelte 5 proxies and ensure plain objects
        try {
            return JSON.parse(JSON.stringify(data));
        } catch {
            return [];
        }
    });

    let rowCount = $derived(processedData.length);

    // Auto-detect columns for grid
    let columns = $derived.by(() => {
        if (rowCount === 0) return [];
        const first = processedData[0];
        if (typeof first === "object" && first !== null) {
            return Object.keys(first).map((key) => ({
                id: key,
                name: key,
                // Ensure objects are rendered as strings
                formatter: (cell: unknown) =>
                    typeof cell === "object" && cell !== null
                        ? JSON.stringify(cell)
                        : String(cell),
            }));
        }
        return ["Value"];
    });
</script>

<div class="data-inspector">
    <button class="accordion-btn" onclick={() => (expanded = !expanded)}>
        <span class="icon">{expanded ? "▼" : "▶"}</span>
        <span class="label">Show Data ({rowCount} rows)</span>
    </button>

    {#if expanded}
        <div class="menu-container">
            <button
                class="menu-btn"
                onclick={(e) => {
                    e.stopPropagation();
                    showMenu = !showMenu;
                }}
                title="Create Widget from Data"
            >
                ⚡
            </button>
            {#if showMenu}
                <div class="menu-dropdown">
                    <button
                        onclick={() => {
                            dashboardContainer.createWidgetFromData(
                                "basic-chart",
                                processedData,
                            );
                            showMenu = false;
                        }}
                    >
                        📊 Basic Chart
                    </button>
                    <button
                        onclick={() => {
                            dashboardContainer.createWidgetFromData(
                                "table",
                                processedData,
                            );
                            showMenu = false;
                        }}
                    >
                        ▦ Table
                    </button>
                </div>
            {/if}
        </div>
    {/if}

    {#if expanded}
        <div class="data-content">
            {#if isArray && rowCount > 0}
                <div class="grid-wrapper">
                    <Grid
                        data={processedData}
                        {columns}
                        pagination={{ enabled: true, limit: 5 }}
                        search={true}
                        style={{
                            table: { "font-size": "0.85rem" },
                            th: { padding: "8px" },
                            td: { padding: "8px" },
                        }}
                    />
                </div>
            {:else if isArray && rowCount === 0}
                <div class="empty-msg">No data rows</div>
            {:else}
                <pre class="json-dump">{JSON.stringify(data, null, 2)}</pre>
            {/if}
        </div>
    {/if}
</div>

<style>
    .data-inspector {
        background: var(--surface-2, #f8f9fa);
        border-top: 1px solid var(--border, #e8eaed);
        font-size: 0.9rem;
    }

    .accordion-btn {
        width: 100%;
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 4px 8px;
        background: transparent;
        border: none;
        cursor: pointer;
        color: var(--text-2, #5f6368);
        font-weight: 400;
        font-size: 0.8rem;
        transition: background 0.1s;
        text-align: left;
        position: relative;
    }

    .menu-container {
        position: absolute;
        right: 8px;
        top: 2px;
    }

    .menu-btn {
        background: transparent;
        border: none;
        cursor: pointer;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 0.9rem;
    }

    .menu-btn:hover {
        background: rgba(0, 0, 0, 0.1);
    }

    .menu-dropdown {
        position: absolute;
        right: 0;
        top: 100%;
        background: white;
        border: 1px solid var(--border, #dfe1e5);
        border-radius: 4px;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
        z-index: 100;
        min-width: 140px;
        display: flex;
        flex-direction: column;
        padding: 4px 0;
    }

    .menu-dropdown button {
        background: transparent;
        border: none;
        text-align: left;
        padding: 8px 12px;
        font-size: 0.85rem;
        cursor: pointer;
        color: var(--text, #202124);
    }

    .menu-dropdown button:hover {
        background: var(--surface-2, #f8f9fa);
    }

    .accordion-btn:hover {
        background: rgba(0, 0, 0, 0.05);
        color: var(--text, #202124);
    }

    .icon {
        font-size: 0.8rem;
    }

    .data-content {
        padding: 12px;
        background: var(--surface, #fff);
        overflow-x: auto;
    }

    .json-dump {
        margin: 0;
        font-family: monospace;
        font-size: 0.85rem;
        white-space: pre-wrap;
        color: #444;
    }

    .grid-wrapper {
        font-family: inherit;
    }

    .empty-msg {
        color: var(--text-3, #9aa0a6);
        font-style: italic;
    }
</style>
