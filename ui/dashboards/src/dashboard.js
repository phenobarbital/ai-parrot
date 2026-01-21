// dashboard.ts - Dashboard Container con API completa
// Note: CSS styles should be loaded via <link> tag in HTML or bundler
import { el, on, stop, uid, cssPx } from "./utils.js";
import { InputModal } from "./input-modal.js";
import { bus } from "./events.js";
import { FreeLayout } from "./free-layout.js";
import { DockLayout } from "./dock-layout.js";
import { GridLayout } from "./grid-layout.js";
import { Widget } from "./widget.js";
export { GridLayout, FreeLayout, DockLayout };
// === Dashboard View (una pestaña individual) ===
export class DashboardView {
    id;
    el;
    header;
    main;
    footer;
    layout;
    layoutMode;
    title;
    icon;
    disposers = [];
    slideshowState = null;
    constructor(id, title, icon, opts) {
        this.id = id;
        this.title = title;
        this.icon = icon;
        this.layoutMode = opts.layoutMode ?? "grid";
        this.el = el("section", {
            class: "dashboard-view",
            "data-dashboard-id": id
        });
        this.header = el("div", { class: "dashboard-header" });
        this.main = el("div", { class: "dashboard-main" });
        this.footer = el("div", { class: "dashboard-footer" });
        if (opts.template?.header) {
            this.header.appendChild(opts.template.header);
        }
        if (opts.template?.footer) {
            this.footer.appendChild(opts.template.footer);
        }
        this.el.append(this.header, this.main, this.footer);
        // Crear layout dinámicamente
        if (this.layoutMode === "free") {
            this.layout = new FreeLayout(this, opts.free);
        }
        else if (this.layoutMode === "dock") {
            this.layout = new DockLayout(this, opts.dock);
        }
        else {
            this.layout = new GridLayout(this, opts.grid);
        }
        this.main.appendChild(this.layout.el);
    }
    setGridLayout(presetId) {
        if (this.layout instanceof GridLayout) {
            this.layout.setPreset(presetId);
        }
    }
    getGridLayoutPreset() {
        if (this.layout instanceof GridLayout) {
            return this.layout.getCurrentPreset();
        }
        return null;
    }
    getTitle() {
        return this.title;
    }
    setTitle(title) {
        this.title = title;
    }
    getIcon() {
        return this.icon;
    }
    setIcon(icon) {
        this.icon = icon;
    }
    getLayoutMode() {
        return this.layoutMode;
    }
    getWidgets() {
        return this.layout.getWidgets();
    }
    addWidget(widget, placement) {
        // TypeScript doesn't unify the addWidget signatures perfectly automatically
        if (this.layout instanceof GridLayout) {
            this.layout.addWidget(widget, placement);
        }
        else if (this.layout instanceof FreeLayout) {
            this.layout.addWidget(widget, placement);
        }
        else if (this.layout instanceof DockLayout) {
            // DockLayout expects a string or DockPosition usually, but our interface is AnyPlacement
            // We'll trust the caller passes the right shape or the layout handles it
            // The placement for dock is usually just a string like 'center' in the demo loop
            // but `types.ts` defines AnyPlacement as object.
            // Let's assume placement is { dockPosition: ... } for dock mode
            const p = placement;
            this.layout.addWidget(widget, p.dockPosition ?? "center");
        }
    }
    removeWidget(widget) {
        this.layout.removeWidget(widget);
    }
    // === Slideshow Mode ===
    enterSlideshow() {
        const widgets = this.getWidgets();
        if (widgets.length === 0)
            return;
        this.slideshowState = {
            index: 0,
            widgets,
            keyHandler: null,
            overlay: null,
        };
        // Crear overlay
        const overlay = el("div", { class: "slideshow-overlay" });
        const content = el("div", { class: "slideshow-content" });
        const controls = el("div", { class: "slideshow-controls" });
        const prevBtn = el("button", { class: "slideshow-btn", type: "button", title: "Previous" }, "◀");
        const indicator = el("span", { class: "slideshow-indicator" });
        const nextBtn = el("button", { class: "slideshow-btn", type: "button", title: "Next" }, "▶");
        const closeBtn = el("button", { class: "slideshow-btn slideshow-close", type: "button", title: "Exit" }, "✕");
        on(prevBtn, "click", () => this.slideshowPrev());
        on(nextBtn, "click", () => this.slideshowNext());
        on(closeBtn, "click", () => this.exitSlideshow());
        controls.append(prevBtn, indicator, nextBtn, closeBtn);
        overlay.append(content, controls);
        document.body.appendChild(overlay);
        this.slideshowState.overlay = overlay;
        this.slideshowState.content = content;
        this.slideshowState.indicator = indicator;
        // Keyboard navigation
        const keyHandler = (e) => {
            if (e.key === "ArrowLeft")
                this.slideshowPrev();
            else if (e.key === "ArrowRight")
                this.slideshowNext();
            else if (e.key === "Escape")
                this.exitSlideshow();
        };
        window.addEventListener("keydown", keyHandler);
        this.slideshowState.keyHandler = keyHandler;
        this.showSlideshowWidget(0);
        bus.emit("slideshow:start", { dashboard: this });
    }
    showSlideshowWidget(index) {
        if (!this.slideshowState)
            return;
        const { widgets, content, indicator } = this.slideshowState;
        const len = widgets.length;
        // Wrap index
        this.slideshowState.index = ((index % len) + len) % len;
        const widget = widgets[this.slideshowState.index];
        if (!widget)
            return;
        // Clear and show widget clone
        // Security: Use cloneNode(true) instead of innerHTML to prevent XSS
        // from re-triggering event handlers like <img onerror=...>
        if (content) {
            content.innerHTML = "";
            const clone = el("div", { class: "slideshow-widget" });
            // Create header with sanitized text content
            const header = el("div", { class: "slideshow-widget-header" });
            const iconSpan = el("span", { class: "slideshow-icon" });
            iconSpan.textContent = widget.getIcon();
            const titleSpan = el("span", { class: "slideshow-title" });
            titleSpan.textContent = widget.getTitle();
            header.append(iconSpan, titleSpan);
            // Clone widget content using cloneNode to avoid innerHTML re-parsing
            const body = el("div", { class: "slideshow-widget-body" });
            const widgetContent = widget.el.querySelector(".widget-content");
            if (widgetContent) {
                body.appendChild(widgetContent.cloneNode(true));
            }
            clone.append(header, body);
            content.appendChild(clone);
        }
        if (indicator) {
            indicator.textContent = `${this.slideshowState.index + 1} / ${len}`;
        }
    }
    slideshowNext() {
        if (!this.slideshowState)
            return;
        this.showSlideshowWidget(this.slideshowState.index + 1);
    }
    slideshowPrev() {
        if (!this.slideshowState)
            return;
        this.showSlideshowWidget(this.slideshowState.index - 1);
    }
    exitSlideshow() {
        if (!this.slideshowState)
            return;
        if (this.slideshowState.keyHandler) {
            window.removeEventListener("keydown", this.slideshowState.keyHandler);
        }
        this.slideshowState.overlay?.remove();
        this.slideshowState = null;
        bus.emit("slideshow:end", { dashboard: this });
    }
    destroy() {
        this.exitSlideshow();
        this.layout.destroy();
        for (const d of this.disposers)
            d();
    }
    // === Layout Persistence ===
    /**
     * Save the current widget layout to localStorage.
     */
    saveLayout() {
        this.layout.saveState?.();
    }
    /**
     * Reset layout to default positions and clear saved state.
     */
    resetLayout() {
        this.layout.reset?.();
    }
    /**
     * Load saved layout from localStorage (called on init).
     */
    loadLayout() {
        this.layout.loadState?.();
    }
}
// === Dashboard Container (contenedor de todas las pestañas) ===
export class DashboardContainer {
    el;
    tabBar;
    tabStrip;
    addBtn;
    content;
    dashboards = new Map();
    activeId = null;
    disposers = [];
    constructor(mount) {
        // Registrar globalmente para que los widgets puedan encontrarlo
        window.__dashboardContainer = this;
        this.el = el("div", { class: "dashboard-container" });
        // === Tab Bar Structure ===
        // [ < ] [ Tabs Scroll Area ] [ > ] [ + ] [ v ]
        this.tabBar = el("div", { class: "dashboard-tabbar" });
        // Scroll Controls
        const scrollLeftBtn = el("button", { class: "dashboard-tab-scroll-btn", title: "Scroll Left" }, "‹");
        const scrollRightBtn = el("button", { class: "dashboard-tab-scroll-btn", title: "Scroll Right" }, "›");
        // Tabs Container (Scrollable)
        const tabsWrapper = el("div", { class: "dashboard-tabs-wrapper" });
        this.tabStrip = el("div", { class: "dashboard-tabs" });
        tabsWrapper.appendChild(this.tabStrip);
        // Add Button
        this.addBtn = el("button", {
            class: "dashboard-tab-add",
            type: "button",
            title: "New dashboard"
        }, "+");
        // Overflow Menu (Chevron)
        const overflowBtn = el("button", { class: "dashboard-tab-overflow-btn", title: "All Dashboards" }, "⌄"); // or ☰ for burger
        // Responsive Burger Menu (Mobile only)
        // We reuse overflowBtn or create a separate one? User asked:
        // "collapse that (+) button inside a burger menu" in responsive.
        // "chevron menu... exactly like a Browser" for tabs.
        // Let's keep Chevron for Tab List, and use Media Queries to hide (+) and buttons.
        this.disposers.push(on(this.addBtn, "click", () => this.createDashboard()), on(scrollLeftBtn, "click", () => this.scrollTabs(-200)), on(scrollRightBtn, "click", () => this.scrollTabs(200)), on(overflowBtn, "click", (e) => this.showDashboardMenu(e)));
        this.tabBar.append(scrollLeftBtn, tabsWrapper, scrollRightBtn, this.addBtn, overflowBtn);
        // Content area
        this.content = el("div", { class: "dashboard-content" });
        this.el.append(this.tabBar, this.content);
        mount.appendChild(this.el);
        // Check scroll visibility on resize and mutation
        const checkScroll = () => {
            const hasOverflow = tabsWrapper.scrollWidth > tabsWrapper.clientWidth;
            scrollLeftBtn.style.display = hasOverflow ? "flex" : "none";
            scrollRightBtn.style.display = hasOverflow ? "flex" : "none";
            this.tabBar.classList.toggle("has-overflow", hasOverflow);
        };
        new ResizeObserver(checkScroll).observe(tabsWrapper);
        new MutationObserver(checkScroll).observe(this.tabStrip, { childList: true });
        // Inject styles for responsive and tab scrolling
        this.injectStyles();
    }
    scrollTabs(amount) {
        const wrapper = this.tabBar.querySelector(".dashboard-tabs-wrapper");
        if (wrapper)
            wrapper.scrollBy({ left: amount, behavior: "smooth" });
    }
    showDashboardMenu(e) {
        e.stopPropagation();
        const rect = e.currentTarget.getBoundingClientRect();
        const menu = el("div", { class: "dashboard-context-menu" });
        Object.assign(menu.style, {
            top: `${rect.bottom + 4}px`,
            right: `${window.innerWidth - rect.right}px`, // Align to right
            maxHeight: "300px",
            overflowY: "auto"
        });
        // 1. Add Dashboard (Visible in mobile mainly, or always handy)
        const addItem = el("div", { class: "dashboard-menu-item" }, "➕ New Dashboard");
        on(addItem, "click", () => {
            this.createDashboard();
            menu.remove();
        });
        menu.appendChild(addItem);
        const separator = el("div", { class: "dashboard-menu-separator" });
        menu.appendChild(separator);
        // 2. List of Dashboards
        this.dashboards.forEach((dash) => {
            const isActive = dash.id === this.activeId;
            const item = el("div", {
                class: `dashboard-menu-item ${isActive ? "active" : ""}`
            });
            item.innerHTML = `
            <span class="icon">${dash.getIcon()}</span>
            <span class="label">${dash.getTitle()}</span>
            ${isActive ? '<span class="check">✓</span>' : ''}
          `;
            on(item, "click", () => {
                this.activate(dash.id);
                menu.remove();
            });
            menu.appendChild(item);
        });
        document.body.appendChild(menu);
        document.body.appendChild(menu);
        const close = (evt) => {
            if (!evt.target.closest(".dashboard-context-menu")) {
                menu.remove();
                document.removeEventListener("pointerdown", close, true);
            }
        };
        // Defer to avoid immediate trigger
        setTimeout(() => document.addEventListener("pointerdown", close, true), 0);
    }
    injectStyles() {
        // Styles are now loaded via CSS import at the top of the file
        // This method is kept for backwards compatibility
    }
    // === Public API - Dashboard Container ===
    /**
     * Obtener todos los dashboards
     */
    getAllDashboards() {
        return Array.from(this.dashboards.values());
    }
    /**
     * Obtener dashboard por ID
     */
    getDashboard(id) {
        return this.dashboards.get(id);
    }
    /**
     * Obtener el dashboard activo
     */
    getActiveDashboard() {
        return this.activeId ? this.dashboards.get(this.activeId) : undefined;
    }
    /**
     * Obtener todos los widgets de todos los dashboards
     */
    getAllWidgets() {
        const widgets = [];
        for (const dash of this.dashboards.values()) {
            widgets.push(...dash.getWidgets());
        }
        return widgets;
    }
    /**
     * Buscar widget por ID en cualquier dashboard
     */
    findWidget(widgetId) {
        for (const dash of this.dashboards.values()) {
            const widget = dash.layout.getWidget(widgetId);
            if (widget) {
                return { widget, dashboard: dash };
            }
        }
        return null;
    }
    /**
     * Crear un nuevo dashboard vacío
     */
    createDashboard(options) {
        const count = this.dashboards.size + 1;
        const title = options?.title ?? `Dashboard ${count}`;
        const icon = options?.icon ?? "📊";
        return this.addDashboard({ title, icon, closable: true }, { grid: { cols: 12, rows: 12 } });
    }
    /**
     * Añadir dashboard con configuración completa
     */
    addDashboard(tab, view = {}) {
        const id = tab.id ?? uid("dash");
        if (this.dashboards.has(id)) {
            throw new Error(`Dashboard "${id}" already exists`);
        }
        const dash = new DashboardView(id, tab.title, tab.icon ?? "📊", view);
        this.dashboards.set(id, dash);
        this.content.appendChild(dash.el);
        // Crear tab button
        const tabEl = this.createTabElement(id, tab, view.layoutMode);
        this.tabStrip.appendChild(tabEl);
        // Activar si es el primero
        if (!this.activeId) {
            this.activate(id);
        }
        bus.emit("dashboard:added", { dashboard: dash });
        return dash;
    }
    /**
     * Remover dashboard
     */
    removeDashboard(id) {
        const dash = this.dashboards.get(id);
        if (!dash)
            return;
        dash.destroy();
        dash.el.remove();
        this.dashboards.delete(id);
        // Remover tab
        const tab = this.tabStrip.querySelector(`[data-dashboard-id="${id}"]`);
        tab?.remove();
        // Activar otro si era el activo
        if (this.activeId === id) {
            this.activeId = null;
            const first = this.dashboards.keys().next().value;
            if (first)
                this.activate(first);
        }
        bus.emit("dashboard:removed", { dashboard: dash });
    }
    /**
     * Activar dashboard por ID
     */
    activate(id) {
        if (!this.dashboards.has(id))
            return;
        this.activeId = id;
        // Update dashboard visibility
        for (const [dashId, dash] of this.dashboards) {
            dash.el.classList.toggle("is-active", dashId === id);
        }
        // Update tab styles
        this.tabStrip.querySelectorAll(".dashboard-tab").forEach(tab => {
            tab.classList.toggle("is-active", tab.dataset.dashboardId === id);
        });
        const dash = this.dashboards.get(id);
        bus.emit("dashboard:activated", { dashboard: dash });
    }
    /**
     * Iterar sobre dashboards
     */
    forEach(callback) {
        this.dashboards.forEach((dash, id) => callback(dash, id));
    }
    // === Private Methods ===
    createTabElement(id, tab, layoutMode = "grid") {
        const tabEl = el("button", {
            class: "dashboard-tab",
            type: "button",
            "data-dashboard-id": id
        });
        const icon = el("span", { class: "dashboard-tab-icon" }, tab.icon ?? "📊");
        const title = el("span", { class: "dashboard-tab-title" }, tab.title);
        const mode = el("span", { class: "dashboard-tab-mode", title: `Layout: ${layoutMode}` }, layoutMode === "dock" ? "⊞" : layoutMode === "free" ? "⊡" : "▦");
        const menu = el("button", {
            class: "dashboard-tab-menu",
            type: "button",
            title: "Menu"
        }, "⋮");
        const close = el("button", {
            class: "dashboard-tab-close",
            type: "button",
            title: "Close"
        }, "×");
        tabEl.append(icon, title, mode, menu);
        if (tab.closable !== false) {
            tabEl.appendChild(close);
        }
        // Click to activate
        this.disposers.push(on(tabEl, "click", (ev) => {
            const target = ev.target;
            if (target.closest(".dashboard-tab-close, .dashboard-tab-menu"))
                return;
            this.activate(id);
        }));
        // Close button
        this.disposers.push(on(close, "click", (ev) => {
            stop(ev);
            this.removeDashboard(id);
        }));
        // Menu button
        this.disposers.push(on(menu, "click", (ev) => {
            stop(ev);
            this.showTabMenu(menu, id);
        }));
        return tabEl;
    }
    showTabMenu(anchor, id) {
        document.querySelector(".dashboard-menu")?.remove();
        const menu = el("div", { class: "dashboard-menu", role: "menu" });
        const dash = this.dashboards.get(id);
        if (!dash)
            return;
        const items = [
            {
                label: "Rename...",
                action: async () => {
                    const newTitle = await InputModal.prompt({
                        title: "Rename Dashboard",
                        defaultValue: dash.getTitle(),
                        confirmLabel: "Rename"
                    });
                    if (newTitle) {
                        dash.setTitle(newTitle);
                        const titleEl = this.tabStrip.querySelector(`[data-dashboard-id="${id}"] .dashboard-tab-title`);
                        if (titleEl)
                            titleEl.textContent = newTitle;
                    }
                }
            },
            {
                label: "Add Widget ▸",
                action: () => {
                    this.showWidgetTypePicker(dash, menu);
                }
            },
            // Add "Change Layout" for dock mode only
            ...(dash.layoutMode === "dock" ? [{
                    label: "🗂️ Change Layout...",
                    action: async () => {
                        const { showLayoutPicker } = await import("./dock-layout-picker.js");
                        showLayoutPicker(dash.layout);
                    }
                }] : []),
            { divider: true },
            { label: `Mode: ${dash.getLayoutMode().toUpperCase()}`, disabled: true },
            { divider: true },
            { label: "▶ Slideshow", action: () => dash.enterSlideshow() },
            { divider: true },
            {
                label: "⚙️ Settings...",
                action: async () => {
                    const { openDashboardSettings } = await import("./dashboard-settings-modal.js");
                    openDashboardSettings(dash);
                }
            },
            { label: "🔄 Reset Layout", action: () => dash.resetLayout() },
        ];
        for (const item of items) {
            if (item.divider) {
                menu.appendChild(el("hr", { class: "dashboard-menu-divider" }));
                continue;
            }
            const { label, action } = item;
            const btn = el("button", { class: "dashboard-menu-item", type: "button" }, label);
            on(btn, "click", () => {
                action();
                menu.remove();
            });
            menu.appendChild(btn);
        }
        document.body.appendChild(menu);
        const rect = anchor.getBoundingClientRect();
        Object.assign(menu.style, {
            position: "fixed",
            top: cssPx(rect.bottom + 4),
            left: cssPx(rect.left),
            zIndex: "100000",
        });
        // Close on outside click
        const closeMenu = (e) => {
            if (!e.target.closest(".dashboard-menu")) {
                menu.remove();
                document.removeEventListener("pointerdown", closeMenu, true);
            }
        };
        setTimeout(() => {
            document.addEventListener("pointerdown", closeMenu, true);
        }, 0);
    }
    showWidgetTypePicker(dash, parentMenu) {
        // Create submenu for widget types
        const submenu = el("div", { class: "dashboard-menu dashboard-submenu" });
        Object.assign(submenu.style, {
            position: "fixed",
            background: "var(--surface-dim, #151525)",
            border: "1px solid var(--border, #333)",
            borderRadius: "8px",
            padding: "4px 0",
            minWidth: "160px",
            boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
            zIndex: "100001",
        });
        const rect = parentMenu.getBoundingClientRect();
        Object.assign(submenu.style, {
            top: cssPx(rect.top),
            left: cssPx(rect.right + 4),
        });
        const widgetTypes = [
            { label: "📦 Blank Widget", type: "blank" },
            { label: "🌐 IFrame Widget", type: "iframe" },
            { label: "🖼️ Image Widget", type: "image" },
            { label: "📺 YouTube Widget", type: "youtube" },
            { label: "🎥 Vimeo Widget", type: "vimeo" },
            { label: "📊 Vega Chart", type: "vega" },
            { label: "📈 ECharts Widget", type: "echarts" },
            { label: "📍 Leaflet Map", type: "leaflet" },
            { label: "📝 Markdown Widget", type: "markdown" },
            { label: "📰 HTML Widget", type: "html" },
            { label: "▦ AG Grid Table", type: "ag-grid" },
            { label: "📅 Grid.js Table", type: "grid-js" },
            { label: "🃏 KPI Cards (Sample)", type: "card-sample" },
        ];
        for (const item of widgetTypes) {
            const btn = el("button", { class: "dashboard-menu-item", type: "button" }, item.label);
            Object.assign(btn.style, {
                display: "block",
                width: "100%",
                padding: "8px 16px",
                background: "transparent",
                border: "none",
                color: "var(--text, #fff)",
                cursor: "pointer",
                textAlign: "left",
                fontSize: "13px",
            });
            on(btn, "click", async () => {
                submenu.remove();
                parentMenu.remove();
                const title = await InputModal.prompt({
                    title: "Widget Title",
                    message: item.type === "blank" ? "Enter a title for the new widget:" : `Enter a title for the new ${item.type} widget:`,
                    defaultValue: "New Widget",
                    confirmLabel: "Create"
                }) ?? "New Widget";
                // If user cancelled title prompt (returns null), maybe we should abort? 
                // User instruction said "requesting entry name... replace usage". 
                // Original code used `?? "New Widget"` so it defaulted if null was returned (cancel).
                // Wait, prompt returns null on cancel. 
                // Original code: prompt(...) ?? "New Widget"
                // So if I cancel, it creates a widget named "New Widget".
                // I should probably preserve that behavior or improve it. 
                // Let's preserve it for now, but really cancelling should abort.
                // Actually, if I look at line 1012: `prompt(...) ?? "New Widget"`.
                // If I cancel, I get "New Widget".
                // Wait, for the URLs, if I cancel, I might want to abort.
                // Line 1017: `prompt(...) ?? ""` -> url is empty string.
                let widget = null;
                // Logic to abort if title is null? Original didn't abort. 
                // But for InputModal, if I return null, it means cancel.
                // Let's stick to original logic: fallback to default if null.
                // But explicitly for the URL prompts, empty string might be weird.
                if (item.type === "iframe") {
                    const url = await InputModal.prompt({
                        title: "IFrame URL",
                        message: "Enter the URL to embed:",
                        defaultValue: "https://example.com",
                        placeholder: "https://..."
                    }) ?? "";
                    const { IFrameWidget } = await import("./iframe-widget.js");
                    widget = new IFrameWidget({ title, url });
                }
                else if (item.type === "image") {
                    const url = await InputModal.prompt({
                        title: "Image URL",
                        defaultValue: "https://via.placeholder.com/400"
                    }) ?? "";
                    const { ImageWidget } = await import("./image-widget.js");
                    widget = new ImageWidget({ title, url });
                }
                else if (item.type === "youtube") {
                    const url = await InputModal.prompt({
                        title: "YouTube Video",
                        message: "Enter YouTube URL or Video ID:",
                        defaultValue: "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                    }) ?? "";
                    const { YouTubeWidget } = await import("./youtube-widget.js");
                    widget = new YouTubeWidget({ title, url });
                }
                else if (item.type === "vimeo") {
                    const url = await InputModal.prompt({
                        title: "Vimeo Video",
                        message: "Enter Vimeo URL or Video ID:",
                        defaultValue: "https://vimeo.com/76979871"
                    }) ?? "";
                    const { VimeoWidget } = await import("./vimeo-widget.js");
                    widget = new VimeoWidget({ title, url });
                }
                else if (item.type === "vega") {
                    const { VegaWidget } = await import("./vega-widget.js");
                    widget = new VegaWidget({ title });
                }
                else if (item.type === "echarts") {
                    const { EChartsWidget } = await import("./echarts-widget.js");
                    widget = new EChartsWidget({ title });
                }
                else if (item.type === "leaflet") {
                    const { LeafletWidget } = await import("./leaflet-widget.js");
                    widget = new LeafletWidget({ title });
                }
                else if (item.type === "markdown") {
                    const { MarkdownWidget } = await import("./markdown-widget.js");
                    widget = new MarkdownWidget({ title });
                }
                else if (item.type === "html") {
                    const { HTMLWidget } = await import("./html-widget.js");
                    widget = new HTMLWidget({ title });
                }
                else if (item.type === "ag-grid") {
                    const { AgGridWidget } = await import("./ag-grid-widget.js");
                    widget = new AgGridWidget({ title });
                }
                else if (item.type === "grid-js") {
                    const { GridJsWidget } = await import("./grid-js-widget.js");
                    widget = new GridJsWidget({ title });
                }
                else if (item.type === "card-sample") {
                    const { CardWidget } = await import("./card-widget.js");
                    const cardWidget = new CardWidget({
                        title,
                        displayMode: "colored",
                        comparisonEnabled: true,
                        showProgressBar: true,
                        cards: [
                            { valueKey: "num_stores", title: "Number of Stores", format: "number", decimals: 0 },
                            { valueKey: "avg_acc_rev_trend", title: "Average Accs. Revenue Per Door", format: "currency", decimals: 2 },
                            { valueKey: "acc_to_goal", title: "Accs % To Goal", format: "percent", goal: 1.0 },
                            { valueKey: "avg_acc_qty_trend", title: "Avg. Accs Quantity per-Store", format: "number", decimals: 2 },
                            { valueKey: "avg_wearable_qty_trended", title: "Avg. Wearable quantity (trended)", format: "number", decimals: 2 }
                        ]
                    });
                    cardWidget.setData([{
                            "company_id": 1,
                            "territory_id": null,
                            "territory_name": null,
                            "description": "PROGRAM",
                            "num_stores": 474,
                            "avg_acc_rev_trend": 3241.451646,
                            "acc_to_goal": 0.64829,
                            "avg_acc_qty_trend": 226.721519,
                            "avg_wearable_qty_trended": 3.227848
                        }]);
                    widget = cardWidget;
                }
                else {
                    widget = new Widget({ title, icon: "📦" });
                }
                let placement;
                if (dash.layoutMode === "dock") {
                    placement = { dockPosition: "center" };
                }
                else if (dash.layoutMode === "free") {
                    placement = dash.layout.findFreeSpace(320, 240);
                }
                else {
                    placement = dash.layout.findFreeSpace(4, 4) ?? { row: 0, col: 0, rowSpan: 4, colSpan: 4 };
                }
                dash.addWidget(widget, placement);
            });
            on(btn, "mouseenter", () => btn.style.background = "var(--surface, #1a1a2e)");
            on(btn, "mouseleave", () => btn.style.background = "transparent");
            submenu.appendChild(btn);
        }
        document.body.appendChild(submenu);
        // Close submenu on outside click
        const closeSubmenu = (e) => {
            if (!e.target.closest(".dashboard-submenu")) {
                submenu.remove();
                document.removeEventListener("pointerdown", closeSubmenu, true);
            }
        };
        setTimeout(() => {
            document.addEventListener("pointerdown", closeSubmenu, true);
        }, 0);
    }
    destroy() {
        delete window.__dashboardContainer;
        for (const dash of this.dashboards.values()) {
            dash.destroy();
        }
        for (const d of this.disposers)
            d();
    }
}
//# sourceMappingURL=dashboard.js.map