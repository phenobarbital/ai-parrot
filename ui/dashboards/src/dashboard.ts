// dashboard.ts - Dashboard Container con API completa
import { el, on, stop, uid, cssPx, type Dispose } from "./utils.js";
import { bus } from "./events.js";
import { FreeLayout } from "./free-layout.js";
import { DockLayout } from "./dock-layout.js";
import { GridLayout } from "./grid-layout.js";
import { Widget } from "./widget.js";
import type { DashboardTabOptions, DashboardViewOptions, AnyPlacement } from "./types.js";

export { GridLayout, FreeLayout, DockLayout };

type LayoutEngine = GridLayout | FreeLayout | DockLayout;

// === Dashboard View (una pestaña individual) ===
export class DashboardView {
  readonly id: string;
  readonly el: HTMLElement;
  readonly header: HTMLElement;
  readonly main: HTMLElement;
  readonly footer: HTMLElement;
  readonly layout: LayoutEngine;
  readonly layoutMode: "grid" | "free" | "dock";

  private title: string;
  private icon: string;
  private disposers: Dispose[] = [];
  private slideshowState: SlideshowState | null = null;

  constructor(id: string, title: string, icon: string, opts: DashboardViewOptions) {
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
    } else if (this.layoutMode === "dock") {
      this.layout = new DockLayout(this, opts.dock);
    } else {
      this.layout = new GridLayout(this, opts.grid);
    }

    this.main.appendChild(this.layout.el);
  }

  getTitle(): string {
    return this.title;
  }

  setTitle(title: string): void {
    this.title = title;
  }

  getIcon(): string {
    return this.icon;
  }

  setIcon(icon: string): void {
    this.icon = icon;
  }

  getLayoutMode() {
    return this.layoutMode;
  }

  getWidgets(): Widget[] {
    return this.layout.getWidgets();
  }

  addWidget(widget: Widget, placement: AnyPlacement): void {
    // TypeScript doesn't unify the addWidget signatures perfectly automatically
    if (this.layout instanceof GridLayout) {
      this.layout.addWidget(widget, placement as any);
    } else if (this.layout instanceof FreeLayout) {
      this.layout.addWidget(widget, placement as any);
    } else if (this.layout instanceof DockLayout) {
      // DockLayout expects a string or DockPosition usually, but our interface is AnyPlacement
      // We'll trust the caller passes the right shape or the layout handles it
      // The placement for dock is usually just a string like 'center' in the demo loop
      // but `types.ts` defines AnyPlacement as object.
      // Let's assume placement is { dockPosition: ... } for dock mode
      const p = placement as { dockPosition: string };
      this.layout.addWidget(widget, p.dockPosition ?? "center");
    }
  }

  removeWidget(widget: Widget): void {
    this.layout.removeWidget(widget);
  }

  // === Slideshow Mode ===

  enterSlideshow(): void {
    const widgets = this.getWidgets();
    if (widgets.length === 0) return;

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
    const keyHandler = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft") this.slideshowPrev();
      else if (e.key === "ArrowRight") this.slideshowNext();
      else if (e.key === "Escape") this.exitSlideshow();
    };
    window.addEventListener("keydown", keyHandler);
    this.slideshowState.keyHandler = keyHandler;

    this.showSlideshowWidget(0);
    bus.emit("slideshow:start", { dashboard: this });
  }

  private showSlideshowWidget(index: number): void {
    if (!this.slideshowState) return;

    const { widgets, content, indicator } = this.slideshowState;
    const len = widgets.length;

    // Wrap index
    this.slideshowState.index = ((index % len) + len) % len;
    const widget = widgets[this.slideshowState.index];

    if (!widget) return;

    // Clear and show widget clone
    if (content) {
      content.innerHTML = "";

      const clone = el("div", { class: "slideshow-widget" });
      clone.innerHTML = `
        <div class="slideshow-widget-header">
          <span class="slideshow-icon">${widget.getIcon()}</span>
          <span class="slideshow-title">${widget.getTitle()}</span>
        </div>
        <div class="slideshow-widget-body">
          ${widget.el.querySelector(".widget-content")?.innerHTML ?? ""}
        </div>
      `;
      content.appendChild(clone);
    }

    if (indicator) {
      indicator.textContent = `${this.slideshowState.index + 1} / ${len}`;
    }
  }

  slideshowNext(): void {
    if (!this.slideshowState) return;
    this.showSlideshowWidget(this.slideshowState.index + 1);
  }

  slideshowPrev(): void {
    if (!this.slideshowState) return;
    this.showSlideshowWidget(this.slideshowState.index - 1);
  }

  exitSlideshow(): void {
    if (!this.slideshowState) return;

    if (this.slideshowState.keyHandler) {
      window.removeEventListener("keydown", this.slideshowState.keyHandler);
    }
    this.slideshowState.overlay?.remove();
    this.slideshowState = null;

    bus.emit("slideshow:end", { dashboard: this });
  }

  destroy(): void {
    this.exitSlideshow();
    this.layout.destroy();
    for (const d of this.disposers) d();
  }
}

