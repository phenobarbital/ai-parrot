<script lang="ts">
    import type { Widget } from '../../domain/widget.svelte.js';

    interface ToolbarButton {
        id: string;
        icon: string;
        title: string;
        onClick: () => void;
        visible?: () => boolean;
    }

    interface Props {
        widget: Widget;
        visibleButtons: ToolbarButton[];
        showBurgerMenu: boolean;
        isToolbarOverflowing?: boolean;
        onDrag?: (e: PointerEvent) => void;
        onBurgerToggle: (e: MouseEvent) => void;
        onBurgerAction: (action: () => void) => void;
    }

    let {
        widget,
        visibleButtons,
        showBurgerMenu,
        isToolbarOverflowing = false,
        onDrag,
        onBurgerToggle,
        onBurgerAction
    }: Props = $props();
</script>

<header
    class="widget-titlebar"
    style:background={widget.getTitleBarGradient()}
    onpointerdown={onDrag}
>
    <div class="widget-title-group">
        <span class="widget-icon" style:color={widget.titleColor}>{widget.icon}</span>
        <h3 class="widget-title" style:color={widget.titleColor}>
            {widget.title}
        </h3>
    </div>

    <div class="widget-actions">
        <!-- Regular toolbar (hidden when overflowing) -->
        <div class="widget-toolbar" class:hidden={isToolbarOverflowing}>
            {#each visibleButtons as btn (btn.id)}
                <button
                    class="widget-toolbtn"
                    class:close-btn={btn.id === 'close'}
                    class:settings-btn={btn.id === 'settings'}
                    type="button"
                    title={btn.title}
                    onclick={(e) => {
                        e.stopPropagation();
                        btn.onClick();
                    }}
                >
                    {@html btn.icon}
                </button>
            {/each}
        </div>

        <!-- Burger menu button -->
        <button
            class="widget-burger"
            type="button"
            title="Menu"
            onclick={onBurgerToggle}
        >
            <svg
                class="w-3.5 h-3.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
            >
                <line x1="3" y1="12" x2="21" y2="12"></line>
                <line x1="3" y1="6" x2="21" y2="6"></line>
                <line x1="3" y1="18" x2="21" y2="18"></line>
            </svg>
        </button>

        <!-- Burger dropdown menu -->
        {#if showBurgerMenu}
            <div class="burger-menu" onclick={(e) => e.stopPropagation()}>
                {#each visibleButtons as btn (btn.id)}
                    <button
                        class="burger-item"
                        class:danger={btn.id === 'close'}
                        type="button"
                        onclick={() => onBurgerAction(btn.onClick)}
                    >
                        <span class="burger-icon">{btn.icon}</span>
                        <span class="burger-label">{btn.title}</span>
                    </button>
                {/each}
            </div>
        {/if}
    </div>
</header>

<style>
    .widget-titlebar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 2px 8px;
        background: linear-gradient(to bottom, #f8f9fa, #e8eaed);
        border-bottom: 1px solid var(--border-subtle, #e8eaed);
        cursor: grab;
        user-select: none;
        flex-shrink: 0;
        min-height: 24px;
    }

    .widget-titlebar:active {
        cursor: grabbing;
    }

    .widget-title-group {
        display: flex;
        align-items: center;
        gap: 8px;
        overflow: hidden;
        flex: 1;
    }

    .widget-icon {
        font-size: 1.1rem;
        flex-shrink: 0;
    }

    .widget-title {
        margin: 0;
        font-size: 0.85rem;
        font-weight: 600;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .widget-actions {
        display: flex;
        align-items: center;
        gap: 4px;
        flex-shrink: 0;
        position: relative;
    }

    .widget-toolbar {
        display: flex;
        gap: 2px;
    }

    .widget-toolbar.hidden {
        display: none;
    }

    .widget-toolbtn {
        width: 26px;
        height: 26px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: transparent;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        color: var(--text-2, #5f6368);
        font-size: 0.95rem;
        transition: background 0.15s, color 0.15s;
    }

    .widget-toolbtn:hover {
        background: rgba(0, 0, 0, 0.08);
        color: var(--text, #202124);
    }

    .widget-toolbtn.close-btn:hover {
        background: rgba(220, 53, 69, 0.12);
        color: var(--danger, #dc3545);
    }

    .widget-burger {
        width: 28px;
        height: 28px;
        display: none;
        align-items: center;
        justify-content: center;
        background: transparent;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        color: var(--text-2, #5f6368);
        font-size: 1rem;
    }

    .widget-burger:hover {
        background: rgba(0, 0, 0, 0.08);
    }

    @container (max-width: 280px) {
        .widget-toolbar {
            display: none;
        }
        .widget-burger {
            display: flex;
        }
    }

    @media (max-width: 400px) {
        .widget-toolbar {
            display: none;
        }
        .widget-burger {
            display: flex;
        }
    }

    .burger-menu {
        position: absolute;
        top: 100%;
        right: 0;
        margin-top: 4px;
        background: var(--surface, #fff);
        border: 1px solid var(--border, #e8eaed);
        border-radius: 8px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
        min-width: 160px;
        z-index: 1000;
        overflow: hidden;
    }

    .burger-item {
        display: flex;
        align-items: center;
        gap: 10px;
        width: 100%;
        padding: 10px 14px;
        background: transparent;
        border: none;
        text-align: left;
        cursor: pointer;
        color: var(--text, #202124);
        font-size: 0.875rem;
        transition: background 0.1s;
    }

    .burger-item:hover {
        background: var(--surface-2, #f8f9fa);
    }

    .burger-item.danger:hover {
        background: rgba(220, 53, 69, 0.08);
        color: var(--danger, #dc3545);
    }

    .burger-icon {
        width: 20px;
        text-align: center;
    }
</style>
