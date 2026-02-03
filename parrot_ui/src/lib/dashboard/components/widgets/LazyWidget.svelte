<script lang="ts">
    import type { Snippet } from 'svelte';

    interface Props {
        children: Snippet;
        placeholderClass?: string;
        rootMargin?: string;
    }

    let { 
        children, 
        placeholderClass = 'widget-placeholder',
        rootMargin = '100px'
    }: Props = $props();

    let visible = $state(false);

    function inViewport(node: HTMLElement) {
        const observer = new IntersectionObserver(
            ([entry]) => {
                if (entry.isIntersecting) {
                    visible = true;
                    observer.disconnect();
                }
            },
            { rootMargin }
        );
        observer.observe(node);
        return { destroy: () => observer.disconnect() };
    }
</script>

<div use:inViewport class="lazy-widget-container">
    {#if visible}
        {@render children()}
    {:else}
        <div class={placeholderClass}></div>
    {/if}
</div>

<style>
    .lazy-widget-container {
        width: 100%;
        height: 100%;
    }

    :global(.widget-placeholder) {
        width: 100%;
        height: 100%;
        min-height: 200px;
        background: linear-gradient(
            90deg,
            var(--surface-2, #f8f9fa) 25%,
            var(--surface-3, #f1f3f4) 50%,
            var(--surface-2, #f8f9fa) 75%
        );
        background-size: 200% 100%;
        animation: shimmer 1.5s infinite;
        border-radius: 8px;
    }

    @keyframes shimmer {
        0% {
            background-position: 200% 0;
        }
        100% {
            background-position: -200% 0;
        }
    }
</style>
