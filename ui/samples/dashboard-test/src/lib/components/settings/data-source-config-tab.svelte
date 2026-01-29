<script lang="ts">
    import type { Widget } from "../../domain/widget.svelte.js";
    import type { DataSourceConfig } from "../../domain/data-source.svelte.js";

    interface Props {
        widget: Widget;
        onConfigChange: (config: DataSourceConfig) => void;
    }

    let { widget, onConfigChange }: Props = $props();

    let url = $state(widget.config.dataSource?.url ?? "");
    let method = $state(widget.config.dataSource?.method ?? "GET");
    let pollInterval = $state(
        widget.config.dataSource?.pollInterval?.toString() ?? "",
    );

    $effect(() => {
        onConfigChange({
            url,
            method,
            pollInterval: pollInterval ? Number(pollInterval) : undefined,
        });
    });
</script>

<div class="tab-section">
    <div class="form-group">
        <label for="ds-url">Data Source URL</label>
        <input id="ds-url" type="text" bind:value={url} />
    </div>

    <div class="form-group">
        <label for="ds-method">HTTP Method</label>
        <select id="ds-method" bind:value={method}>
            <option value="GET">GET</option>
            <option value="POST">POST</option>
            <option value="PUT">PUT</option>
            <option value="PATCH">PATCH</option>
            <option value="DELETE">DELETE</option>
        </select>
    </div>

    <div class="form-group">
        <label for="ds-poll">Poll Interval (ms)</label>
        <input id="ds-poll" type="number" bind:value={pollInterval} />
    </div>
</div>

<style>
    .tab-section {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .form-group label {
        display: block;
        margin-bottom: 6px;
        font-size: 0.875rem;
        font-weight: 500;
    }

    input,
    select {
        width: 100%;
        padding: 8px 10px;
        border: 1px solid var(--border, #dadce0);
        border-radius: 6px;
        font-size: 0.9rem;
    }
</style>
