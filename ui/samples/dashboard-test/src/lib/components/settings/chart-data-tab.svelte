<script lang="ts">
    import type { DataSourceConfig } from "../../domain/data-source.svelte.js";
    import type { QSDataSourceConfig } from "../../domain/qs-datasource.svelte.js";

    type DataSourceType = "rest" | "qs" | "json";
    type JsonConfig = { mode: "inline" | "url"; json?: string; url?: string };

    interface SupportsDataSource {
        dataSourceType: DataSourceType;
        restConfig: DataSourceConfig | null;
        qsConfig: QSDataSourceConfig | null;
        jsonConfig: JsonConfig;
    }

    interface Props {
        widget: SupportsDataSource;
        onConfigChange: (config: {
            dataSourceType: DataSourceType;
            restConfig?: DataSourceConfig;
            qsConfig?: QSDataSourceConfig;
            jsonConfig?: JsonConfig;
        }) => void;
        onApply?: () => void;
    }

    let { widget, onConfigChange, onApply }: Props = $props();

    let dataSourceType = $state<DataSourceType>(
        widget.dataSourceType ?? "json",
    );
    let restUrl = $state(widget.restConfig?.url ?? "");
    let restMethod = $state(widget.restConfig?.method ?? "GET");

    let qsSlug = $state(widget.qsConfig?.slug ?? "");
    let qsBaseUrl = $state(widget.qsConfig?.baseUrl ?? "");

    let jsonMode = $state<JsonConfig["mode"]>(
        widget.jsonConfig?.mode ?? "inline",
    );
    let jsonInline = $state(widget.jsonConfig?.json ?? "[]");
    let jsonUrl = $state(widget.jsonConfig?.url ?? "");

    $effect(() => {
        const config = {
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
        };

        onConfigChange(config);
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

    {#if onApply}
        <button class="btn-apply" type="button" onclick={onApply}>
            Apply Data
        </button>
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

    .btn-apply {
        align-self: flex-start;
        padding: 8px 14px;
        border-radius: 6px;
        border: none;
        background: var(--primary, #1a73e8);
        color: white;
        cursor: pointer;
    }
    .btn-apply:hover {
        background: var(--primary-dark, #1557b0);
    }
</style>
