<script lang="ts">
    import type { DashboardTab } from "../../domain/dashboard-tab.svelte.js";

    interface Props {
        tab: DashboardTab;
        onClose: () => void;
    }

    let { tab, onClose }: Props = $props();

    let title = $state(tab.title);

    function handleSubmit() {
        tab.title = title;
        onClose();
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === "Escape") onClose();
        if (e.key === "Enter") handleSubmit();
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
        <h2 class="modal-title">Rename Dashboard</h2>

        <input
            type="text"
            class="modal-input"
            bind:value={title}
            placeholder="Dashboard name"
            autofocus
        />

        <div class="modal-actions">
            <button type="button" class="btn btn-secondary" onclick={onClose}>
                Cancel
            </button>
            <button
                type="button"
                class="btn btn-primary"
                onclick={handleSubmit}
            >
                Rename
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
        padding: 24px;
        min-width: 360px;
        max-width: 90vw;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
    }

    .modal-title {
        margin: 0 0 20px;
        font-size: 1.25rem;
        font-weight: 600;
        color: var(--text, #202124);
    }

    .modal-input {
        width: 100%;
        padding: 12px 16px;
        border: 2px solid var(--border, #dfe1e5);
        border-radius: 8px;
        font-size: 1rem;
        color: var(--text, #202124);
        outline: none;
        transition: border-color 0.2s;
    }

    .modal-input:focus {
        border-color: var(--primary, #1a73e8);
    }

    .modal-actions {
        display: flex;
        justify-content: flex-end;
        gap: 12px;
        margin-top: 20px;
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
</style>
