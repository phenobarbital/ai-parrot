<script lang="ts">
    /**
     * DashboardModule
     * 
     * A lightweight dashboard shell for wrapping full modules (like AgentDashboard)
     * without the overhead of tab management.
     */
    import { type Snippet } from 'svelte';

    interface Props {
        title?: string;
        icon?: string;
        children?: Snippet;
        headerExtra?: Snippet;
    }

    let { title, icon, children, headerExtra }: Props = $props();
</script>

<div class="dashboard-module">
    <!-- Header -->
    <header class="dashboard-header">
        <div class="header-main">
            {#if icon}
                <span class="header-icon">{icon}</span>
            {/if}
            {#if title}
                <h2 class="header-title">{title}</h2>
            {/if}
        </div>
        
        {#if headerExtra}
            <div class="header-extra">
                {@render headerExtra()}
            </div>
        {/if}
    </header>

    <!-- Content -->
    <main class="dashboard-content">
        {#if children}
            {@render children()}
        {/if}
    </main>
</div>

<style>
    .dashboard-module {
        display: flex;
        flex-direction: column;
        height: 100%;
        width: 100%;
        background: var(--surface-2, #f8f9fa);
        overflow: hidden;
    }

    .dashboard-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        height: 48px;
        padding: 0 16px;
        background: var(--surface, #ffffff);
        border-bottom: 1px solid var(--border, #e0e0e0);
        flex-shrink: 0;
    }

    .header-main {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .header-icon {
        font-size: 1.2rem;
    }

    .header-title {
        font-size: 1rem;
        font-weight: 600;
        margin: 0;
        color: var(--text-1, #333);
    }

    .dashboard-content {
        flex: 1;
        min-height: 0;
        position: relative;
        overflow: auto;
    }

    .header-extra {
        display: flex;
        align-items: center;
        gap: 8px;
    }
</style>
