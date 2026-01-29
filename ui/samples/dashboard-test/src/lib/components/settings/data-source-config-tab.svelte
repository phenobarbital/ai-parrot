<script lang="ts">
    import type { Widget } from "../../domain/widget.svelte.js";
    import type {
        DataSourceConfig,
        AuthStrategy,
    } from "../../domain/data-source.svelte.js";
    import {
        DataSource,
        DataSourceError,
    } from "../../domain/data-source.svelte.js";

    interface Props {
        widget: Widget;
        onConfigChange: (config: DataSourceConfig) => void;
    }

    let { widget, onConfigChange }: Props = $props();

    // HTTP methods
    const httpMethods = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;

    // Auth strategy types
    const authTypes = [
        { value: "none", label: "None" },
        { value: "basic", label: "Basic Auth" },
        { value: "apiKey", label: "API Key" },
        { value: "bearer", label: "Bearer Token" },
        { value: "jwt-storage", label: "JWT (Local Storage)" },
        { value: "jwt-session", label: "JWT (Session Storage)" },
        { value: "oauth2", label: "OAuth2 Client Credentials" },
        { value: "custom", label: "Custom Headers" },
    ] as const;

    // Form state - initialize from widget's current config
    const currentConfig = (widget.config.dataSource ?? {}) as DataSourceConfig;

    let url = $state(currentConfig.url ?? "");
    let method = $state<DataSourceConfig["method"]>(
        currentConfig.method ?? "GET",
    );
    let authType = $state<AuthStrategy["type"]>("none");

    // Auth-specific fields
    let basicUsername = $state("");
    let basicPassword = $state("");
    let apiKeyValue = $state("");
    let apiKeyHeader = $state("X-API-Key");
    let apiKeyPrefix = $state("");
    let bearerToken = $state("");
    let jwtStorageKey = $state("auth_token");
    let jwtSessionKey = $state("auth_token");
    let oauth2Endpoint = $state("");
    let oauth2ClientId = $state("");
    let oauth2ClientSecret = $state("");
    let oauth2Scope = $state("");
    let customHeaders = $state<Array<{ key: string; value: string }>>([
        { key: "", value: "" },
    ]);

    // Test state
    let testing = $state(false);
    let testResult = $state<{
        success: boolean;
        message: string;
        data?: string;
    } | null>(null);

    // Initialize auth fields from current config on mount
    $effect(() => {
        const auth = currentConfig.auth;
        if (!auth) return;

        authType = auth.type;
        if (auth.type === "basic") {
            basicUsername = auth.username ?? "";
            basicPassword = auth.password ?? "";
        } else if (auth.type === "apiKey") {
            apiKeyValue = auth.key ?? "";
            apiKeyHeader = auth.header ?? "X-API-Key";
            apiKeyPrefix = auth.prefix ?? "";
        } else if (auth.type === "bearer") {
            bearerToken = auth.token ?? "";
        } else if (auth.type === "jwt-storage") {
            jwtStorageKey = auth.storageKey ?? "auth_token";
        } else if (auth.type === "jwt-session") {
            jwtSessionKey = auth.sessionKey ?? "auth_token";
        } else if (auth.type === "oauth2") {
            oauth2Endpoint = auth.tokenEndpoint ?? "";
            oauth2ClientId = auth.clientId ?? "";
            oauth2ClientSecret = auth.clientSecret ?? "";
            oauth2Scope = auth.scope ?? "";
        }
    });

    function buildAuthStrategy(): AuthStrategy {
        switch (authType) {
            case "basic":
                return {
                    type: "basic",
                    username: basicUsername,
                    password: basicPassword,
                };
            case "apiKey":
                return {
                    type: "apiKey",
                    key: apiKeyValue,
                    header: apiKeyHeader || undefined,
                    prefix: apiKeyPrefix || undefined,
                };
            case "bearer":
                return { type: "bearer", token: bearerToken };
            case "jwt-storage":
                return {
                    type: "jwt-storage",
                    storageKey: jwtStorageKey || undefined,
                };
            case "jwt-session":
                return {
                    type: "jwt-session",
                    sessionKey: jwtSessionKey || undefined,
                };
            case "oauth2":
                return {
                    type: "oauth2",
                    tokenEndpoint: oauth2Endpoint,
                    clientId: oauth2ClientId,
                    clientSecret: oauth2ClientSecret,
                    scope: oauth2Scope || undefined,
                };
            case "custom": {
                // Build a getHeaders function from the custom headers
                const headers: Record<string, string> = {};
                for (const h of customHeaders) {
                    if (h.key.trim()) {
                        headers[h.key.trim()] = h.value;
                    }
                }
                return {
                    type: "custom",
                    getHeaders: async () => headers,
                };
            }
            default:
                return { type: "none" };
        }
    }

    function buildConfig(): DataSourceConfig {
        return {
            url,
            method,
            auth: buildAuthStrategy(),
        };
    }

    // Notify parent of config changes
    $effect(() => {
        if (url) {
            onConfigChange(buildConfig());
        }
    });

    function addCustomHeader() {
        customHeaders = [...customHeaders, { key: "", value: "" }];
    }

    function removeCustomHeader(index: number) {
        customHeaders = customHeaders.filter((_, i) => i !== index);
        if (customHeaders.length === 0) {
            customHeaders = [{ key: "", value: "" }];
        }
    }

    async function handleTest() {
        if (!url) {
            testResult = { success: false, message: "URL is required" };
            return;
        }

        testing = true;
        testResult = null;

        try {
            const config = buildConfig();
            const testDs = new DataSource(config);
            const data = await testDs.fetch();
            const preview =
                typeof data === "object"
                    ? JSON.stringify(data, null, 2).slice(0, 300)
                    : String(data).slice(0, 300);
            testResult = {
                success: true,
                message: "Connection successful!",
                data: preview,
            };
        } catch (err) {
            const error =
                err instanceof DataSourceError ? err : new Error(String(err));
            testResult = {
                success: false,
                message: error.message,
            };
        } finally {
            testing = false;
        }
    }
