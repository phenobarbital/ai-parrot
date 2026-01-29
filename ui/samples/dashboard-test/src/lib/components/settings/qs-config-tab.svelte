<script lang="ts">
    import type {
        QSDataSourceConfig,
        QSDataSource,
    } from "../../domain/qs-datasource.svelte.js";
    import { DEFAULT_QS_URL } from "../../domain/qs-datasource.svelte.js";
    import type { Widget } from "../../domain/widget.svelte.js";

    interface Props {
        widget: Widget;
        onConfigChange: (config: QSDataSourceConfig) => void;
    }

    let { widget, onConfigChange }: Props = $props();

    // Initialize from existing config or defaults
    // We assume the widget is a QSWidget, so it has qsConfig inside its config or directly accessible if casted
    // But since we are passing generic widget, we try to safely extract it
    const currentConfig = (widget as any).qsDataSource?.qsConfig ||
        (widget.config as any).qsConfig || {
            slug: "",
            baseUrl: DEFAULT_QS_URL,
            fields: [],
            filter: {},
        };

    let slug = $state(currentConfig.slug || "");
    let baseUrl = $state(currentConfig.baseUrl || DEFAULT_QS_URL);

    // JSON editors state
    let payloadJson = $state(
        JSON.stringify(currentConfig.payload || {}, null, 2),
    );
    let filterJson = $state(
        JSON.stringify(currentConfig.filter || {}, null, 2),
    );
    let fieldsStr = $state((currentConfig.fields || []).join(", "));

    // Validation state
    // Validation state
    let payloadError = $state("");
    let filterError = $state("");

    // UI state
    let showAdvanced = $state(false);

    // Testing state
    let testing = $state(false);
    let testResult = $state<{
        success: boolean;
        message: string;
        data?: string;
    } | null>(null);

    function validateJson(json: string): Record<string, unknown> | null {
        try {
            return JSON.parse(json);
        } catch (e) {
            return null;
        }
    }

    function buildConfig(): QSDataSourceConfig {
        const payload = validateJson(payloadJson) || {};
        const filter = validateJson(filterJson) || {};
        const fields = fieldsStr
            .split(",")
            .map((f: string) => f.trim())
            .filter((f: string) => f.length > 0);

        return {
            slug,
            baseUrl,
            payload,
            filter,
            fields,
            auth: { type: "jwt-storage", storageKey: "auth_token" }, // Default for now
        };
    }

    // Effect to notify parent of changes
    $effect(() => {
        // Validate JSONs
        if (!validateJson(payloadJson)) {
            payloadError = "Invalid JSON";
            return;
        } else {
            payloadError = "";
        }

        if (!validateJson(filterJson)) {
            filterError = "Invalid JSON";
            return;
        } else {
            filterError = "";
        }

        if (slug) {
            onConfigChange(buildConfig());
        }
    });

    async function handleTest() {
        if (!slug) {
            testResult = { success: false, message: "Slug is required" };
            return;
        }

        testing = true;
        testResult = null;

        try {
            // We need to import QSDataSource dynamically to avoid circular deps if any
            // or just use the one we imported
            const { QSDataSource } = await import(
                "../../domain/qs-datasource.svelte.js"
            );
            const config = buildConfig();
            const ds = new QSDataSource(config);
            const data = await ds.fetch();

            const preview =
                typeof data === "object"
                    ? JSON.stringify(data, null, 2).slice(0, 300)
                    : String(data).slice(0, 300);

            testResult = {
                success: true,
                message: "Query successful!",
                data: preview,
            };
        } catch (err: any) {
            testResult = {
                success: false,
                message: err.message || String(err),
            };
        } finally {
            testing = false;
        }
    }
</script>

