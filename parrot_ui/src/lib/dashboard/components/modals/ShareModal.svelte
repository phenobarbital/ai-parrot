<script lang="ts">
    interface Props {
        url: string;
        title?: string;
        onClose: () => void;
    }

    let { url, title = "Share URL", onClose }: Props = $props();
    let copied = $state(false);

    function handleCopy() {
        navigator.clipboard.writeText(url).then(() => {
            copied = true;
            setTimeout(() => {
                copied = false;
            }, 2000);
        });
    }

    function handleOverlayClick(e: MouseEvent) {
        if (e.target === e.currentTarget) {
            onClose();
        }
    }
</script>

<div class="modal-overlay" onclick={handleOverlayClick} role="dialog" aria-modal="true">
    <div class="modal-box">
        <h3 class="font-bold text-lg mb-4">{title}</h3>
        
        <p class="py-2 text-sm text-gray-600">Share this link with others to grant access to this dashboard object.</p>
        
        <div class="join w-full mt-2">
            <input 
                type="text" 
                readonly 
                value={url} 
                class="input input-bordered join-item w-full bg-base-200 text-sm font-mono"
            />
            <button class="btn join-item btn-primary" onclick={handleCopy}>
                {#if copied}
                    <span>✓ Copied</span>
                {:else}
                    <span>Copy</span>
                {/if}
            </button>
        </div>
        
        <div class="modal-action">
            <button class="btn" onclick={onClose}>Close</button>
        </div>
    </div>
</div>

<style>
    .modal-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-color: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
    }

    .modal-box {
        background: var(--surface, #fff);
        padding: 1.5rem;
        border-radius: 0.5rem;
        max-width: 32rem;
        width: 100%;
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
    }
</style>
