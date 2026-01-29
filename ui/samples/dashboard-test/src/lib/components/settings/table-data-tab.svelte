<script lang="ts">
    import type {
        TableWidget,
        DataSourceType,
        JsonDataSourceConfig,
    } from "../../domain/table-widget.svelte.js";
    import type { DataSourceConfig } from "../../domain/data-source.svelte.js";
    import type { QSDataSourceConfig } from "../../domain/qs-datasource.svelte.js";
    import { DEFAULT_QS_URL } from "../../domain/qs-datasource.svelte.js";

    interface Props {
        widget: TableWidget;
        onConfigChange: (config: {
            dataSourceType: DataSourceType;
            restConfig?: DataSourceConfig;
            qsConfig?: QSDataSourceConfig;
            jsonConfig?: JsonDataSourceConfig;
        }) => void;
    }

    let { widget, onConfigChange }: Props = $props();

    // Local state
    let dataSourceType = $state<DataSourceType>(widget.dataSourceType);

    // REST config
    let restUrl = $state(widget.restConfig?.url ?? "");
    let restMethod = $state(widget.restConfig?.method ?? "GET");

    // QS config
    let qsSlug = $state(widget.qsConfig?.slug ?? "");
    let qsBaseUrl = $state(widget.qsConfig?.baseUrl ?? DEFAULT_QS_URL);
    let qsPayload = $state(
        widget.qsConfig?.payload
            ? JSON.stringify(widget.qsConfig.payload, null, 2)
            : "",
    );
    let showQsAdvanced = $state(false);

    // JSON config
    let jsonMode = $state<"inline" | "url">(
        widget.jsonConfig?.mode ?? "inline",
    );
    let jsonInline = $state(widget.jsonConfig?.json ?? "[]");
    let jsonUrl = $state(widget.jsonConfig?.url ?? "");
    let jsonError = $state<string | null>(null);

    const dataSourceOptions: {
        value: DataSourceType;
        label: string;
        icon: string;
    }[] = [
        { value: "rest", label: "REST API", icon: "🌐" },
        { value: "json", label: "JSON Data", icon: "📄" },
    ];

    // Validate JSON
    function validateJson(value: string): boolean {
        try {
            JSON.parse(value);
            jsonError = null;
            return true;
        } catch {
            jsonError = "Invalid JSON format";
            return false;
        }
    }

    // Notify parent on change
    function notifyChange() {
        const config: Parameters<typeof onConfigChange>[0] = {
            dataSourceType,
        };

        if (dataSourceType === "rest") {
            config.restConfig = { url: restUrl, method: restMethod };
        } else if (dataSourceType === "qs") {
            let payload: Record<string, unknown> | undefined;
            if (qsPayload.trim()) {
                try {
                    payload = JSON.parse(qsPayload);
                } catch {
                    // Ignore invalid payload
                }
            }
            config.qsConfig = { slug: qsSlug, baseUrl: qsBaseUrl, payload };
        } else if (dataSourceType === "json") {
            config.jsonConfig = {
                mode: jsonMode,
                json: jsonMode === "inline" ? jsonInline : undefined,
                url: jsonMode === "url" ? jsonUrl : undefined,
            };
        }

        onConfigChange(config);
    }

    $effect(() => {
        notifyChange();
    });
</script>

<div class="data-tab">
    <!-- Data Source Type Selector -->
    <section class="settings-section">
        <h3 class="section-title">Data Source Type</h3>
        <div class="source-type-selector">
            {#each dataSourceOptions as opt}
                <label
                    class="source-type-option"
                    class:selected={dataSourceType === opt.value}
                >
                    <input
                        type="radio"
                        name="data-source-type"
                        value={opt.value}
                        bind:group={dataSourceType}
                    />
                    <span class="option-icon">{opt.icon}</span>
                    <span class="option-label">{opt.label}</span>
                </label>
            {/each}
        </div>
    </section>

    <!-- REST Configuration -->
    {#if dataSourceType === "rest"}
        <section class="settings-section">
            <h3 class="section-title">REST Configuration</h3>
            <div class="form-group">
                <label for="rest-url">URL <span class="required">*</span></label
                >
                <input
                    type="url"
                    id="rest-url"
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
        </section>
    {/if}

    <!-- QuerySource Configuration -->
    {#if dataSourceType === "qs"}
        <section class="settings-section">
            <h3 class="section-title">QuerySource Configuration</h3>
            <div class="form-group">
                <label for="qs-slug">Slug <span class="required">*</span></label
                >
                <input
                    type="text"
                    id="qs-slug"
                    bind:value={qsSlug}
                    placeholder="my_query_slug"
                />
            </div>

            <button
                type="button"
                class="advanced-toggle"
                onclick={() => (showQsAdvanced = !showQsAdvanced)}
            >
                <span>Advanced Options</span>
                <span class="chevron" class:open={showQsAdvanced}>▼</span>
            </button>

            {#if showQsAdvanced}
                <div class="advanced-section">
                    <div class="form-group">
                        <label for="qs-base-url">Base URL</label>
                        <input
                            type="url"
                            id="qs-base-url"
                            bind:value={qsBaseUrl}
                            placeholder={DEFAULT_QS_URL}
                        />
                    </div>
                    <div class="form-group">
                        <label for="qs-payload">Payload (JSON)</label>
                        <textarea
                            id="qs-payload"
                            bind:value={qsPayload}
                            rows="4"
                            placeholder={'{"param": "value"}'}
                        ></textarea>
                    </div>
                </div>
            {/if}
        </section>
    {/if}

    <!-- JSON Configuration -->
    {#if dataSourceType === "json"}
        <section class="settings-section">
            <h3 class="section-title">JSON Configuration</h3>
            <div class="form-group">
                <label for="json-mode">Source</label>
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
                        onblur={() => validateJson(jsonInline)}
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
                        type="url"
                        id="json-url"
                        bind:value={jsonUrl}
                        placeholder="https://example.com/data.json"
                    />
                </div>
            {/if}
        </section>
    {/if}
</div>
