<script lang="ts">
    import type { DashboardTab } from "../../domain/dashboard-tab.svelte.js";
    import type { LayoutMode, WidgetType } from "../../domain/types.js";
    import RenameModal from "../modals/rename-modal.svelte";
    import SettingsModal from "../modals/settings-modal.svelte";
    import AddWidgetModal from "../modals/add-widget-modal.svelte";

    interface Props {
        tabs: DashboardTab[];
        activeId: string | null;
        onActivate: (id: string) => void;
        onCreate: () => void;
        onClose: (id: string) => void;
        onAddWidget?: (
            tab: DashboardTab,
            widgetType: WidgetType,
            name: string,
            config?: { url?: string },
        ) => void;
        onShare?: (tab?: DashboardTab) => void;
    }

    let { tabs, activeId, onActivate, onCreate, onClose, onAddWidget, onShare }: Props =
        $props();

    // Menu state - track which tab's menu is open
    let openMenuTabId = $state<string | null>(null);
    let menuPosition = $state({ top: 0, left: 0 });
    let showTabList = $state(false);

    // Modal state
    let renameModalTab = $state<DashboardTab | null>(null);
    let settingsModalTab = $state<DashboardTab | null>(null);
    let addWidgetModalTab = $state<DashboardTab | null>(null);

    // Layout mode icons
    const layoutIcons: Record<LayoutMode, string> = {
        grid: "▦",
        free: "⊡",
        dock: "⊞",
        component: "🧩",
    };

    // Get the tab for the open menu
    let menuTab = $derived(
        openMenuTabId ? tabs.find((t) => t.id === openMenuTabId) : null,
    );

    function toggleMenu(e: MouseEvent, tabId: string) {
        e.stopPropagation();
        showTabList = false;

        if (openMenuTabId === tabId) {
            openMenuTabId = null;
        } else {
            // Calculate position relative to the button
            const button = e.currentTarget as HTMLElement;
            const rect = button.getBoundingClientRect();
            // Use fixed positioning relative to viewport since menu is portal-like (but here absolute in relative container)
            // Wait, container is relative. We need offset relative to container?
            // Actually, best to just render it relative to the button using absolute positioning in the loop?
            // No, user complaint was about clipping.
            // We moved it to .tab-bar level which is relative.

            // Let's get the .tab-bar rect
            const tabBar = (
                button.closest(".tab-bar") as HTMLElement
            ).getBoundingClientRect();

            menuPosition = {
                top: rect.bottom - tabBar.top + 4,
                left: rect.left - tabBar.left,
            };
            openMenuTabId = tabId;
        }
    }

    function closeMenu() {
        openMenuTabId = null;
        showTabList = false;
    }

    function toggleTabList(e: MouseEvent) {
        e.stopPropagation();
        openMenuTabId = null;
        showTabList = !showTabList;
    }

    // Menu action handlers
    function handleRename(tab: DashboardTab) {
        openMenuTabId = null;
        renameModalTab = tab;
    }

    function handleAddWidget(tab: DashboardTab) {
        openMenuTabId = null;
        addWidgetModalTab = tab;
    }

    function handleSettings(tab: DashboardTab) {
        openMenuTabId = null;
        settingsModalTab = tab;
    }

    function handleSlideshow(tab: DashboardTab) {
        openMenuTabId = null;
        tab.enterSlideshow();
    }

    function handleResetLayout(tab: DashboardTab) {
        openMenuTabId = null;
        console.log("Reset layout for tab:", tab.id);
        // TODO: Implement layout reset
    }

    function handleWidgetAdded(
        widgetType: WidgetType,
        name: string,
        config?: { url?: string },
    ) {
        if (addWidgetModalTab && onAddWidget) {
            onAddWidget(addWidgetModalTab, widgetType, name, config);
        }
    }

    // Debug
    $effect(() => {
        // console.log(
        //     "[TabBar] rendering tabs:",
        //     tabs.length,
        //     "active:",
        //     activeId,
        // );
    });
</script>