interface SlideshowState {
  index: number;
  widgets: Widget[];
  keyHandler: ((e: KeyboardEvent) => void) | null;
  overlay: HTMLElement | null;
  content?: HTMLElement;
  indicator?: HTMLElement;
}

// === Dashboard Container (contenedor de todas las pestañas) ===
export class DashboardContainer {
  readonly el: HTMLElement;
  private readonly tabBar: HTMLElement;
  private readonly tabStrip: HTMLElement;
  private readonly addBtn: HTMLElement;
  private readonly content: HTMLElement;

  private readonly dashboards = new Map<string, DashboardView>();
  private activeId: string | null = null;
  private disposers: Dispose[] = [];

  constructor(mount: HTMLElement) {
    // Registrar globalmente para que los widgets puedan encontrarlo
    (window as any).__dashboardContainer = this;

    this.el = el("div", { class: "dashboard-container" });

    // Tab bar
    this.tabBar = el("div", { class: "dashboard-tabbar" });
    this.tabStrip = el("div", { class: "dashboard-tabs" });
    this.addBtn = el("button", {
      class: "dashboard-tab-add",
      type: "button",
      title: "New dashboard"
    }, "+");

    this.disposers.push(
      on(this.addBtn, "click", () => this.createDashboard())
    );

    this.tabBar.append(this.tabStrip, this.addBtn);

    // Content area
    this.content = el("div", { class: "dashboard-content" });

    this.el.append(this.tabBar, this.content);
    mount.appendChild(this.el);
  }

  // === Public API - Dashboard Container ===

  /**
   * Obtener todos los dashboards
   */
  getAllDashboards(): DashboardView[] {
    return Array.from(this.dashboards.values());
  }

  /**
   * Obtener dashboard por ID
   */
  getDashboard(id: string): DashboardView | undefined {
    return this.dashboards.get(id);
  }

  /**
   * Obtener el dashboard activo
   */
  getActiveDashboard(): DashboardView | undefined {
    return this.activeId ? this.dashboards.get(this.activeId) : undefined;
  }

  /**
   * Obtener todos los widgets de todos los dashboards
   */
  getAllWidgets(): Widget[] {
    const widgets: Widget[] = [];
    for (const dash of this.dashboards.values()) {
      widgets.push(...dash.getWidgets());
    }
    return widgets;
  }

