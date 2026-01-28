// widget.ts - Widget con dock corregido y responsive
import { clamp, cssPx, el, on, stop, storage, uid, type Dispose } from "./utils.js";
import { bus } from "./events.js";
import type { DashboardView } from "./dashboard.js";
import type { Placement, WidgetOptions, WidgetState, ToolbarButton, AnyPlacement } from "./types.js";

type WidgetMode = "docked" | "floating" | "maximized";

export class Widget {
  readonly id: string;
  readonly el: HTMLElement;

  protected readonly opts: WidgetOptions;
  protected readonly titleBar: HTMLElement;
  protected readonly titleText: HTMLElement;
  protected readonly toolbar: HTMLElement;
  protected readonly burgerBtn: HTMLElement;
  protected readonly headerSection: HTMLElement;
  protected readonly contentSection: HTMLElement;
  protected readonly footerSection: HTMLElement;
  protected readonly resizeHandle: HTMLElement;

  protected dashboard: DashboardView | null = null;
  protected placement: AnyPlacement | null = null;
  protected mode: WidgetMode = "docked";
  protected minimized = false;

  // Para restaurar estado al re-dockear
  protected lastDocked: { dashboard: DashboardView; placement: AnyPlacement } | null = null;
  protected floatingStyles: { left: string; top: string; width: string; height: string } | null = null;

  protected disposers: Dispose[] = [];
  protected stateRestored = false;

  protected customToolbarButtons: ToolbarButton[] = [];
  protected customConfigTabs: import("./widget-config-modal.js").ConfigTab[] = [];

  constructor(opts: WidgetOptions) {
    this.opts = opts;
    this.id = opts.id ?? uid("widget");

    // Crear estructura del widget
    this.el = el("article", {
      class: "widget",
      "data-widget-id": this.id
    });

    // Title bar con icono, título, y toolbar
    this.titleBar = el("header", { class: "widget-titlebar" });

    const iconEl = el("span", { class: "widget-icon" }, opts.icon ?? "▣");
    this.titleText = el("span", { class: "widget-title" }, opts.title);

    // Burger menu para modo responsive
    this.burgerBtn = el("button", {
      class: "widget-burger",
      type: "button",
      title: "Menu",
      "aria-label": "Widget menu"
    }, "☰");

    this.toolbar = el("div", { class: "widget-toolbar" });

    const titleGroup = el("div", { class: "widget-title-group" });
    titleGroup.append(iconEl, this.titleText);

    const actionsGroup = el("div", { class: "widget-actions" });
    actionsGroup.append(this.toolbar, this.burgerBtn);

    this.titleBar.append(titleGroup, actionsGroup);

    // Secciones de contenido
    this.headerSection = el("div", { class: "widget-header" });
    this.contentSection = el("div", { class: "widget-content" });
    this.footerSection = el("div", { class: "widget-footer" });

    this.setSection(this.headerSection, opts.header);
    this.setSection(this.contentSection, opts.content);
    this.setSection(this.footerSection, opts.footer);

    // Resize handle
    this.resizeHandle = el("div", {
      class: "widget-resize-handle",
      title: "Resize"
    });

    this.el.append(
      this.titleBar,
      this.headerSection,
      this.contentSection,
      this.footerSection,
      this.resizeHandle
    );

    // Apply is_system flag
    if (opts.is_system) {
      this.el.classList.add("is-system");
      // Force closable to false for system widgets
      this.opts.closable = false;
    }

    // Apply is_minimal flag
    if (opts.is_minimal) {
      this.el.classList.add("is-minimal");
      this.titleBar.style.display = "none";
    }

    this.buildToolbar();
    this.setupInteractions();

    // Init Styles
    if (opts.titleColor) this.setTitleColor(opts.titleColor);
    if (opts.titleBackground) this.setTitleBackground(opts.titleBackground);

    // Lifecycle hook: initialization complete
    this.onInit();
  }

  // === Lifecycle Hooks (override in subclasses) ===

  /** Called after widget is fully constructed. Override in subclasses. */
  protected onInit(): void { }

  /** Called before widget is destroyed. Override in subclasses. */
  protected onDestroy(): void { }

