<script lang="ts">
    import type { Widget } from '../../domain/widget.svelte.js';
    import ConfirmDialog from '../modals/confirm-dialog.svelte';
    import WidgetSettingsModal from '../modals/widget-settings-modal.svelte';

    interface Props {
        widget: Widget;
        showCloseConfirm: boolean;
        showSettings: boolean;
        onConfirmClose: () => void;
        onCancelClose: () => void;
        onCloseSettings: () => void;
    }

    let {
        widget,
        showCloseConfirm,
        showSettings,
        onConfirmClose,
        onCancelClose,
        onCloseSettings
    }: Props = $props();
</script>

{#if showCloseConfirm}
    <ConfirmDialog
        title="Close Widget"
        message="Are you sure you want to close this widget?"
        confirmText="Close"
        cancelText="Cancel"
        type="warning"
        onConfirm={onConfirmClose}
        onCancel={onCancelClose}
    />
{/if}

{#if showSettings}
    <WidgetSettingsModal {widget} onClose={onCloseSettings} />
{/if}
