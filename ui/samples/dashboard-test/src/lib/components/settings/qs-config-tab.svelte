<script lang="ts">
    import type { QSWidget } from "../../domain/qs-widget.svelte.js";
    import type { QSDataSourceConfig } from "../../domain/qs-datasource.svelte.js";

    interface Props {
        widget: QSWidget;
        onConfigChange: (config: QSDataSourceConfig) => void;
    }

    let { widget, onConfigChange }: Props = $props();

    let slug = $state(widget.qsDataSource?.qsConfig.slug ?? "");
    let baseUrl = $state(widget.qsDataSource?.qsConfig.baseUrl ?? "");

    $effect(() => {
        onConfigChange({
            slug,
            baseUrl: baseUrl || undefined,
        });
    });
</script>

<div class="tab-section">
    <div class="form-group">
        <label for="qs-slug">Query slug</label>
        <input id="qs-slug" type="text" bind:value={slug} />
    </div>
    <div class="form-group">
        <label for="qs-base-url">Base URL</label>
        <input id="qs-base-url" type="text" bind:value={baseUrl} />
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

    input {
        width: 100%;
        padding: 8px 10px;
        border: 1px solid var(--border, #dadce0);
        border-radius: 6px;
        font-size: 0.9rem;
    }
</style>