  /** Called before refresh starts. Override in subclasses. */
  protected onRefresh(): void { }

  /** Called after refresh completes. Override in subclasses. */
  protected onReload(): void { }

  /** Called when configuration is saved. Override in subclasses. */
  protected onConfigSave(config: Record<string, unknown>): void {
    // Apply common config changes
    if (typeof config.title === "string") this.setTitle(config.title);
    if (typeof config.icon === "string") this.setIcon(config.icon);

    // Style settings via config
    if (config.style && typeof config.style === "object") {
      const style = config.style as any;
      if (typeof style.titleColor === "string") this.setTitleColor(style.titleColor);
      if (typeof style.titleBackground === "string") this.setTitleBackground(style.titleBackground);
    }

    // Behavior
    if (typeof config.closable === "boolean") {
      this.opts.closable = config.closable;
      this.buildToolbar(); // Rebuild to toggle close button
    }

    if (typeof config.is_system === "boolean") {
      this.opts.is_system = config.is_system;
      this.el.classList.toggle("is-system", this.opts.is_system);
      // Force closable to false if system
      if (this.opts.is_system) {
        this.opts.closable = false;
      }
      this.buildToolbar();
    }
  }

  // === Getters & Setters ===

  getTitle(): string {
    return this.titleText.textContent ?? this.opts.title;
  }

  setTitle(title: string): void {
    this.titleText.textContent = title;
  }

  getIcon(): string {
    return this.opts.icon ?? "▣";
  }

  setIcon(icon: string): void {
    const iconEl = this.titleBar.querySelector(".widget-icon");
    if (iconEl) iconEl.textContent = icon;
    this.opts.icon = icon;
  }

  setTitleColor(color: string): void {
    this.titleText.style.color = color;
    (this.titleBar.querySelector(".widget-icon") as HTMLElement).style.color = color;
    this.opts.titleColor = color;
  }

  getTitleColor(): string {
    return this.opts.titleColor ?? "";
  }

  setTitleBackground(color: string): void {
    // Create a linear-gradient from the selected color (lighter at top, darker at bottom)
    // This overrides any existing CSS gradient
    const gradient = `linear-gradient(to bottom, ${color}, ${this.darkenColor(color, 15)})`;
    this.titleBar.style.background = gradient;
    this.titleBar.style.backgroundImage = gradient; // Ensure gradient takes precedence
    this.opts.titleBackground = color;
  }

