<script lang="ts">
    interface Props {
        title?: string;
        message: string;
        confirmText?: string;
        cancelText?: string;
        type?: "warning" | "danger" | "info";
        onConfirm: () => void;
        onCancel: () => void;
    }

    let {
        title = "Confirm",
        message,
        confirmText = "Yes",
        cancelText = "No",
        type = "warning",
        onConfirm,
        onCancel,
    }: Props = $props();

    function handleOverlayClick(e: MouseEvent) {
        if (e.target === e.currentTarget) {
            onCancel();
        }
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === "Escape") {
            onCancel();
        }
    }
</script>

<svelte:window onkeydown={handleKeydown} />

<div
    class="confirm-overlay"
    onclick={handleOverlayClick}
    role="dialog"
    aria-modal="true"
>
    <div
        class="confirm-dialog"
        class:danger={type === "danger"}
        class:warning={type === "warning"}
    >
        <div class="confirm-header">
            <span class="confirm-icon">
                {#if type === "danger"}❌{:else if type === "warning"}⚠️{:else}ℹ️{/if}
            </span>
            <h3 class="confirm-title">{title}</h3>
        </div>

        <div class="confirm-body">
            <p>{message}</p>
        </div>

        <div class="confirm-footer">
            <button class="btn-cancel" type="button" onclick={onCancel}>
                {cancelText}
            </button>
            <button
                class="btn-confirm"
                class:danger={type === "danger"}
                type="button"
                onclick={onConfirm}
            >
                {confirmText}
            </button>
        </div>
    </div>
</div>

<style>
    .confirm-overlay {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 100000;
        animation: fadeIn 0.15s ease-out;
    }

    @keyframes fadeIn {
        from {
            opacity: 0;
        }
        to {
            opacity: 1;
        }
    }

    .confirm-dialog {
        background: var(--surface, #fff);
        border-radius: 12px;
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
        min-width: 320px;
        max-width: 420px;
        animation: slideIn 0.15s ease-out;
    }

    @keyframes slideIn {
        from {
            opacity: 0;
            transform: scale(0.95) translateY(-10px);
        }
        to {
            opacity: 1;
            transform: scale(1) translateY(0);
        }
    }

    .confirm-header {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 20px 24px 0;
    }

    .confirm-icon {
        font-size: 1.5rem;
    }

    .confirm-title {
        margin: 0;
        font-size: 1.1rem;
        font-weight: 600;
        color: var(--text, #202124);
    }

    .confirm-body {
        padding: 16px 24px;
    }

    .confirm-body p {
        margin: 0;
        color: var(--text-2, #5f6368);
        font-size: 0.95rem;
        line-height: 1.5;
    }

    .confirm-footer {
        display: flex;
        justify-content: flex-end;
        gap: 12px;
        padding: 16px 24px;
        border-top: 1px solid var(--border, #e8eaed);
    }

    .btn-cancel,
    .btn-confirm {
        padding: 10px 20px;
        font-size: 0.9rem;
        font-weight: 500;
        border-radius: 6px;
        cursor: pointer;
        transition: all 0.15s;
    }

    .btn-cancel {
        background: transparent;
        border: 1px solid var(--border, #dadce0);
        color: var(--text-2, #5f6368);
    }

    .btn-cancel:hover {
        background: var(--surface-2, #f8f9fa);
    }

    .btn-confirm {
        background: var(--primary, #1a73e8);
        border: none;
        color: white;
    }

    .btn-confirm:hover {
        background: var(--primary-dark, #1557b0);
    }

    .btn-confirm.danger {
        background: var(--danger, #dc3545);
    }

    .btn-confirm.danger:hover {
        background: #c82333;
    }
</style>
