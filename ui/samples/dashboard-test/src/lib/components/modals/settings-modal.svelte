<script lang="ts">
    import type { DashboardTab } from "../../domain/dashboard-tab.svelte.js";
    import type {
        LayoutMode,
        DashboardTemplate,
        GridMode,
    } from "../../domain/types.js";
    import { GRID_MODE_PRESETS } from "../../domain/types.js";

    interface Props {
        tab: DashboardTab;
        onClose: () => void;
    }

    let { tab, onClose }: Props = $props();

    let activeSection = $state<"general" | "layout" | "template">("general");
    let title = $state(tab.title);
    let layoutMode = $state<LayoutMode>(tab.layoutMode);
    let gridMode = $state<GridMode>(tab.gridMode);
    let template = $state<DashboardTemplate>(tab.template);
    let paneSize = $state(tab.paneSize);

    function saveTitle() {
        tab.title = title;
    }

    function saveLayout() {
        tab.switchLayout(layoutMode);
    }

    function saveGridMode() {
        tab.gridMode = gridMode;
    }

    function saveTemplate() {
        tab.template = template;
        tab.paneSize = paneSize;
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === "Escape") onClose();
    }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
    class="modal-overlay"
    role="dialog"
    aria-modal="true"
    onclick={onClose}
    onkeydown={handleKeydown}
