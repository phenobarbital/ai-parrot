<script lang="ts">
    import type {
        SimpleTableWidget,
        DataSourceType,
        JsonDataSourceConfig,
    } from "../../domain/simple-table-widget.svelte.js";
    import type { DataSourceConfig } from "../../domain/data-source.svelte.js";
    import type { QSDataSourceConfig } from "../../domain/qs-datasource.svelte.js";
    import { DEFAULT_QS_URL } from "../../domain/qs-datasource.svelte.js";

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

    // Initialize from widget
    let dataSourceType = $state<DataSourceType>(widget.dataSourceType);

    // REST config
    let restUrl = $state(widget.restConfig?.url ?? "");
    let restMethod = $state(widget.restConfig?.method ?? "GET");

    // QS config
    let qsSlug = $state(widget.qsConfig?.slug ?? "");
    let qsBaseUrl = $state(widget.qsConfig?.baseUrl ?? DEFAULT_QS_URL);
    let qsPayloadJson = $state(
        JSON.stringify(widget.qsConfig?.payload ?? {}, null, 2),
    );

    // JSON config
    let jsonMode = $state<"inline" | "url">(widget.jsonConfig.mode);
    let jsonInline = $state(widget.jsonConfig.json ?? "[]");
    let jsonUrl = $state(widget.jsonConfig.url ?? "");

    // Validation
    let jsonError = $state("");

    function validateJson(json: string): boolean {
        try {
            JSON.parse(json);
            return true;
        } catch {
            return false;
        }
    }

    // Notify parent on changes
    $effect(() => {
        // Validate JSON inputs
        if (dataSourceType === "json" && jsonMode === "inline") {
            if (!validateJson(jsonInline)) {
                jsonError = "Invalid JSON";
                return;
            }
            jsonError = "";
        }

        if (dataSourceType === "qs" && qsPayloadJson) {
            if (!validateJson(qsPayloadJson)) {
                return; // Don't update with invalid JSON
            }
        }

        const config: Parameters<typeof onConfigChange>[0] = {
            dataSourceType,
        };

        if (dataSourceType === "rest" && restUrl) {
            config.restConfig = {
                url: restUrl,
                method: restMethod as "GET" | "POST",
                auth: { type: "jwt-storage", storageKey: "auth_token" },
            };
        }

        if (dataSourceType === "qs" && qsSlug) {
            config.qsConfig = {
                slug: qsSlug,
                baseUrl: qsBaseUrl,
                payload: JSON.parse(qsPayloadJson || "{}"),
            };
        }

        if (dataSourceType === "json") {
            config.jsonConfig = {
                mode: jsonMode,
                json: jsonMode === "inline" ? jsonInline : undefined,
                url: jsonMode === "url" ? jsonUrl : undefined,
            };
        }

        onConfigChange(config);
    });
</script>