  /**
   * Buscar widget por ID en cualquier dashboard
   */
  findWidget(widgetId: string): { widget: Widget; dashboard: DashboardView } | null {
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
  createDashboard(options?: { title?: string; icon?: string }): DashboardView {
    const count = this.dashboards.size + 1;
    const title = options?.title ?? `Dashboard ${count}`;
    const icon = options?.icon ?? "📊";

    return this.addDashboard(
      { title, icon, closable: true },
      { grid: { cols: 12, rows: 12 } }
    );
  }

  /**
   * Añadir dashboard con configuración completa
   */
  addDashboard(tab: DashboardTabOptions, view: DashboardViewOptions = {}): DashboardView {
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
  removeDashboard(id: string): void {
    const dash = this.dashboards.get(id);
    if (!dash) return;

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
      if (first) this.activate(first);
    }

    bus.emit("dashboard:removed", { dashboard: dash });
  }

  /**
   * Activar dashboard por ID
   */
  activate(id: string): void {
    if (!this.dashboards.has(id)) return;

    this.activeId = id;

    // Update dashboard visibility
    for (const [dashId, dash] of this.dashboards) {
      dash.el.classList.toggle("is-active", dashId === id);
    }

    // Update tab styles
    this.tabStrip.querySelectorAll<HTMLElement>(".dashboard-tab").forEach(tab => {
      tab.classList.toggle("is-active", tab.dataset.dashboardId === id);
    });

    const dash = this.dashboards.get(id)!;
    bus.emit("dashboard:activated", { dashboard: dash });
  }

  /**
   * Iterar sobre dashboards
   */
  forEach(callback: (dashboard: DashboardView, id: string) => void): void {
    this.dashboards.forEach((dash, id) => callback(dash, id));
  }

  // === Private Methods ===

  private createTabElement(id: string, tab: DashboardTabOptions, layoutMode: string = "grid"): HTMLElement {
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
    this.disposers.push(
      on(tabEl, "click", (ev) => {
        const target = ev.target as HTMLElement;
        if (target.closest(".dashboard-tab-close, .dashboard-tab-menu")) return;
        this.activate(id);
      })
    );

    // Close button
    this.disposers.push(
      on(close, "click", (ev) => {
        stop(ev);
        this.removeDashboard(id);
      })
    );

    // Menu button
    this.disposers.push(
      on(menu, "click", (ev) => {
        stop(ev);
        this.showTabMenu(menu, id);
      })
    );

    return tabEl;
  }

  private showTabMenu(anchor: HTMLElement, id: string): void {
    document.querySelector(".dashboard-menu")?.remove();

    const menu = el("div", { class: "dashboard-menu", role: "menu" });
    const dash = this.dashboards.get(id);
    if (!dash) return;

    const items = [
      {
        label: "Rename...",
        action: () => {
          const newTitle = prompt("Dashboard name:", dash.getTitle());
          if (newTitle) {
            dash.setTitle(newTitle);
            const titleEl = this.tabStrip.querySelector(
              `[data-dashboard-id="${id}"] .dashboard-tab-title`
            );
            if (titleEl) titleEl.textContent = newTitle;
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
          showLayoutPicker(dash.layout as any);
        }
      }] : []),
      { divider: true },
      { label: `Mode: ${dash.getLayoutMode().toUpperCase()}`, disabled: true } as any,
      { divider: true },
      { label: "▶ Slideshow", action: () => dash.enterSlideshow() },
      { divider: true },
      { label: "Reset Layout", action: () => dash.layout.reset() },
    ];

    for (const item of items) {
      if ((item as { divider?: boolean }).divider) {
        menu.appendChild(el("hr", { class: "dashboard-menu-divider" }));
        continue;
      }

      const { label, action } = item as { label: string; action: () => void };
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
    const closeMenu = (e: Event) => {
      if (!(e.target as HTMLElement).closest(".dashboard-menu")) {
        menu.remove();
        document.removeEventListener("pointerdown", closeMenu, true);
      }
    };
    setTimeout(() => {
      document.addEventListener("pointerdown", closeMenu, true);
    }, 0);
  }

  private showWidgetTypePicker(dash: DashboardView, parentMenu: HTMLElement): void {
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
      { label: "▦ AG Grid Table", type: "ag-grid" },
      { label: "📅 Grid.js Table", type: "grid-js" },
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

        const title = prompt("Widget title:", item.type === "blank" ? "New Widget" : `New ${item.type} Widget`) ?? "New Widget";

        let widget: Widget;

        if (item.type === "iframe") {
          const url = prompt("Enter URL:", "https://example.com") ?? "";
          const { IFrameWidget } = await import("./iframe-widget.js");
          widget = new IFrameWidget({ title, url });
        } else if (item.type === "image") {
          const url = prompt("Enter image URL:", "https://via.placeholder.com/400") ?? "";
          const { ImageWidget } = await import("./image-widget.js");
          widget = new ImageWidget({ title, url });
        } else if (item.type === "youtube") {
          const url = prompt("Enter YouTube URL or Video ID:", "https://www.youtube.com/watch?v=dQw4w9WgXcQ") ?? "";
          const { YouTubeWidget } = await import("./youtube-widget.js");
          widget = new YouTubeWidget({ title, url });
        } else if (item.type === "vimeo") {
          const url = prompt("Enter Vimeo URL or Video ID:", "https://vimeo.com/76979871") ?? "";
          const { VimeoWidget } = await import("./vimeo-widget.js");
          widget = new VimeoWidget({ title, url });
        } else if (item.type === "vega") {
          const { VegaWidget } = await import("./vega-widget.js");
          widget = new VegaWidget({ title });
        } else if (item.type === "echarts") {
          const { EChartsWidget } = await import("./echarts-widget.js");
          widget = new EChartsWidget({ title });
        } else if (item.type === "leaflet") {
          const { LeafletWidget } = await import("./leaflet-widget.js");
          widget = new LeafletWidget({ title });
        } else if (item.type === "markdown") {
          const { MarkdownWidget } = await import("./markdown-widget.js");
          widget = new MarkdownWidget({ title });
        } else if (item.type === "ag-grid") {
          const { AgGridWidget } = await import("./ag-grid-widget.js");
          widget = new AgGridWidget({ title });
        } else if (item.type === "grid-js") {
          const { GridJsWidget } = await import("./grid-js-widget.js");
          widget = new GridJsWidget({ title });
        } else {
          widget = new Widget({ title, icon: "📦" });
        }

        let placement: any;
        if (dash.layoutMode === "dock") {
          placement = { dockPosition: "center" };
        } else if (dash.layoutMode === "free") {
          placement = (dash.layout as FreeLayout).findFreeSpace(320, 240);
        } else {
          placement = (dash.layout as GridLayout).findFreeSpace(4, 4) ?? { row: 0, col: 0, rowSpan: 4, colSpan: 4 };
        }

        dash.addWidget(widget, placement);
      });

      on(btn, "mouseenter", () => btn.style.background = "var(--surface, #1a1a2e)");
      on(btn, "mouseleave", () => btn.style.background = "transparent");

      submenu.appendChild(btn);
    }

    document.body.appendChild(submenu);

    // Close submenu on outside click
    const closeSubmenu = (e: Event) => {
      if (!(e.target as HTMLElement).closest(".dashboard-submenu")) {
        submenu.remove();
        document.removeEventListener("pointerdown", closeSubmenu, true);
      }
    };
    setTimeout(() => {
      document.addEventListener("pointerdown", closeSubmenu, true);
    }, 0);
  }

  destroy(): void {
    delete (window as any).__dashboardContainer;
    for (const dash of this.dashboards.values()) {
      dash.destroy();
    }
    for (const d of this.disposers) d();
  }
}