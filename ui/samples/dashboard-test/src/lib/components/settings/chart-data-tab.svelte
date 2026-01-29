<script lang="ts">
    import type { DataSourceConfig } from "../../domain/data-source.svelte.js";
    import type { QSDataSourceConfig } from "../../domain/qs-datasource.svelte.js";
    import { DEFAULT_QS_URL } from "../../domain/qs-datasource.svelte.js";

    // Generic interface for widgets that support data sources (Charts & Tables)
    export interface DataWidgetLike {
        dataSourceType: "rest" | "qs" | "json";
        restConfig?: DataSourceConfig | null;
        qsConfig?: QSDataSourceConfig | null;
        jsonConfig?: {
            mode: "inline" | "url";
            json?: string;
            url?: string;
        };
    }

    interface Props {
        widget: DataWidgetLike;
        onConfigChange: (config: {
            dataSourceType: "rest" | "qs" | "json";
            restConfig?: DataSourceConfig;
            qsConfig?: QSDataSourceConfig;
            jsonConfig?: {
                mode: "inline" | "url";
                json?: string;
                url?: string;
            };
        }) => void;
        onApply?: () => void;
    }

    let { widget, onConfigChange, onApply }: Props = $props();

    // Initialize from widget
    let dataSourceType = $state<"rest" | "qs" | "json">(widget.dataSourceType);

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
    // Ensure jsonConfig exists on widget before accessing
    let jsonConfig = widget.jsonConfig || { mode: "inline", json: "[]" };
    let jsonMode = $state<"inline" | "url">(jsonConfig.mode);
    let jsonInline = $state(jsonConfig.json ?? "[]");
    let jsonUrl = $state(jsonConfig.url ?? "");

    // Validation
    let jsonError = $state("");

    // Test connection status
    let restTestStatus = $state<"idle" | "testing" | "success" | "error">(
        "idle",
    );
    let qsTestStatus = $state<"idle" | "testing" | "success" | "error">("idle");
    let restTestError = $state("");
    let qsTestError = $state("");

    async function testRestConnection() {
        if (!restUrl) {
            restTestError = "URL is required";
            restTestStatus = "error";
            return;
        }
        restTestStatus = "testing";
        restTestError = "";
        try {
            const response = await fetch(restUrl, {
                method: restMethod,
                headers: { Accept: "application/json" },
            });
            if (response.ok) {
                restTestStatus = "success";
            } else {
                restTestStatus = "error";
                restTestError = `HTTP ${response.status}`;
            }
        } catch (e) {
            restTestStatus = "error";
            restTestError =
                e instanceof Error ? e.message : "Connection failed";
        }
    }

    async function testQsConnection() {
        if (!qsSlug) {
            qsTestError = "Slug is required";
            qsTestStatus = "error";
            return;
        }
        qsTestStatus = "testing";
        qsTestError = "";
        try {
            const payload = JSON.parse(qsPayloadJson || "{}");
            const response = await fetch(
                `${qsBaseUrl}/api/v1/querysource/${qsSlug}`,
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        Accept: "application/json",
                    },
                    body: JSON.stringify(payload),
                },
            );
            if (response.ok) {
                qsTestStatus = "success";
            } else {
                qsTestStatus = "error";
                qsTestError = `HTTP ${response.status}`;
            }
        } catch (e) {
            qsTestStatus = "error";
            qsTestError = e instanceof Error ? e.message : "Connection failed";
        }
    }

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

            <div class="button-group">
                <button
                    type="button"
                    class="control-btn test"
                    onclick={testRestConnection}
                    disabled={restTestStatus === "testing"}
                >
                    {#if restTestStatus === "testing"}
                        ⏳ Testing...
                    {:else}
                        🔗 Test
                    {/if}
                </button>
                <button
                    type="button"
                    class="control-btn apply"
                    onclick={() => onApply?.()}
                >
                    Apply
                </button>
                {#if restTestStatus === "success"}
                    <span class="status-indicator success">● Connected</span>
                {:else if restTestStatus === "error"}
                    <span class="status-indicator error"
                        >● {restTestError || "Failed"}</span
                    >
                {/if}
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

            <div class="button-group">
                <button
                    type="button"
                    class="control-btn test"
                    onclick={testQsConnection}
                    disabled={qsTestStatus === "testing"}
                >
                    {#if qsTestStatus === "testing"}
                        ⏳ Testing...
                    {:else}
                        🔗 Test
                    {/if}
                </button>
                <button
                    type="button"
                    class="control-btn apply"
                    onclick={() => onApply?.()}
                >
                    Apply
                </button>
                {#if qsTestStatus === "success"}
                    <span class="status-indicator success">● Connected</span>
                {:else if qsTestStatus === "error"}
                    <span class="status-indicator error"
                        >● {qsTestError || "Failed"}</span
                    >
                {/if}
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

                    <div class="json-controls">
                        <button
                            type="button"
                            class="control-btn validate"
                            onclick={() => {
                                if (validateJson(jsonInline)) {
                                    alert("Valid JSON");
                                } else {
                                    alert("Invalid JSON");
                                }
                            }}
                        >
                            ✓ Validate
                        </button>
                        <button
                            type="button"
                            class="control-btn"
                            onclick={() => {
                                try {
                                    const parsed = JSON.parse(jsonInline);
                                    jsonInline = JSON.stringify(
                                        parsed,
                                        null,
                                        2,
                                    );
                                } catch (e) {
                                    alert("Invalid JSON, cannot prettify");
                                }
                            }}
                        >
                            Prettify
                        </button>
                        <button
                            type="button"
                            class="control-btn apply"
                            onclick={() => onApply?.()}
                        >
                            Apply
                        </button>
                    </div>

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

    .json-controls {
        display: flex;
        gap: 8px;
        margin-top: 8px;
    }

    .control-btn {
        padding: 6px 12px;
        font-size: 0.85rem;
        border: 1px solid var(--border, #dadce0);
        border-radius: 4px;
        background: var(--surface, #fff);
        cursor: pointer;
        color: var(--text, #202124);
        transition: all 0.15s;
    }

    .control-btn:hover {
        background: var(--surface-2, #f1f3f4);
        border-color: var(--text-3, #9aa0a6);
    }

    .control-btn.validate {
        color: var(--primary, #1a73e8);
        border-color: var(--primary, #1a73e8);
        background: rgba(26, 115, 232, 0.05);
    }

    .control-btn.validate:hover {
        background: rgba(26, 115, 232, 0.1);
    }

    .control-btn.apply {
        margin-left: auto; /* Push to right? Or just keep it next to others */
        background: var(--primary, #1a73e8);
        color: #fff;
        border-color: var(--primary, #1a73e8);
    }

    .control-btn.apply:hover {
        background: var(--primary-hover, #1558b0);
    }

    .control-btn.test {
        color: var(--text, #202124);
        border-color: var(--border, #dadce0);
    }

    .control-btn.test:hover {
        background: var(--surface-2, #f1f3f4);
    }

    .control-btn:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    .button-group {
        display: flex;
        gap: 8px;
        align-items: center;
        margin-top: 12px;
        flex-wrap: wrap;
    }

    .status-indicator {
        font-size: 0.85rem;
        font-weight: 500;
        margin-left: 8px;
    }

    .status-indicator.success {
        color: var(--success, #28a745);
    }

    .status-indicator.error {
        color: var(--danger, #dc3545);
    }
</style>