</script>

<div class="datasource-config">
    <!-- URL and Method -->
    <div class="form-row">
        <div class="form-group url-group">
            <label for="ds-url">URL</label>
            <input
                id="ds-url"
                type="url"
                bind:value={url}
                placeholder="https://api.example.com/data"
            />
        </div>
        <div class="form-group method-group">
            <label for="ds-method">Method</label>
            <select id="ds-method" bind:value={method}>
                {#each httpMethods as m}
                    <option value={m}>{m}</option>
                {/each}
            </select>
        </div>
    </div>

    <!-- Auth Strategy -->
    <div class="form-group">
        <label for="ds-auth">Authentication</label>
        <select id="ds-auth" bind:value={authType}>
            {#each authTypes as auth}
                <option value={auth.value}>{auth.label}</option>
            {/each}
        </select>
    </div>

    <!-- Auth-specific fields -->
    <div class="auth-fields">
        {#if authType === "basic"}
            <div class="form-row">
                <div class="form-group">
                    <label for="basic-user">Username</label>
                    <input
                        id="basic-user"
                        type="text"
                        bind:value={basicUsername}
                    />
                </div>
                <div class="form-group">
                    <label for="basic-pass">Password</label>
                    <input
                        id="basic-pass"
                        type="password"
                        bind:value={basicPassword}
                    />
                </div>
            </div>
        {:else if authType === "apiKey"}
            <div class="form-row">
                <div class="form-group">
                    <label for="apikey-header">Header Name</label>
                    <input
                        id="apikey-header"
                        type="text"
                        bind:value={apiKeyHeader}
                        placeholder="X-API-Key"
                    />
                </div>
                <div class="form-group">
                    <label for="apikey-prefix">Prefix (optional)</label>
                    <input
                        id="apikey-prefix"
                        type="text"
                        bind:value={apiKeyPrefix}
                        placeholder="Bearer"
                    />
                </div>
            </div>
            <div class="form-group">
                <label for="apikey-value">API Key</label>
                <input
                    id="apikey-value"
                    type="password"
                    bind:value={apiKeyValue}
                />
            </div>
        {:else if authType === "bearer"}
            <div class="form-group">
                <label for="bearer-token">Bearer Token</label>
                <input
                    id="bearer-token"
                    type="password"
                    bind:value={bearerToken}
                />
            </div>
        {:else if authType === "jwt-storage"}
            <div class="form-group">
                <label for="jwt-storage-key">LocalStorage Key</label>
                <input
                    id="jwt-storage-key"
                    type="text"
                    bind:value={jwtStorageKey}
                    placeholder="auth_token"
                />
            </div>
            <p class="hint">
                Token will be read from localStorage at request time.
            </p>
        {:else if authType === "jwt-session"}
            <div class="form-group">
                <label for="jwt-session-key">SessionStorage Key</label>
                <input
                    id="jwt-session-key"
                    type="text"
                    bind:value={jwtSessionKey}
                    placeholder="auth_token"
                />
            </div>
            <p class="hint">
                Token will be read from sessionStorage at request time.
            </p>
        {:else if authType === "oauth2"}
            <div class="form-group">
                <label for="oauth2-url">Token Endpoint</label>
                <input
                    id="oauth2-url"
                    type="url"
                    bind:value={oauth2Endpoint}
                    placeholder="https://auth.example.com/oauth/token"
                />
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label for="oauth2-client">Client ID</label>
                    <input
                        id="oauth2-client"
                        type="text"
                        bind:value={oauth2ClientId}
                    />
                </div>
                <div class="form-group">
                    <label for="oauth2-secret">Client Secret</label>
                    <input
                        id="oauth2-secret"
                        type="password"
                        bind:value={oauth2ClientSecret}
                    />
                </div>
            </div>
            <div class="form-group">
                <label for="oauth2-scope">Scope (optional)</label>
                <input
                    id="oauth2-scope"
                    type="text"
                    bind:value={oauth2Scope}
                    placeholder="read write"
                />
            </div>
        {:else if authType === "custom"}
            <div class="custom-headers">
                <span class="field-label">Custom Headers</span>
                {#each customHeaders as header, i}
                    <div class="header-row">
                        <input
                            type="text"
                            bind:value={header.key}
                            placeholder="Header name"
                        />
                        <input
                            type="text"
                            bind:value={header.value}
                            placeholder="Value"
                        />
                        <button
                            type="button"
                            class="remove-btn"
                            onclick={() => removeCustomHeader(i)}>×</button
                        >
                    </div>
                {/each}
                <button
                    type="button"
                    class="add-header-btn"
                    onclick={addCustomHeader}>+ Add Header</button
                >
            </div>
        {:else}
            <p class="hint">No authentication required.</p>
        {/if}
    </div>

    <!-- Test Button -->
    <div class="test-section">
        <button
            type="button"
            class="test-btn"
            onclick={handleTest}
            disabled={testing || !url}
        >
            {#if testing}
                Testing...
            {:else}
                🧪 Test Connection
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
    .datasource-config {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    .form-group {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .form-group label,
    .field-label {
        font-size: 0.875rem;
        font-weight: 500;
        color: var(--text, #202124);
    }

    .form-row {
        display: flex;
        gap: 12px;
    }

    .form-row .form-group {
        flex: 1;
    }

    .url-group {
        flex: 1;
    }

    .method-group {
        width: 100px;
        flex: none !important;
    }

    input[type="text"],
    input[type="url"],
    input[type="password"],
    select {
        padding: 10px 12px;
        font-size: 0.95rem;
        border: 1px solid var(--border, #dadce0);
        border-radius: 6px;
        background: var(--surface, #fff);
        transition: border-color 0.15s;
    }

    input:focus,
    select:focus {
        outline: none;
        border-color: var(--primary, #1a73e8);
        box-shadow: 0 0 0 3px rgba(26, 115, 232, 0.12);
    }

    select {
        cursor: pointer;
    }

    .auth-fields {
        padding: 12px;
        background: var(--surface-2, #f8f9fa);
        border-radius: 8px;
        min-height: 40px;
    }

    .hint {
        margin: 0;
        font-size: 0.8rem;
        color: var(--text-3, #9aa0a6);
        font-style: italic;
    }

    .custom-headers {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .header-row {
        display: flex;
        gap: 8px;
        align-items: center;
    }

    .header-row input {
        flex: 1;
    }

    .remove-btn {
        width: 28px;
        height: 28px;
        padding: 0;
        background: transparent;
        border: 1px solid var(--border, #dadce0);
        border-radius: 4px;
        cursor: pointer;
        color: var(--text-2, #5f6368);
        font-size: 1rem;
        flex-shrink: 0;
    }

    .remove-btn:hover {
        background: rgba(220, 53, 69, 0.1);
        border-color: var(--danger, #dc3545);
        color: var(--danger, #dc3545);
    }

    .add-header-btn {
        padding: 8px 12px;
        background: transparent;
        border: 1px dashed var(--border, #dadce0);
        border-radius: 6px;
        cursor: pointer;
        color: var(--primary, #1a73e8);
        font-size: 0.875rem;
        margin-top: 8px;
    }

    .add-header-btn:hover {
        background: rgba(26, 115, 232, 0.05);
    }

    .test-section {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding-top: 8px;
        border-top: 1px solid var(--border-subtle, #e8eaed);
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

    .result-icon {
        font-weight: bold;
        display: inline;
    }

    .result-message {
        display: inline;
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
</style>
