<script lang="ts">
    import Grid from "gridjs-svelte";
    import "gridjs/dist/theme/mermaid.css";

    interface Props {
        data: unknown;
    }
    let { data }: Props = $props();

    let expanded = $state(false);

    let isArray = $derived(Array.isArray(data));
    let rowCount = $derived(isArray ? (data as unknown[]).length : 0);

    // Auto-detect columns for grid
    let columns = $derived.by(() => {
        if (!isArray || rowCount === 0) return [];
        const first = (data as unknown[])[0];
        if (typeof first === "object" && first !== null) {
            return Object.keys(first).map((key) => ({ id: key, name: key }));
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
        <div class="data-content">
            {#if isArray && rowCount > 0}
                <div class="grid-wrapper">
                    <Grid
                        {data}
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