<svelte:window onclick={closeMenu} />

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="tab-bar" onclick={closeMenu}>
    <div class="tabs-scroll-area">
        {#each tabs as tab (tab.id)}
            <div
                class="tab"
                class:active={tab.id === activeId}
                onclick={() => onActivate(tab.id)}
                role="button"
                tabindex="0"
                onkeypress={(e) => e.key === "Enter" && onActivate(tab.id)}
            >
                <!-- Blue top border for active tab -->
                {#if tab.id === activeId}
                    <span class="tab-active-indicator"></span>
                {/if}

                <span class="tab-icon">{tab.icon}</span>
                <span class="tab-title">{tab.title}</span>
                <span class="tab-layout-icon" title="Layout: {tab.layoutMode}"
                    >{layoutIcons[tab.layoutMode]}</span
                >

                <!-- 3-dots menu button -->
                <button
                    class="tab-menu-btn"
                    type="button"
                    onclick={(e) => toggleMenu(e, tab.id)}
                    title="Tab Options"
                    class:active={openMenuTabId === tab.id}
                >
                    ⋮
                </button>

                <!-- Close button -->
                {#if tab.closable}
                    <button
                        class="tab-close"
                        type="button"
                        onclick={(e) => {
                            e.stopPropagation();
                            onClose(tab.id);
                        }}
                        title="Close Tab"
                    >
                        ×
                    </button>
                {/if}
            </div>
        {/each}
    </div>

    <!-- Dropdown menu - rendered OUTSIDE the scroll area to avoid clipping -->
    {#if menuTab}
        <div
            class="tab-menu"
            style="top: {menuPosition.top}px; left: {menuPosition.left}px;"
            onclick={(e) => e.stopPropagation()}
        >
            <div class="menu-header">
                <span class="menu-mode"
                    >Mode: {menuTab.layoutMode.toUpperCase()}</span
                >
            </div>
            <button
                class="menu-item"
                type="button"
                onclick={() => handleRename(menuTab!)}
            >
                <span class="menu-icon">{@html `<svg class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m14.304 4.844 2.852 2.852M7 7H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1v-4.5m2.409-9.91a2.017 2.017 0 0 1 0 2.853l-6.844 6.844L8 14l.713-3.565 6.844-6.844a2.015 2.015 0 0 1 2.852 0Z"/></svg>`}</span>
                <span class="menu-label">Rename...</span>
            </button>
            <button
                class="menu-item"
                type="button"
                onclick={() => handleAddWidget(menuTab!)}
            >
                <span class="menu-icon">{@html `<svg class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14m-7 7V5"/></svg>`}</span>
                <span class="menu-label">Add Widget...</span>
            </button>
            <div class="menu-separator"></div>
            <button
                class="menu-item"
                type="button"
                onclick={() => handleSlideshow(menuTab!)}
            >
                <span class="menu-icon">{@html `<svg class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 18V6l8 6-8 6Z"/></svg>`}</span>
                <span class="menu-label">Slideshow</span>
            </button>
            <div class="menu-separator"></div>
            <button
                class="menu-item"
                type="button"
                onclick={() => handleSettings(menuTab!)}
            >
                <span class="menu-icon">{@html `<svg class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 13v-2a1 1 0 0 0-1-1h-.757l-.447-.894.447-.894a1 1 0 0 0 .632-1.265l-.666-3.327a1 1 0 0 0-1.63-.5l-3.354 1.678-.895-.447V3.5a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v.757l-.894.447-3.354-1.678a1 1 0 0 0-1.63.5l-.666 3.327a1 1 0 0 0 .633 1.265l.447.894-.447.894H2.5a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h.757l.447.894-.447.894a1 1 0 0 0-.632 1.265l.666 3.327a1 1 0 0 0 1.63.5l3.354-1.678.895.447v.757a1 1 0 0 0 1 1h4a1 1 0 0 0 1-1v-.757l.894-.447 3.354 1.678a1 1 0 0 0 1.63-.5l.666-3.327a1 1 0 0 0-.633-1.265l-.447-.894.447-.894H20a1 1 0 0 0 1-1Z"/><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"/></svg>`}</span>
                <span class="menu-label">Settings...</span>
            </button>
            <button
                class="menu-item"
                type="button"
                onclick={() => handleResetLayout(menuTab!)}
            >
                <span class="menu-icon">{@html `<svg class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.651 7.65a7.131 7.131 0 0 0-12.68 3.15M6.349 16.35a7.131 7.131 0 0 0 12.68-3.15M17 14v4h-4M7 10V6h4"/></svg>`}</span>
                <span class="menu-label">Reset Layout</span>
            </button>
            <div class="menu-separator"></div>
            <button
                class="menu-item"
                type="button"
                onclick={() => {
                    const tabToShare = menuTab;
                    openMenuTabId = null;
                    onShare?.(tabToShare!);
                }}
            >
                <span class="menu-icon">{@html `<svg class="w-4 h-4" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h6l2 4m-8-4v8m0-8V6a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v9h2m8 0H9m4 0h2m4 0h2v-4m0 0h-5m3.5 5.5a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Zm-10 0a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z"/></svg>`}</span>
                <span class="menu-label">Share...</span>
            </button>
        </div>
    {/if}

    <!-- Share button (Active Tab) -->
    <button
        class="tab-list-btn"
        type="button"
        onclick={() => onShare?.()}
        title="Share Dashboard"
    >
        🔗
    </button>

    <!-- Tab list overflow button -->
    <button
        class="tab-list-btn"
        type="button"
        onclick={toggleTabList}
        title="All Tabs"
    >
        ☰
    </button>

    <!-- Tab list dropdown -->
    {#if showTabList}
        <div class="tab-list-dropdown" onclick={(e) => e.stopPropagation()}>
            <div class="tab-list-header">All Dashboards ({tabs.length})</div>
            {#each tabs as tab (tab.id)}
                <button
                    class="tab-list-item"
                    class:active={tab.id === activeId}
                    type="button"
                    onclick={() => {
                        onActivate(tab.id);
                        showTabList = false;
                    }}
                >
                    <span class="tab-icon">{tab.icon}</span>
                    <span class="tab-title">{tab.title}</span>
                    <span class="tab-layout-icon"
                        >{layoutIcons[tab.layoutMode]}</span
                    >
                </button>
            {/each}
        </div>
    {/if}

    <!-- Add new tab button -->
    <button
        class="tab-add"
        type="button"
        onclick={onCreate}
        title="New Dashboard"
    >
        +
    </button>
</div>

<!-- Modals -->
{#if renameModalTab}
    <RenameModal tab={renameModalTab} onClose={() => (renameModalTab = null)} />
{/if}

{#if settingsModalTab}
    <SettingsModal
        tab={settingsModalTab}
        onClose={() => (settingsModalTab = null)}
    />
{/if}

{#if addWidgetModalTab}
    <AddWidgetModal
        tab={addWidgetModalTab}
        onClose={() => (addWidgetModalTab = null)}
        onAddWidget={handleWidgetAdded}
    />
{/if}

<style>
    .tab-bar {
        display: flex;
        align-items: center;
        background: var(--surface, #fff);
        border-bottom: 1px solid var(--border, #dfe1e5);
        padding: 0 8px;
        height: 38px;
        gap: 4px;
        flex-shrink: 0;
        position: relative;
    }

    .tabs-scroll-area {
        display: flex;
        align-items: flex-end;
        gap: 2px;
        overflow-x: auto;
        flex: 1;
        height: 100%;
        scrollbar-width: none;
    }
    .tabs-scroll-area::-webkit-scrollbar {
        display: none;
    }

    .tab {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 0 10px;
        height: 32px;
        margin-bottom: -1px;

        background: transparent;
        border: 1px solid transparent;
        border-bottom: none;
        border-radius: 6px 6px 0 0;
        cursor: pointer;
        font-size: 0.8rem;
        color: var(--text-2, #5f6368);
        user-select: none;
        transition:
            background 0.1s,
            color 0.1s;
        min-width: 120px;
        max-width: 220px;
        position: relative;
    }

    .tab:hover {
        background: var(--surface-2, #f1f3f4);
        color: var(--text, #202124);
    }

    .tab.active {
        background: var(--surface, #fff);
        border-color: var(--border, #dfe1e5);
        color: var(--text, #202124);
        font-weight: 500;
        z-index: 1;
    }
    .tab.active::after {
        content: "";
        position: absolute;
        bottom: -1px;
        left: 0;
        right: 0;
        height: 1px;
        background: var(--surface, #fff);
    }

    /* Blue top border indicator for active tab */
    .tab-active-indicator {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: var(--primary, #1a73e8);
        border-radius: 3px 3px 0 0;
    }

    .tab-icon {
        font-size: 1em;
        flex-shrink: 0;
    }

    .tab-title {
        flex: 1;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .tab-layout-icon {
        font-size: 0.9em;
        color: var(--text-3, #9aa0a6);
        flex-shrink: 0;
    }

    .tab-menu-btn,
    .tab-close {
        width: 20px;
        height: 20px;
        border-radius: 4px;
        border: none;
        background: transparent;
        color: inherit;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        opacity: 0;
        font-size: 14px;
        flex-shrink: 0;
        transition:
            opacity 0.1s,
            background 0.1s;
    }

    .tab:hover .tab-menu-btn,
    .tab:hover .tab-close,
    .tab.active .tab-menu-btn {
        opacity: 0.6;
    }

    .tab-menu-btn:hover,
    .tab-close:hover,
    .tab-menu-btn.active {
        background: rgba(0, 0, 0, 0.1);
        opacity: 1 !important;
    }

    /* Dropdown menu - positioned at tab-bar level */
    .tab-menu {
        position: absolute;
        /* Top and Left are set via inline styles */
        min-width: 180px;
        background: var(--surface, #fff);
        border: 1px solid var(--border, #dfe1e5);
        border-radius: 8px;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
        z-index: 100;
        padding: 4px 0;
        margin-top: 4px;
    }

    .menu-header {
        padding: 8px 12px;
        font-size: 0.75rem;
        color: var(--text-3, #9aa0a6);
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .menu-separator {
        height: 1px;
        background: var(--border, #e8eaed);
        margin: 4px 0;
    }

    .menu-item {
        display: flex;
        align-items: center;
        gap: 10px;
        width: 100%;
        padding: 8px 12px;
        border: none;
        background: transparent;
        font-size: 0.75rem;
        color: var(--text, #202124);
        cursor: pointer;
        text-align: left;
    }

    .menu-item:hover {
        background: var(--surface-2, #f1f3f4);
    }

    .menu-icon {
        font-size: 1em;
        width: 20px;
        text-align: center;
    }

    /* Tab list button and dropdown */
    .tab-list-btn {
        width: 32px;
        height: 32px;
        border-radius: 4px;
        border: 1px solid transparent;
        background: transparent;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1rem;
        color: var(--text-2, #5f6368);
    }
    .tab-list-btn:hover {
        background: var(--surface-2, #f1f3f4);
        color: var(--primary, #1a73e8);
    }

    .tab-list-dropdown {
        position: absolute;
        top: 100%;
        right: 48px;
        min-width: 200px;
        max-height: 300px;
        overflow-y: auto;
        background: var(--surface, #fff);
        border: 1px solid var(--border, #dfe1e5);
        border-radius: 8px;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
        z-index: 100;
        padding: 4px 0;
        margin-top: 4px;
    }

    .tab-list-header {
        padding: 8px 12px;
        font-size: 0.75rem;
        color: var(--text-3, #9aa0a6);
        font-weight: 500;
        border-bottom: 1px solid var(--border, #e8eaed);
        margin-bottom: 4px;
    }

    .tab-list-item {
        display: flex;
        align-items: center;
        gap: 8px;
        width: 100%;
        padding: 8px 12px;
        border: none;
        background: transparent;
        font-size: 0.75rem;
        color: var(--text, #202124);
        cursor: pointer;
        text-align: left;
    }

    .tab-list-item:hover {
        background: var(--surface-2, #f1f3f4);
    }

    .tab-list-item.active {
        background: var(--primary-light, #e8f0fe);
        color: var(--primary, #1a73e8);
    }

    .tab-add {
        width: 32px;
        height: 32px;
        border-radius: 50%;
        border: 1px solid transparent;
        background: transparent;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.2rem;
        color: var(--text-2, #5f6368);
    }
    .tab-add:hover {
        background: var(--surface-2, #f1f3f4);
        color: var(--primary, #1a73e8);
    }
</style>