>
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="modal" onclick={(e) => e.stopPropagation()}>
        <div class="modal-header">
            <h2 class="modal-title">
                <span class="title-icon">⚙️</span>
                Dashboard Settings
            </h2>
            <button type="button" class="close-btn" onclick={onClose}>×</button>
        </div>

        <div class="settings-tabs">
            <button
                type="button"
                class="settings-tab"
                class:active={activeSection === "general"}
                onclick={() => (activeSection = "general")}
            >
                <span class="tab-icon">⚙️</span>
                General
            </button>
            <button
                type="button"
                class="settings-tab"
                class:active={activeSection === "layout"}
                onclick={() => (activeSection = "layout")}
            >
                <span class="tab-icon">📐</span>
                Layout
            </button>
            <button
                type="button"
                class="settings-tab"
                class:active={activeSection === "template"}
                onclick={() => (activeSection = "template")}
            >
                <span class="tab-icon">🖼️</span>
                Template
            </button>
        </div>

        <div class="settings-content">
            {#if activeSection === "general"}
                <div class="setting-group">
                    <label class="setting-label" for="dashboard-title"
                        >Dashboard Title</label
                    >
                    <input
                        id="dashboard-title"
                        type="text"
                        class="setting-input"
                        bind:value={title}
                    />
                    <button
                        type="button"
                        class="btn btn-primary"
                        onclick={saveTitle}
                    >
                        Save Title
                    </button>

                    <div class="setting-divider"></div>

                    <label class="setting-checkbox">
                        <input type="checkbox" bind:checked={tab.closable} />
                        <span class="checkbox-label"
                            >Allow closing this tab</span
                        >
                    </label>
                </div>
            {:else if activeSection === "layout"}
                <div class="setting-group">
                    <label class="setting-label">Layout Mode</label>
                    <div class="layout-options">
                        <label
                            class="layout-option"
                            class:selected={layoutMode === "grid"}
                        >
                            <input
                                type="radio"
                                name="layout"
                                value="grid"
                                bind:group={layoutMode}
                            />
                            <span class="layout-icon">▦</span>
                            <span class="layout-name">Grid</span>
                        </label>
                        <label
                            class="layout-option"
                            class:selected={layoutMode === "free"}
                        >
                            <input
                                type="radio"
                                name="layout"
                                value="free"
                                bind:group={layoutMode}
                            />
                            <span class="layout-icon">⊡</span>
                            <span class="layout-name">Free</span>
                        </label>
                        <label
                            class="layout-option"
                            class:selected={layoutMode === "dock"}
                        >
                            <input
                                type="radio"
                                name="layout"
                                value="dock"
                                bind:group={layoutMode}
                            />
                            <span class="layout-icon">⊞</span>
                            <span class="layout-name">Dock</span>
                        </label>
                    </div>
                    <button
                        type="button"
                        class="btn btn-primary"
                        onclick={saveLayout}
                    >
                        Apply Layout
                    </button>

                    {#if layoutMode === "grid"}
                        <div class="setting-divider"></div>
                        <label class="setting-label">Grid Layout Mode</label>
                        <div class="grid-mode-options">
                            {#each GRID_MODE_PRESETS as preset (preset.id)}
                                <label
                                    class="grid-mode-option"
                                    class:selected={gridMode === preset.id}
                                >
                                    <input
                                        type="radio"
                                        name="gridMode"
                                        value={preset.id}
                                        bind:group={gridMode}
                                    />
                                    <div class="grid-mode-preview">
                                        {#each preset.columns as col}
                                            <div
                                                class="grid-mode-col"
                                                style="flex: {col}"
                                            ></div>
                                        {/each}
                                    </div>
                                    <span class="grid-mode-name"
                                        >{preset.name}</span
                                    >
                                    <span class="grid-mode-desc"
                                        >{preset.description}</span
                                    >
                                </label>
                            {/each}
                        </div>
                        <button
                            type="button"
                            class="btn btn-primary"
                            onclick={saveGridMode}
                        >
                            Apply Grid Mode
                        </button>
                    {/if}
                </div>
            {:else if activeSection === "template"}
                <div class="setting-group">
                    <label class="setting-label">Dashboard Template</label>
                    <div class="template-options">
                        <label
                            class="template-option"
                            class:selected={template === "default"}
                        >
                            <input
                                type="radio"
                                name="template"
                                value="default"
                                bind:group={template}
                            />
                            <span class="template-icon">━</span>
                            <span class="template-name">Default</span>
                            <span class="template-desc">No pane</span>
                        </label>
                        <label
                            class="template-option"
                            class:selected={template === "pane-left"}
                        >
                            <input
                                type="radio"
                                name="template"
                                value="pane-left"
                                bind:group={template}
                            />
                            <span class="template-icon">▌┃</span>
                            <span class="template-name">Left Pane</span>
                            <span class="template-desc">Sidebar left</span>
                        </label>
                        <label
                            class="template-option"
                            class:selected={template === "pane-right"}
                        >
                            <input
                                type="radio"
                                name="template"
                                value="pane-right"
                                bind:group={template}
                            />
                            <span class="template-icon">┃▐</span>
                            <span class="template-name">Right Pane</span>
                            <span class="template-desc">Sidebar right</span>
                        </label>
                        <label
                            class="template-option"
                            class:selected={template === "pane-top"}
                        >
                            <input
                                type="radio"
                                name="template"
                                value="pane-top"
                                bind:group={template}
                            />
                            <span class="template-icon">▔┃</span>
                            <span class="template-name">Top Pane</span>
                            <span class="template-desc">Header area</span>
                        </label>
                        <label
                            class="template-option"
                            class:selected={template === "pane-bottom"}
                        >
                            <input
                                type="radio"
                                name="template"
                                value="pane-bottom"
                                bind:group={template}
                            />
                            <span class="template-icon">┃▁</span>
                            <span class="template-name">Bottom Pane</span>
                            <span class="template-desc">Footer area</span>
                        </label>
                    </div>

                    {#if template !== "default"}
                        <div class="setting-divider"></div>
                        <label class="setting-label" for="pane-size"
                            >Pane Size ({paneSize}px)</label
                        >
                        <input
                            id="pane-size"
                            type="range"
                            class="setting-range"
                            min="100"
                            max="500"
                            step="10"
                            bind:value={paneSize}
                        />
                    {/if}

                    <button
                        type="button"
                        class="btn btn-primary"
                        onclick={saveTemplate}
                    >
                        Apply Template
                    </button>
                </div>
            {/if}
        </div>

        <div class="modal-footer">
            <button type="button" class="btn btn-secondary" onclick={onClose}>
                Close
            </button>
        </div>
    </div>
</div>

<style>
    .modal-overlay {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.4);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
    }

    .modal {
        background: var(--surface, #fff);
        border-radius: 12px;
        min-width: 420px;
        max-width: 90vw;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
        overflow: hidden;
    }

    .modal-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 20px;
        border-bottom: 1px solid var(--border, #e8eaed);
    }

    .modal-title {
        margin: 0;
        font-size: 1.1rem;
        font-weight: 600;
        color: var(--text, #202124);
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .title-icon {
        font-size: 1.2em;
    }

    .close-btn {
        width: 32px;
        height: 32px;
        border-radius: 50%;
        border: none;
        background: transparent;
        font-size: 1.5rem;
        color: var(--text-2, #5f6368);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .close-btn:hover {
        background: var(--surface-2, #f1f3f4);
    }

    .settings-tabs {
        display: flex;
        border-bottom: 1px solid var(--border, #e8eaed);
        padding: 0 20px;
    }

    .settings-tab {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 12px 16px;
        border: none;
        background: transparent;
        font-size: 0.9rem;
        color: var(--text-2, #5f6368);
        cursor: pointer;
        border-bottom: 2px solid transparent;
        margin-bottom: -1px;
    }

    .settings-tab:hover {
        color: var(--text, #202124);
    }

    .settings-tab.active {
        color: var(--primary, #1a73e8);
        border-bottom-color: var(--primary, #1a73e8);
    }

    .tab-icon {
        font-size: 1em;
    }

    .settings-content {
        padding: 20px;
        min-height: 160px;
    }

    .setting-group {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .setting-label {
        font-size: 0.85rem;
        font-weight: 500;
        color: var(--text, #202124);
    }

    .setting-input {
        padding: 10px 14px;
        border: 1px solid var(--border, #dfe1e5);
        border-radius: 6px;
        font-size: 0.95rem;
        outline: none;
    }

    .setting-input:focus {
        border-color: var(--primary, #1a73e8);
    }

    .layout-options {
        display: flex;
        gap: 12px;
    }

    .layout-option {
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 6px;
        padding: 16px 12px;
        border: 2px solid var(--border, #e8eaed);
        border-radius: 8px;
        cursor: pointer;
        transition:
            border-color 0.15s,
            background 0.15s;
    }

    .layout-option:hover {
        background: var(--surface-2, #f8f9fa);
    }

    .layout-option.selected {
        border-color: var(--primary, #1a73e8);
        background: var(--primary-light, #e8f0fe);
    }

    .layout-option input {
        display: none;
    }

    .layout-icon {
        font-size: 1.5rem;
    }

    .layout-name {
        font-size: 0.85rem;
        font-weight: 500;
    }

    .setting-divider {
        height: 1px;
        background: var(--border, #e8eaed);
        margin: 8px 0;
    }

    .setting-checkbox {
        display: flex;
        align-items: center;
        gap: 10px;
        cursor: pointer;
        user-select: none;
    }

    .checkbox-label {
        font-size: 0.9rem;
        color: var(--text, #202124);
    }

    .modal-footer {
        display: flex;
        justify-content: flex-end;
        padding: 16px 20px;
        border-top: 1px solid var(--border, #e8eaed);
    }

    .btn {
        padding: 10px 20px;
        border-radius: 6px;
        font-size: 0.9rem;
        font-weight: 500;
        cursor: pointer;
        border: none;
        transition: background 0.15s;
    }

    .btn-secondary {
        background: transparent;
        color: var(--text-2, #5f6368);
    }
    .btn-secondary:hover {
        background: var(--surface-2, #f1f3f4);
    }

    .btn-primary {
        background: var(--primary, #1a73e8);
        color: white;
    }
    .btn-primary:hover {
        background: var(--primary-dark, #1557b0);
    }

    /* Template options */
    .template-options {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
    }

    .template-option {
        flex: 1;
        min-width: 100px;
        max-width: 120px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 4px;
        padding: 12px 8px;
        border: 2px solid var(--border, #e8eaed);
        border-radius: 8px;
        cursor: pointer;
        transition:
            border-color 0.15s,
            background 0.15s;
        text-align: center;
    }

    .template-option:hover {
        background: var(--surface-2, #f8f9fa);
    }

    .template-option.selected {
        border-color: var(--primary, #1a73e8);
        background: var(--primary-light, #e8f0fe);
    }

    .template-option input {
        display: none;
    }

    .template-icon {
        font-size: 1.3rem;
        font-family: monospace;
    }

    .template-name {
        font-size: 0.8rem;
        font-weight: 500;
    }

    .template-desc {
        font-size: 0.7rem;
        color: var(--text-3, #9aa0a6);
    }

    .setting-range {
        width: 100%;
        height: 6px;
        border-radius: 3px;
        accent-color: var(--primary, #1a73e8);
    }

    /* Grid Mode Options */
    .grid-mode-options {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
        gap: 12px;
    }

    .grid-mode-option {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding: 16px 12px;
        border: 2px solid var(--border, #e8eaed);
        border-radius: 8px;
        cursor: pointer;
        transition:
            border-color 0.15s,
            background 0.15s;
        text-align: center;
    }

    .grid-mode-option:hover {
        background: var(--surface-2, #f8f9fa);
    }

    .grid-mode-option.selected {
        border-color: var(--primary, #1a73e8);
        background: var(--primary-light, #e8f0fe);
    }

    .grid-mode-option input {
        display: none;
    }

    .grid-mode-preview {
        display: flex;
        gap: 4px;
        height: 40px;
        padding: 6px;
        background: var(--surface-2, #f1f3f4);
        border-radius: 4px;
    }

    .grid-mode-col {
        background: var(--border, #dadce0);
        border-radius: 3px;
        min-width: 8px;
    }

    .grid-mode-option.selected .grid-mode-col {
        background: var(--primary, #1a73e8);
        opacity: 0.6;
    }

    .grid-mode-name {
        font-size: 0.85rem;
        font-weight: 500;
        color: var(--text, #202124);
    }

    .grid-mode-desc {
        font-size: 0.7rem;
        color: var(--text-3, #9aa0a6);
        line-height: 1.3;
    }
</style>