  /** Helper to darken a hex color by a percentage */
  private darkenColor(hex: string, percent: number): string {
    // Remove # if present
    hex = hex.replace(/^#/, '');

    // Parse RGB
    let r = parseInt(hex.substring(0, 2), 16);
    let g = parseInt(hex.substring(2, 4), 16);
    let b = parseInt(hex.substring(4, 6), 16);

    // Darken
    r = Math.max(0, Math.floor(r * (1 - percent / 100)));
    g = Math.max(0, Math.floor(g * (1 - percent / 100)));
    b = Math.max(0, Math.floor(b * (1 - percent / 100)));

    // Convert back to hex
    return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
  }

  getTitleBackground(): string {
    return this.opts.titleBackground ?? "";
  }

  isClosable(): boolean {
    return this.opts.closable !== false; // Default true if undefined
  }

  isSystem(): boolean {
    return !!this.opts.is_system;
  }

  /** Get configuration tabs for this widget. Override in subclasses to add tabs. */
  getConfigTabs(): import("./widget-config-modal.js").ConfigTab[] {
    return [];
  }

  /** Open the settings modal */
  async openSettings(): Promise<void> {
    const { openWidgetConfig } = await import("./widget-config-modal.js");
    // Merge dynamically added tabs with class-defined tabs
    const allTabs = [
      ...this.customConfigTabs,
      ...this.getConfigTabs()
    ];
    openWidgetConfig(this, allTabs);
  }

  /** Add a custom button to the toolbar */
  addToolbarButton(btn: ToolbarButton): void {
    this.customToolbarButtons.push(btn);
    this.renderToolbar();
  }

  /** Remove a custom toolbar button by ID */
  removeToolbarButton(id: string): void {
    const index = this.customToolbarButtons.findIndex(b => b.id === id);
    if (index !== -1) {
      this.customToolbarButtons.splice(index, 1);
      this.renderToolbar();
    }
  }

  /** Add a custom configuration tab */
  addConfigTab(tab: import("./widget-config-modal.js").ConfigTab): void {
    this.customConfigTabs.push(tab);
  }

  /** Remove a custom configuration tab by ID */
  removeConfigTab(id: string): void {
    const index = this.customConfigTabs.findIndex(t => t.id === id);
    if (index !== -1) {
      this.customConfigTabs.splice(index, 1);
    }
  }



  getDashboard(): DashboardView | null {
    return this.dashboard;
  }

  getPlacement(): AnyPlacement | null {
    return this.placement;
  }

  isFloating(): boolean {
    return this.mode === "floating";
  }

  isMaximized(): boolean {
    return this.mode === "maximized";
  }

  isDocked(): boolean {
    return this.mode === "docked";
  }

  isMinimized(): boolean {
    return this.minimized;
  }

  // === Setters (used by layout) ===

  setDocked(dashboard: DashboardView, placement: AnyPlacement): void {
    this.dashboard = dashboard;
    this.placement = placement; // No spread if AnyPlacement is union
    this.mode = "docked";

    // Guardar para poder re-dockear
    this.lastDocked = { dashboard, placement: placement };

    // Limpiar estilos de floating/maximized
    this.el.classList.remove("is-floating", "is-maximized");
    this.el.style.position = "";
    this.el.style.left = "";
    this.el.style.top = "";
    this.el.style.width = "";
    this.el.style.height = "";
    this.el.style.zIndex = "";
  }

  setPlacement(placement: AnyPlacement): void {
    this.placement = placement;
    if (this.lastDocked) {
      this.lastDocked.placement = placement;
    }
  }

  setContent(content: string | HTMLElement): void {
    this.setSection(this.contentSection, content);
  }

  // === Public Actions ===

  toggleMinimize(): void {
    this.minimized = !this.minimized;
    this.el.classList.toggle("is-minimized", this.minimized);
    bus.emit("widget:minimized", { widget: this });
    this.saveState();
  }

  float(): void {
    // Si ya está flotando, no hacer nada
    if (this.isFloating()) return;

    // Si está maximizado, primero restaurar
    if (this.isMaximized()) {
      this.restore();
    }

    // Guardar posición actual antes de flotar
    if (this.dashboard && this.placement) {
      this.lastDocked = {
        dashboard: this.dashboard,
        placement: this.placement
      };
    }

    // Obtener rect actual para posicionar
    const rect = this.el.getBoundingClientRect();

    // Mover al body
    document.body.appendChild(this.el);

    this.mode = "floating";
    this.el.classList.add("is-floating");
    this.el.classList.remove("is-maximized");

    // Aplicar estilos de floating
    Object.assign(this.el.style, {
      position: "fixed",
      left: cssPx(rect.left),
      top: cssPx(rect.top),
      width: cssPx(Math.max(280, rect.width)),
      height: cssPx(Math.max(200, rect.height)),
      zIndex: "9999",
    });

    // Guardar estilos floating para persistencia
    this.floatingStyles = {
      left: this.el.style.left,
      top: this.el.style.top,
      width: this.el.style.width,
      height: this.el.style.height,
    };

    bus.emit("widget:floated", { widget: this });
    this.saveState();
    this.renderToolbar();
  }

  /**
   * DOCK CORREGIDO: Ahora siempre tiene un destino
   */
  dock(): void {
    if (!this.isFloating() && !this.isMaximized()) return;

    // Buscar dónde re-dockear
    let targetDash = this.lastDocked?.dashboard ?? this.dashboard;
    let targetPlacement = this.lastDocked?.placement ?? this.placement;

    // Si no hay destino guardado, buscar el dashboard activo
    if (!targetDash) {
      // Importación dinámica para evitar circular dependency
      const container = (window as any).__dashboardContainer;
      if (container) {
        targetDash = container.getActiveDashboard();
      }
    }

    // Si aún no hay dashboard, no podemos dockear
    if (!targetDash) {
      console.warn("No dashboard available to dock widget");
      return;
    }

    // Si no hay placement, encontrar espacio libre
    if (!targetPlacement) {
      targetPlacement = targetDash.layout.findFreeSpace(4, 4) ??
        { row: 0, col: 0, rowSpan: 4, colSpan: 4 };
    }

    // Remover del body
    this.el.remove();

    // Limpiar estilos floating
    this.el.classList.remove("is-floating", "is-maximized");
    Object.assign(this.el.style, {
      left: "",
      top: "",
      width: "",
      height: "",
      zIndex: "",
    });
    console.log(`[Widget] setDocked: ${this.id}`, { style: this.el.style.cssText });

    // Re-agregar al layout
    this.mode = "docked";

    // CRITICAL: Restore dimensions for FreeLayout
    // addWidget typically resets to default if we don't pass full info.
    // targetPlacement should already have the correct Width/Height if it came from FreeLayout state
    targetDash.addWidget(this, targetPlacement);

    bus.emit("widget:docked", {
      widget: this,
      dashboard: targetDash,
      placement: targetPlacement
    });

    this.saveState();
    this.renderToolbar();
  }

  toggleFloating(): void {
    if (this.isFloating()) {
      this.dock();
    } else {
      this.float();
    }
  }

  maximize(): void {
    if (this.isMaximized()) return;

    // Guardar estado actual
    if (this.isFloating()) {
      this.floatingStyles = {
        left: this.el.style.left,
        top: this.el.style.top,
        width: this.el.style.width,
        height: this.el.style.height,
      };
    } else if (this.dashboard && this.placement) {
      this.lastDocked = {
        dashboard: this.dashboard,
        placement: this.placement,
      };
      // Ensure we don't accidentally treat it as "was floating"
      this.floatingStyles = null;
    }

    // Mover al body si no está ahí
    if (!this.el.parentElement || this.el.parentElement !== document.body) {
      document.body.appendChild(this.el);
    }

    this.mode = "maximized";
    this.el.classList.add("is-maximized");
    this.el.classList.remove("is-floating");

    Object.assign(this.el.style, {
      position: "fixed",
      left: "0",
      top: "0",
      width: "100vw",
      height: "100vh",
      zIndex: "10000",
    });

    bus.emit("widget:maximized", { widget: this });
    this.saveState();
    this.renderToolbar();
  }

  restore(): void {
    if (!this.isMaximized()) return;

    this.el.classList.remove("is-maximized");

    // Decidir si restaurar a floating o docked

    // PRIORITY: If we have a last docked state, go back there.
    // Maximized widgets should usually return to their docked state unless they were floating before maximizing.
    // But even if floating, if they have a dock parent, we might want to dock?
    // Let's track "wasFloating" specifically?
    // Actually, `floatingStyles` is set when we float.
    // unique issue: `maximize` sets `floatingStyles` if floating, OR `lastDocked` if docked.

    if (this.lastDocked && this.mode === "maximized" && !this.floatingStyles) {
      // It was docked, then maximized. Restore to dock.
      this.dock();
    } else if (this.floatingStyles) {
      // Restore to floating
      this.mode = "floating";
      this.el.classList.add("is-floating");
      Object.assign(this.el.style, this.floatingStyles);
      this.el.style.zIndex = "9999";
    } else if (this.lastDocked) {
      // Fallback: If no floating styles but lastDocked exists, dock it.
      this.dock();
    } else {
      // Fallback: floating center
      this.mode = "floating";
      this.el.classList.add("is-floating");
      Object.assign(this.el.style, {
        position: "fixed",
        left: "50%",
        top: "50%",
        transform: "translate(-50%, -50%)",
        width: "400px",
        height: "300px",
        zIndex: "9999",
      });
    }

    bus.emit("widget:restored", { widget: this });
    this.saveState();
    this.renderToolbar();
  }

  async refresh(): Promise<void> {
    if (!this.opts.onRefresh) return;

    this.onRefresh(); // Lifecycle hook: before refresh
    this.el.classList.add("is-refreshing");
    try {
      await this.opts.onRefresh(this);
    } finally {
      this.el.classList.remove("is-refreshing");
      this.onReload(); // Lifecycle hook: after refresh
    }
  }

  close(): void {
    this.opts.onClose?.(this);

    // If docked, remove from layout
    if (this.dashboard) {
      this.dashboard.layout.removeWidget(this);
    }
    // If floating/maximized, it might not have 'this.dashboard' set (it's null when floating)
    // But we might have 'lastDocked' which holds the original dashboard reference
    else if (this.lastDocked?.dashboard) {
      this.lastDocked.dashboard.layout.removeWidget(this);
    }

    storage.remove(this.storageKey());
    this.destroy();
    this.el.remove();
  }

  openInNewWindow(): void {
    const win = window.open("", "_blank", "width=720,height=480");
    if (!win) return;

    // Copiar estilos
    const styles = Array.from(document.styleSheets)
      .map(sheet => {
        try {
          return Array.from(sheet.cssRules ?? [])
            .map(rule => rule.cssText)
            .join("\n");
        } catch {
          return "";
        }
      })
      .join("\n");

    win.document.write(`
      <!DOCTYPE html>
      <html>
        <head>
          <title>${this.getTitle()}</title>
          <style>${styles}</style>
        </head>
        <body class="widget-popup-body">
          ${this.el.outerHTML}
        </body>
      </html>
    `);
    win.document.close();
  }

  // === Private Methods ===

  private setSection(section: HTMLElement, content?: string | HTMLElement): void {
    section.innerHTML = "";
    if (!content) {
      section.style.display = "none";
      return;
    }
    section.style.display = "";
    if (typeof content === "string") {
      section.innerHTML = content;
    } else {
      section.appendChild(content);
    }
  }

  private buildToolbar(): void {
    const defaultButtons: ToolbarButton[] = [
      {
        id: "minimize",
        title: this.minimized ? "Restore" : "Minimize",
        icon: "−",
        onClick: () => this.toggleMinimize(),
        visible: () => this.opts.minimizable !== false,
      },
      {
        id: "maximize",
        title: "Maximize",
        icon: "□",
        onClick: () => this.maximize(),
        visible: () => !this.isMaximized() && this.opts.maximizable !== false,
      },
      {
        id: "restore",
        title: "Restore",
        icon: "❐",
        onClick: () => this.restore(),
        visible: () => this.isMaximized(),
      },
      {
        id: "float",
        title: this.isFloating() ? "Dock" : "Float",
        icon: this.isFloating() ? "⊡" : "⊟",
        onClick: () => this.toggleFloating(),
        visible: () => this.opts.floatable !== false,
      },
      {
        id: "refresh",
        title: "Refresh",
        icon: "↻",
        onClick: () => void this.refresh(),
        visible: () => !!this.opts.onRefresh,
      },
      {
        id: "popout",
        title: "Open in new window",
        icon: "↗",
        onClick: () => this.openInNewWindow(),
        visible: () => true,
      },
      {
        id: "settings",
        title: "Settings",
        icon: "⚙",
        onClick: () => void this.openSettings(),
        visible: () => true,
      },
      {
        id: "close",
        title: "Close",
        icon: "×",
        onClick: () => this.close(),
        visible: () => this.opts.closable !== false,
      },
    ];

    this.renderToolbar(defaultButtons);
  }

  private renderToolbar(buttons?: ToolbarButton[]): void {
    const allButtons = buttons ?? this.getToolbarButtons();

    this.toolbar.innerHTML = "";
    for (const btn of allButtons) {
      if (btn.visible && !btn.visible(this)) continue;

      const button = el("button", {
        class: "widget-toolbtn",
        type: "button",
        title: btn.title,
        "data-btn-id": btn.id,
      }, btn.icon);

      this.disposers.push(
        on(button, "click", (ev: Event) => {
          stop(ev);
          btn.onClick(this);
          this.renderToolbar();
        })
      );

      this.toolbar.appendChild(button);
    }
  }

  private getToolbarButtons(): ToolbarButton[] {
    return [
      {
        id: "minimize",
        title: this.minimized ? "Restore" : "Minimize",
        icon: "−",
        onClick: () => this.toggleMinimize(),
        visible: () => this.opts.minimizable !== false,
      },
      {
        id: "maximize",
        title: "Maximize",
        icon: "□",
        onClick: () => this.maximize(),
        visible: () => !this.isMaximized() && this.opts.maximizable !== false,
      },
      {
        id: "restore",
        title: "Restore",
        icon: "❐",
        onClick: () => this.restore(),
        visible: () => this.isMaximized(),
      },
      {
        id: "float",
        title: this.isFloating() ? "Dock" : "Float",
        icon: this.isFloating() ? "⊡" : "⊟",
        onClick: () => this.toggleFloating(),
        visible: () => this.opts.floatable !== false,
      },
      {
        id: "refresh",
        title: "Refresh",
        icon: "↻",
        onClick: () => void this.refresh(),
        visible: () => !!this.opts.onRefresh,
      },
      {
        id: "popout",
        title: "Open in new window",
        icon: "↗",
        onClick: () => this.openInNewWindow(),
        visible: () => true,
      },
      {
        id: "settings",
        title: "Settings",
        icon: "⚙",
        onClick: () => void this.openSettings(),
        visible: () => !this.opts.is_system,
      },
      {
        id: "close",
        title: "Close",
        icon: "×",
        onClick: () => this.close(),
        visible: () => this.opts.closable !== false && !this.opts.is_system,
      },
      ...this.customToolbarButtons,
      ...(this.opts.toolbar ?? []),
    ];
  }

  private setupInteractions(): void {
    // Drag desde titlebar (or body for minimal mode)
    if (this.opts.draggable !== false) {
      // For minimal mode, drag from the content section (body)
      const dragTarget = this.opts.is_minimal ? this.contentSection : this.titleBar;

      this.disposers.push(
        on(dragTarget, "pointerdown", (ev: PointerEvent) => {
          const target = ev.target as HTMLElement;
          // Don't start drag if clicking on interactive elements
          if (target.closest("button, input, select, textarea, a, [contenteditable]")) return;

          if (this.isMaximized()) return;

          if (this.isFloating()) {
            this.beginFloatingDrag(ev);
          } else if (this.dashboard) {
            this.dashboard.layout.beginDrag(this, ev);
          }
        })
      );
    }

    // Resize
    if (this.opts.resizable !== false) {
      this.disposers.push(
        on(this.resizeHandle, "pointerdown", (ev: PointerEvent) => {
          if (this.isMaximized()) return;

          if (this.isFloating()) {
            this.beginFloatingResize(ev);
          } else if (this.dashboard) {
            this.dashboard.layout.beginResize(this, ev);
          }
        })
      );
    }

    // Burger menu
    this.disposers.push(
      on(this.burgerBtn, "click", (ev: Event) => {
        stop(ev);
        this.showBurgerMenu();
      })
    );

    // Double-click para maximize/restore
    this.disposers.push(
      on(this.titleBar, "dblclick", (ev: Event) => {
        const target = ev.target as HTMLElement;
        if (target.closest("button")) return;

        if (this.isMaximized()) {
          this.restore();
        } else {
          this.maximize();
        }
      })
    );
  }

  private beginFloatingDrag(ev: PointerEvent): void {
    stop(ev);

    const startX = ev.clientX;
    const startY = ev.clientY;
    const rect = this.el.getBoundingClientRect();
    const offsetX = startX - rect.left;
    const offsetY = startY - rect.top;

    const onMove = (e: PointerEvent) => {
      this.el.style.left = cssPx(e.clientX - offsetX);
      this.el.style.top = cssPx(e.clientY - offsetY);
    };

    const onUp = () => {
      window.removeEventListener("pointermove", onMove, true);
      window.removeEventListener("pointerup", onUp, true);
      this.floatingStyles = {
        left: this.el.style.left,
        top: this.el.style.top,
        width: this.el.style.width,
        height: this.el.style.height,
      };
      this.saveState();
    };

    window.addEventListener("pointermove", onMove, true);
    window.addEventListener("pointerup", onUp, true);
  }

  private beginFloatingResize(ev: PointerEvent): void {
    stop(ev);

    const startX = ev.clientX;
    const startY = ev.clientY;
    const rect = this.el.getBoundingClientRect();
    const startW = rect.width;
    const startH = rect.height;

    const onMove = (e: PointerEvent) => {
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      this.el.style.width = cssPx(Math.max(200, startW + dx));
      this.el.style.height = cssPx(Math.max(150, startH + dy));
    };

    const onUp = () => {
      window.removeEventListener("pointermove", onMove, true);
      window.removeEventListener("pointerup", onUp, true);
      this.floatingStyles = {
        left: this.el.style.left,
        top: this.el.style.top,
        width: this.el.style.width,
        height: this.el.style.height,
      };
      this.saveState();
    };

    window.addEventListener("pointermove", onMove, true);
    window.addEventListener("pointerup", onUp, true);
  }

  private showBurgerMenu(): void {
    // Remover menú existente
    document.querySelector(".widget-context-menu")?.remove();

    const menu = el("div", {
      class: "widget-context-menu",
      role: "menu"
    });

    const menuItems = [
      { label: this.minimized ? "Restore" : "Minimize", action: () => this.toggleMinimize() },
      { label: this.isMaximized() ? "Restore size" : "Maximize", action: () => this.isMaximized() ? this.restore() : this.maximize() },
      { label: this.isFloating() ? "Dock" : "Float", action: () => this.toggleFloating() },
      { divider: true },
      { label: "Refresh", action: () => void this.refresh(), disabled: !this.opts.onRefresh },
      { label: "Open in new window", action: () => this.openInNewWindow() },
      { divider: true },
      { label: "Close", action: () => this.close() },
    ];

    for (const item of menuItems) {
      if ((item as { divider?: boolean }).divider) {
        menu.appendChild(el("hr", { class: "widget-menu-divider" }));
        continue;
      }

      const { label, action, disabled } = item as { label: string; action: () => void; disabled?: boolean };
      const btn = el("button", {
        class: "widget-menu-item",
        type: "button",
        disabled: disabled ? "true" : "",
      }, label);

      on(btn, "click", () => {
        action();
        menu.remove();
      });

      menu.appendChild(btn);
    }

    document.body.appendChild(menu);

    // Posicionar menú
    const rect = this.burgerBtn.getBoundingClientRect();
    Object.assign(menu.style, {
      position: "fixed",
      top: cssPx(rect.bottom + 4),
      right: cssPx(window.innerWidth - rect.right),
      zIndex: "100000",
    });

    // Cerrar al hacer click fuera
    const closeMenu = (e: Event) => {
      if (!(e.target as HTMLElement).closest(".widget-context-menu")) {
        menu.remove();
        document.removeEventListener("pointerdown", closeMenu, true);
      }
    };
    setTimeout(() => {
      document.addEventListener("pointerdown", closeMenu, true);
    }, 0);
  }

  // === Persistence ===

  private storageKey(): string {
    return `widget:${this.id}`;
  }

  saveState(): void {
    const state: WidgetState = {
      id: this.id,
      mode: this.mode,
      minimized: this.minimized,
      dashboardId: this.dashboard?.id ?? this.lastDocked?.dashboard.id ?? null,
      placement: this.placement ?? this.lastDocked?.placement ?? null,
      floating: this.floatingStyles,
    };
    storage.set(this.storageKey(), state);
  }

  getSavedState(): WidgetState | null {
    return storage.get<WidgetState>(this.storageKey());
  }

  restoreState(): void {
    if (this.stateRestored) return;
    this.stateRestored = true;

    const state = this.getSavedState();
    if (!state) return;

    this.minimized = state.minimized;
    this.el.classList.toggle("is-minimized", this.minimized);

    if (state.mode === "floating" && state.floating) {
      // Restaurar floating después de que el widget esté en el DOM
      setTimeout(() => {
        this.float();
        if (state.floating) {
          Object.assign(this.el.style, state.floating);
          this.floatingStyles = state.floating;
        }
      }, 0);
    } else if (state.mode === "maximized") {
      setTimeout(() => this.maximize(), 0);
    }
  }

  destroy(): void {
    this.onDestroy(); // Lifecycle hook: before destroy
    for (const d of this.disposers) d();
    this.disposers = [];
  }
}