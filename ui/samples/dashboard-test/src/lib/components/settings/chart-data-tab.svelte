<script lang="ts">
    import type { BaseChartWidget } from "../../domain/base-chart-widget.svelte.js";
    import type { DataSourceConfig } from "../../domain/data-source.svelte.js";
    import type { QSDataSourceConfig } from "../../domain/qs-datasource.svelte.js";

    interface Props {
        widget: BaseChartWidget;
        onConfigChange: (config: {
            dataSourceType: "rest" | "qs" | "json";
            restConfig?: DataSourceConfig;
            qsConfig?: QSDataSourceConfig;
            jsonConfig?: { mode: "inline" | "url"; json?: string; url?: string };
        }) => void;
        onApply: () => void;
    }

    let { widget, onConfigChange, onApply }: Props = $props();

    let dataSourceType = $state<"rest" | "qs" | "json">(
        widget.dataSourceType,
    );
    let restUrl = $state(widget.restConfig?.url ?? "");
    let qsSlug = $state(widget.qsConfig?.slug ?? "");
    let qsBaseUrl = $state(widget.qsConfig?.baseUrl ?? "");
    let jsonMode = $state<"inline" | "url">(
        widget.jsonConfig?.mode ?? "inline",
    );
    let jsonText = $state(widget.jsonConfig?.json ?? "[]");
    let jsonUrl = $state(widget.jsonConfig?.url ?? "");

    $effect(() => {
        const restConfig = restUrl.trim()
            ? ({ url: restUrl.trim() } as DataSourceConfig)
            : undefined;
        const qsConfig = qsSlug.trim()
            ? ({
                  slug: qsSlug.trim(),
                  baseUrl: qsBaseUrl.trim() || undefined,
              } as QSDataSourceConfig)
            : undefined;

        const jsonConfig = {
            mode: jsonMode,
            json: jsonMode === "inline" ? jsonText : undefined,
            url: jsonMode === "url" ? jsonUrl.trim() : undefined,
        };

        onConfigChange({
            dataSourceType,
            restConfig,
            qsConfig,
            jsonConfig,
        });
    });
</script>

<div class="chart-data">
    <div class="form-group">
        <label for="data-source-type">Data Source</label>
        <select id="data-source-type" bind:value={dataSourceType}>
            <option value="json">JSON</option>
            <option value="rest">REST API</option>
            <option value="qs">QuerySource</option>
        </select>
    </div>

    {#if dataSourceType === "rest"}
        <div class="form-group">
            <label for="rest-url">REST URL</label>
            <input
                id="rest-url"
                type="url"
                placeholder="https://api.example.com/data"
                bind:value={restUrl}
            />
        </div>
    {:else if dataSourceType === "qs"}
        <div class="form-row">
            <div class="form-group">
                <label for="qs-slug">QuerySource Slug</label>
                <input
                    id="qs-slug"
                    type="text"
                    placeholder="sales-summary"
                    bind:value={qsSlug}
                />
            </div>
            <div class="form-group">
                <label for="qs-base-url">QuerySource Base URL</label>
                <input
                    id="qs-base-url"
                    type="url"
                    placeholder="http://localhost:5000"
                    bind:value={qsBaseUrl}
                />
            </div>
        </div>
    {:else}
        <div class="form-group">
            <label for="json-mode">JSON Mode</label>
            <select id="json-mode" bind:value={jsonMode}>
                <option value="inline">Inline JSON</option>
                <option value="url">JSON URL</option>
            </select>
        </div>

        {#if jsonMode === "inline"}
            <div class="form-group">
                <label for="json-inline">JSON Array</label>
                <textarea
                    id="json-inline"
                    rows="6"
                    bind:value={jsonText}
                    placeholder='[{"label":"A","value":10}]'
                ></textarea>
            </div>
        {:else}
            <div class="form-group">
                <label for="json-url">JSON URL</label>
                <input
                    id="json-url"
                    type="url"
                    placeholder="https://example.com/data.json"
                    bind:value={jsonUrl}
                />
            </div>
        {/if}
    {/if}

    <div class="actions">
        <button type="button" class="btn-apply" onclick={onApply}>
            Apply Data
        </button>
    </div>
</div>

<style>
    .chart-data {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    .form-row {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 12px;
    }

    .form-group {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .form-group label {
        font-size: 0.85rem;
        font-weight: 600;
    }

    .form-group input,
    .form-group select,
    .form-group textarea {
        padding: 8px 10px;
        border-radius: 6px;
        border: 1px solid var(--border, #444);
        background: var(--surface-2, #1f1f1f);
        color: inherit;
    }

    .actions {
        display: flex;
        justify-content: flex-end;
    }

    .btn-apply {
        background: var(--primary, #1a73e8);
        color: #fff;
        border: none;
        padding: 8px 14px;
        border-radius: 6px;
    }
</style>