<div class="data-tab">
    <!-- Data Source Type Selector -->
    <div class="form-group">
        <label for="ds-type">Data Source Type</label>
        <select id="ds-type" bind:value={dataSourceType}>
            <option value="rest">REST API</option>
            <option value="qs">QuerySource</option>
            <option value="json">JSON Data</option>
        </select>
    </div>

    <!-- REST Configuration -->
    {#if dataSourceType === "rest"}
        <div class="config-section">
            <h4>REST API Configuration</h4>
            <div class="form-group">
                <label for="rest-url">URL <span class="required">*</span></label
                >
                <input
                    id="rest-url"
                    type="url"
                    bind:value={restUrl}
                    placeholder="https://api.example.com/data"
                />
            </div>
            <div class="form-group">
                <label for="rest-method">Method</label>
                <select id="rest-method" bind:value={restMethod}>
                    <option value="GET">GET</option>
                    <option value="POST">POST</option>
                </select>
            </div>
        </div>
    {/if}

    <!-- QuerySource Configuration -->
    {#if dataSourceType === "qs"}
        <div class="config-section">
            <h4>QuerySource Configuration</h4>
            <div class="form-group">
                <label for="qs-slug">Slug <span class="required">*</span></label
                >
                <input
                    id="qs-slug"
                    type="text"
                    bind:value={qsSlug}
                    placeholder="e.g. hisense_stores"
                />
            </div>

            <!-- Advanced: Base URL -->
            <div class="advanced-section">
                <button
                    type="button"
                    class="advanced-toggle"
                    onclick={() => {
                        const el = document.getElementById("qs-advanced");
                        if (el) el.classList.toggle("hidden");
                    }}
                >
                    <span>Advanced Options</span>
                    <span class="toggle-icon">▼</span>
                </button>
                <div id="qs-advanced" class="advanced-content hidden">
                    <div class="form-group">
                        <label for="qs-base">API URL</label>
                        <input
                            id="qs-base"
                            type="url"
                            bind:value={qsBaseUrl}
                            placeholder={DEFAULT_QS_URL}
                        />
                    </div>
                    <div class="form-group">
                        <label for="qs-payload">Payload (JSON)</label>
                        <textarea
                            id="qs-payload"
                            bind:value={qsPayloadJson}
                            rows="3"
                        ></textarea>
                    </div>
                </div>
            </div>
        </div>
    {/if}

    <!-- JSON Configuration -->
    {#if dataSourceType === "json"}
        <div class="config-section">
            <h4>JSON Data Configuration</h4>
            <div class="form-group">
                <label for="json-mode">Mode</label>
                <select id="json-mode" bind:value={jsonMode}>
                    <option value="inline">Inline JSON</option>
                    <option value="url">Load from URL</option>
                </select>
            </div>

            {#if jsonMode === "inline"}
                <div class="form-group">
                    <label for="json-data"
                        >JSON Data <span class="required">*</span></label
                    >
                    <textarea
                        id="json-data"
                        bind:value={jsonInline}
                        class:has-error={!!jsonError}
                        rows="8"
                        placeholder={'[{"name": "John", "amount": 100}]'}
                    ></textarea>
                    {#if jsonError}
                        <span class="error-msg">{jsonError}</span>
                    {/if}
                </div>
            {:else}
                <div class="form-group">
                    <label for="json-url"
                        >JSON URL <span class="required">*</span></label
                    >
                    <input
                        id="json-url"
                        type="url"
                        bind:value={jsonUrl}
                        placeholder="https://example.com/data.json"
                    />
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
    .data-tab {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    .form-group {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    label {
        font-size: 0.875rem;
        font-weight: 500;
        color: var(--text, #202124);
    }

    .required {
        color: var(--danger, #dc3545);
    }

    select,
    input,
    textarea {
        padding: 10px 12px;
        font-size: 0.95rem;
        border: 1px solid var(--border, #dadce0);
        border-radius: 6px;
        background: var(--surface, #fff);
        font-family: inherit;
    }

    textarea {
        font-family: monospace;
        font-size: 0.9rem;
        resize: vertical;
    }

    select:focus,
    input:focus,
    textarea:focus {
        outline: none;
        border-color: var(--primary, #1a73e8);
        box-shadow: 0 0 0 3px rgba(26, 115, 232, 0.12);
    }

    .config-section {
        padding: 12px;
        background: var(--surface-2, #f8f9fa);
        border-radius: 8px;
        border: 1px solid var(--border, #e8eaed);
    }

    .config-section h4 {
        margin: 0 0 12px 0;
        font-size: 0.9rem;
        color: var(--text-2, #5f6368);
    }

    .has-error {
        border-color: var(--danger, #dc3545);
    }

    .error-msg {
        font-size: 0.8rem;
        color: var(--danger, #dc3545);
    }

    .advanced-section {
        border: 1px solid var(--border, #dfe1e5);
        border-radius: 8px;
        overflow: hidden;
        background: var(--surface, #fff);
        margin-top: 12px;
    }

    .advanced-toggle {
        width: 100%;
        background: var(--surface-2, #f8f9fa);
        border: none;
        padding: 10px 14px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        color: var(--text, #202124);
        font-size: 0.85rem;
        font-weight: 500;
        cursor: pointer;
    }

    .advanced-content {
        padding: 12px;
        border-top: 1px solid var(--border, #dfe1e5);
    }

    .advanced-content.hidden {
        display: none;
    }

    .toggle-icon {
        font-size: 0.75rem;
        color: var(--text-3, #9aa0a6);
    }
</style>
