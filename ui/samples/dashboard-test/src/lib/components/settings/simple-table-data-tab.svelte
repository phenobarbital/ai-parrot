<script lang="ts">
    import type { DataSourceConfig } from "../../domain/data-source.svelte.js";
    import type { QSDataSourceConfig } from "../../domain/qs-datasource.svelte.js";
    import type {
        SimpleTableWidget,
        DataSourceType,
        JsonDataSourceConfig,
    } from "../../domain/simple-table-widget.svelte.js";

    interface Props {
        widget: SimpleTableWidget;
        onConfigChange: (config: {
            dataSourceType: DataSourceType;
            restConfig?: DataSourceConfig;
            qsConfig?: QSDataSourceConfig;
            jsonConfig?: JsonDataSourceConfig;
        }) => void;
    }

    let { widget, onConfigChange }: Props = $props();

    let dataSourceType = $state<DataSourceType>(widget.dataSourceType);
    let restUrl = $state(widget.restConfig?.url ?? "");
    let restMethod = $state(widget.restConfig?.method ?? "GET");
    let qsSlug = $state(widget.qsConfig?.slug ?? "");
    let qsBaseUrl = $state(widget.qsConfig?.baseUrl ?? "");
    let jsonMode = $state<JsonDataSourceConfig["mode"]>(
        widget.jsonConfig?.mode ?? "inline",
    );
    let jsonInline = $state(widget.jsonConfig?.json ?? "[]");
    let jsonUrl = $state(widget.jsonConfig?.url ?? "");

    $effect(() => {
        onConfigChange({
            dataSourceType,
            restConfig:
                dataSourceType === "rest"
                    ? { url: restUrl, method: restMethod }
                    : undefined,
            qsConfig:
                dataSourceType === "qs"
                    ? {
                          slug: qsSlug,
                          baseUrl: qsBaseUrl || undefined,
                      }
                    : undefined,
            jsonConfig:
                dataSourceType === "json"
                    ? {
                          mode: jsonMode,
                          json: jsonMode === "inline" ? jsonInline : undefined,
                          url: jsonMode === "url" ? jsonUrl : undefined,
                      }
                    : undefined,
        });
    });
</script>

<div class="tab-section">
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
            <input id="rest-url" type="text" bind:value={restUrl} />
        </div>
        <div class="form-group">
            <label for="rest-method">Method</label>
            <select id="rest-method" bind:value={restMethod}>
                <option value="GET">GET</option>
                <option value="POST">POST</option>
                <option value="PUT">PUT</option>
                <option value="PATCH">PATCH</option>
                <option value="DELETE">DELETE</option>
            </select>
        </div>
    {:else if dataSourceType === "qs"}
        <div class="form-group">
            <label for="qs-slug">Query slug</label>
            <input id="qs-slug" type="text" bind:value={qsSlug} />
        </div>
        <div class="form-group">
            <label for="qs-base-url">Base URL</label>
            <input id="qs-base-url" type="text" bind:value={qsBaseUrl} />
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
                <label for="json-inline">JSON Data</label>
                <textarea
                    id="json-inline"
                    rows="6"
                    bind:value={jsonInline}
                ></textarea>
            </div>
        {:else}
            <div class="form-group">
                <label for="json-url">JSON URL</label>
                <input id="json-url" type="text" bind:value={jsonUrl} />
            </div>
        {/if}
    {/if}
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
    select,
    textarea {
        width: 100%;
        padding: 8px 10px;
        border: 1px solid var(--border, #dadce0);
        border-radius: 6px;
        font-size: 0.9rem;
    }

    textarea {
        font-family: monospace;
    }
</style>