<div class="qs-config">
    <!-- Header info -->
    <div class="info-block">
        <p>
            QuerySource Endpoint: <code
                >{baseUrl}/api/v2/services/queries/{slug || "{slug}"}</code
            >
        </p>
    </div>

    <!-- Base URL & Slug -->
    <!-- Slug -->
    <div class="form-group">
        <label for="qs-slug">Slug <span class="required">*</span></label>
        <input
            id="qs-slug"
            type="text"
            bind:value={slug}
            placeholder="e.g. hisense_stores"
        />
    </div>

    <!-- Advanced Options -->
    <div class="advanced-section">
        <button
            type="button"
            class="advanced-toggle"
            onclick={() => (showAdvanced = !showAdvanced)}
            aria-expanded={showAdvanced}
        >
            <span>Advanced Options</span>
            <span class="toggle-icon">▼</span>
        </button>

        {#if showAdvanced}
            <div class="advanced-content">
                <div class="form-group">
                    <label for="qs-base-url">API URL</label>
                    <input
                        id="qs-base-url"
                        type="url"
                        bind:value={baseUrl}
                        placeholder="http://navigator-dev.dev.local:5000"
                    />
                </div>
            </div>
        {/if}
    </div>

    <!-- Fields -->
    <div class="form-group">
        <label for="qs-fields">Fields (comma separated)</label>
        <input
            id="qs-fields"
            type="text"
            bind:value={fieldsStr}
            placeholder="store_id, exact_name, etc."
        />
        <p class="hint">Leave empty to fetch all fields.</p>
    </div>

    <!-- Payload JSON -->
    <div class="form-group">
        <label for="qs-payload">Payload (JSON)</label>
        <textarea
            id="qs-payload"
            bind:value={payloadJson}
            class:has-error={!!payloadError}
            rows="3"
        ></textarea>
        {#if payloadError}
            <span class="error-msg">{payloadError}</span>
        {/if}
    </div>

    <!-- Filter JSON -->
    <div class="form-group">
        <label for="qs-filter">Filter (JSON, optional)</label>
        <textarea
            id="qs-filter"
            bind:value={filterJson}
            class:has-error={!!filterError}
            rows="3"
        ></textarea>
        {#if filterError}
            <span class="error-msg">{filterError}</span>
        {/if}
    </div>

    <!-- Test Button -->
    <div class="test-section">
        <button
            type="button"
            class="test-btn"
            onclick={handleTest}
            disabled={testing || !slug}
        >
            {#if testing}
                Testing...
            {:else}
                ⚡ Test Query
            {/if}
        </button>

        {#if testResult}
            <div
                class="test-result"
                class:success={testResult.success}
                class:error={!testResult.success}
            >
                <span class="result-icon">{testResult.success ? "✓" : "✗"}</span
                >
                <span class="result-message">{testResult.message}</span>
                {#if testResult.data}
                    <pre class="result-data">{testResult.data}...</pre>
                {/if}
            </div>
        {/if}
    </div>
</div>

<style>
    .test-section {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .test-btn {
        padding: 10px 16px;
        background: var(--surface, #fff);
        border: 1px solid var(--primary, #1a73e8);
        border-radius: 6px;
        color: var(--primary, #1a73e8);
        font-weight: 500;
        cursor: pointer;
        transition: all 0.15s;
    }

    .test-btn:hover:not(:disabled) {
        background: rgba(26, 115, 232, 0.08);
    }

    .test-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .test-result {
        padding: 12px;
        border-radius: 6px;
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .test-result.success {
        background: rgba(34, 197, 94, 0.1);
        border: 1px solid rgba(34, 197, 94, 0.3);
        color: #166534;
    }

    .test-result.error {
        background: rgba(220, 53, 69, 0.1);
        border: 1px solid rgba(220, 53, 69, 0.3);
        color: #991b1b;
    }

    .result-data {
        margin: 0;
        padding: 8px;
        background: rgba(0, 0, 0, 0.05);
        border-radius: 4px;
        font-size: 0.75rem;
        overflow-x: auto;
        max-height: 100px;
        white-space: pre-wrap;
        word-break: break-all;
    }
    .advanced-section {
        border: 1px solid var(--border, #dfe1e5);
        border-radius: 8px;
        overflow: hidden;
        background: var(--surface, #fff);
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
        transition: background 0.15s;
    }

    .advanced-toggle:hover {
        background: var(--surface-hover, #f1f3f4);
        text-decoration: none;
    }

    .toggle-icon {
        font-size: 0.75rem;
        color: var(--text-3, #9aa0a6);
        transition: transform 0.2s;
    }

    .advanced-toggle[aria-expanded="true"] .toggle-icon {
        transform: rotate(180deg);
    }

    .advanced-content {
        padding: 16px;
        background: var(--surface, #fff);
        border-top: 1px solid var(--border, #dfe1e5);
        animation: none; /* Removed slideDown since we are in a box */
    }
</style>
