<script lang="ts">
    import { onMount } from "svelte";
    import DashboardContainerView from "$lib/dashboard/components/dashboard/dashboard-container.svelte";
    import { dashboardContainer } from "$lib/dashboard/domain/dashboard-container.svelte.js";
    import { Widget } from "$lib/dashboard/domain/widget.svelte.js";
    import { GridLayout } from "$lib/dashboard/domain/layouts/grid-layout.svelte.js";
    import { DockLayout } from "$lib/dashboard/domain/layouts/dock-layout.svelte.js";
    import { FreeLayout } from "$lib/dashboard/domain/layouts/free-layout.svelte.js";

    // Setup test data with 3 different layout modes
    onMount(() => {
        console.log("Initializing Demo Dashboard with 3 layout modes...");

        // Clear existing to start fresh
        if (dashboardContainer.tabList.length === 0) {
            // === Tab 1: Grid Layout ===
            const gridTab = dashboardContainer.createTab({
                title: "Grid Layout",
                icon: "▦",
                layoutMode: "grid",
            });

            if (gridTab.layout instanceof GridLayout) {
                // Widget with custom colors and footer
                const cpuWidget = new Widget({
                    title: "CPU Usage",
                    icon: "⚡",
                    titleBackground: "#e3f2fd",
                    titleColor: "#1565c0",
                    footerContent: "<small>Updated every 5s</small>",
                });
                gridTab.layout.addWidget(cpuWidget, {
                    col: 0,
                    row: 0,
                    colSpan: 4,
                    rowSpan: 4,
                });

                // Widget with custom toolbar button
                const memoryWidget = new Widget({
                    title: "Memory",
                    icon: "💾",
                    titleBackground: "#e8f5e9",
                    titleColor: "#2e7d32",
                });
                memoryWidget.addToolbarButton({
                    id: "clear-cache",
                    icon: '<svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>',
                    title: "Clear Cache",
                    onClick: () =>
                        memoryWidget.setStatusMessage("Cache cleared!"),
                    visible: () => true,
                });
                gridTab.layout.addWidget(memoryWidget, {
                    col: 4,
                    row: 0,
                    colSpan: 4,
                    rowSpan: 4,
                });

                // Widget with header content
                const networkWidget = new Widget({
                    title: "Network",
                    icon: "🌐",
                    titleBackground: "#fff3e0",
                    titleColor: "#e65100",
                    headerContent:
                        "<div style='padding:4px 0;font-size:12px;'>↓ 125 MB/s ↑ 45 MB/s</div>",
                });
                gridTab.layout.addWidget(networkWidget, {
                    col: 8,
                    row: 0,
                    colSpan: 4,
                    rowSpan: 8,
                });

                // Non-closable widget
                const logsWidget = new Widget({
                    title: "Logs",
                    icon: "📝",
                    closable: false,
                    titleBackground: "#fce4ec",
                    titleColor: "#c2185b",
                });
                logsWidget.setStatusMessage("Streaming logs...");
                gridTab.layout.addWidget(logsWidget, {
                    col: 0,
                    row: 4,
                    colSpan: 8,
                    rowSpan: 4,
                });
            }

            // === Tab 2: Dock Layout ===
            const dockTab = dashboardContainer.createTab({
                title: "Dock Layout",
                icon: "⊞",
                layoutMode: "dock",
            });

            if (dockTab.layout instanceof DockLayout) {
                dockTab.layout.addWidget(
                    new Widget({ title: "System Info", icon: "🖥️" }),
                    "left",
                );
                dockTab.layout.addWidget(
                    new Widget({ title: "Performance", icon: "📊" }),
                    "right",
                );
                dockTab.layout.addWidget(
                    new Widget({ title: "Activity", icon: "📈" }),
                    "left",
                );
            }

            // === Tab 3: Free Layout ===
            const freeTab = dashboardContainer.createTab({
                title: "Free Layout",
                icon: "⊡",
                layoutMode: "free",
            });

            if (freeTab.layout instanceof FreeLayout) {
                freeTab.layout.addWidget(
                    new Widget({ title: "Widget A", icon: "🔷" }),
                    { x: 50, y: 50, width: 300, height: 200 },
                );
                freeTab.layout.addWidget(
                    new Widget({ title: "Widget B", icon: "🔶" }),
                    { x: 400, y: 100, width: 250, height: 180 },
                );
                freeTab.layout.addWidget(
                    new Widget({ title: "Widget C", icon: "🟢" }),
                    { x: 150, y: 300, width: 350, height: 220 },
                );
            }

            // === Tab 4: Component Layout ===
            dashboardContainer.createTab({
                title: "Contact Form",
                icon: "📝",
                layoutMode: "component",
                component: "SimpleForm",
            });

            // Activate first tab
            dashboardContainer.activateTab(gridTab.id);

            // Persist the initialized state so it's available for sharing
            import('$lib/data/mock-loader').then(({ persistCurrentState }) => {
                persistCurrentState().catch(err => console.error('Failed to persist demo dashboard:', err));
            });
        }
    });
</script>

<div class="demo-wrapper">
    <DashboardContainerView />
</div>

<style>
    .demo-wrapper {
        width: 100%;
        height: 100%;
        background: #eee;
        position: absolute;
        top: 0;
        left: 0;
    }
</style>
