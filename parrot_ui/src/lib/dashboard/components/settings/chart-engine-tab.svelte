<script lang="ts">
    import type {
        BasicChartWidget,
        ChartEngine,
    } from "../../domain/basic-chart-widget.svelte.js";

    interface Props {
        widget: BasicChartWidget;
        onConfigChange: (config: { chartEngine: ChartEngine }) => void;
    }

    let { widget, onConfigChange }: Props = $props();

    let chartEngine = $state<ChartEngine>(widget.chartEngine);

    $effect(() => {
        onConfigChange({ chartEngine });
    });
</script>

<div class="settings-tab">
    <div class="form-group">
        <label for="chart-engine">Chart Engine</label>
        <select id="chart-engine" bind:value={chartEngine}>
            <option value="carbon">Carbon Charts</option>
            <option value="echarts">ECharts</option>
            <option value="vega">Vega-Lite</option>
            <option value="frappe">Frappe Charts</option>
        </select>
        <p class="hint">
            Choose the renderer for this widget (affects styling and features).
        </p>
    </div>
</div>

<style>
    .settings-tab {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    .form-group {
        display: flex;
        flex-direction: column;
        gap: 6px;
        flex: 1;
    }

    label {
        font-size: 0.875rem;
        font-weight: 500;
        color: var(--text, #202124);
    }

    select {
        padding: 10px 12px;
        font-size: 0.95rem;
        border: 1px solid var(--border, #dadce0);
        border-radius: 6px;
        background: var(--surface, #fff);
        width: 100%;
    }

    select:focus {
        outline: none;
        border-color: var(--primary, #1a73e8);
        box-shadow: 0 0 0 3px rgba(26, 115, 232, 0.12);
    }

    .hint {
        margin: 0;
        font-size: 0.8rem;
        color: var(--text-3, #9aa0a6);
        font-style: italic;
    }
</style>
