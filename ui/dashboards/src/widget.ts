import { cssPx, el, on, stop, uid, type Dispose } from "./utils";
import type { DashboardView, Cell } from "./dashboard";

export type ToolbarButton = {
  id: string;
  title: string;
  icon?: string;       // text/icon (simple demo)
  onClick: (w: Widget) => void;
  visible?: (w: Widget) => boolean;
};

export type WidgetOptions = {
  id?: string;
  title: string;
  icon?: string; // can be emoji or an icon text; replace with <i> if you use an icon font
  header?: string | HTMLElement;
  content?: string | HTMLElement;
  footer?: string | HTMLElement;

  // Behavior toggles
  draggable?: boolean;
  resizable?: boolean;

  // Callbacks
  onRefresh?: (w: Widget) => void | Promise<void>;
  onClose?: (w: Widget) => void;

  toolbar?: ToolbarButton[]; // allow custom buttons
};

type WidgetState = "docked" | "floating" | "maximized";

export type SavedWidgetState = {
  state: WidgetState;
  minimized: boolean;
  dashId: string | null;
  cell: Cell | null;
  floating?: { left?: string; top?: string; width?: string; height?: string };
};

export class Widget {
  public readonly id: string;
  public readonly el: HTMLElement;

  private readonly titleBar: HTMLElement;
  private readonly titleText: HTMLElement;
  private readonly toolbarEl: HTMLElement;
  private readonly burgerBtn: HTMLButtonElement;

  private readonly sectionHeader: HTMLElement;
  private readonly sectionContent: HTMLElement;
  private readonly sectionFooter: HTMLElement;

  private dash: DashboardView | null = null;
  private cell: Cell | null = null;

  private state: WidgetState = "docked";
  private minimized = false;

  private prevDock: { dash: DashboardView; cell: Cell } | null = null;
  private prevInlineStyle: string | null = null;

  private disposers: Dispose[] = [];

  private resizeAvail = { right: true, bottom: true };

  private opts: WidgetOptions;
  private restoredState = false;

  constructor(opts: WidgetOptions) {
    this.opts = opts;
    this.id = opts.id ?? uid("w");

    // Root
    this.el = el("article", { class: "widget", "data-widget-id": this.id });

    // Titlebar
    const iconEl = el("span", { class: "widget-icon", title: "Widget icon" }, opts.icon ?? "▣");
    this.titleText = el("span", { class: "widget-title" }, opts.title);

    this.toolbarEl = el("div", { class: "widget-toolbar" });

    this.burgerBtn = el("button", { class: "widget-burger", type: "button", title: "Widget menu" }, "⌄") as HTMLButtonElement;

    this.titleBar = el("div", { class: "widget-titlebar" }, iconEl, this.titleText, this.toolbarEl, this.burgerBtn);

    // Sections
    this.sectionHeader = el("div", { class: "widget-section widget-header" });
    this.sectionContent = el("div", { class: "widget-section widget-content" });
    this.sectionFooter = el("div", { class: "widget-section widget-footer" });

    this.setSection(this.sectionHeader, opts.header ?? "");
    this.setSection(this.sectionContent, opts.content ?? "");
    this.setSection(this.sectionFooter, opts.footer ?? "");

    // Resize handle (docked + floating)
    const handleCorner = el("div", { class: "widget-resize-handle handle-br", title: "Resize" });

    this.el.append(this.titleBar, this.sectionHeader, this.sectionContent, this.sectionFooter, handleCorner);

    this.buildToolbar();
    this.wireInteractions(handleCorner);
  }

  private setSection(section: HTMLElement, value: string | HTMLElement): void {
    section.innerHTML = "";
    if (typeof value === "string") {
      section.innerHTML = value;
    } else {
      section.append(value);
    }
  }

  getTitle(): string {
    return this.titleText.textContent ?? this.opts.title;
  }

  getIcon(): string {
    return this.opts.icon ?? "▣";
  }

  private buildToolbar(): void {
    const defaultButtons: ToolbarButton[] = [
      {
        id: "min",
        title: "Minimize / restore",
        icon: "▁",
        onClick: (w) => w.toggleMinimize(),
        visible: () => true,
      },
      {
        id: "max",
        title: "Maximize",
        icon: "⛶",
        onClick: (w) => w.maximize(),
        visible: (w) => !w.isMaximized(),
      },
      {
        id: "restore",
        title: "Restore",
        icon: "🗗",
        onClick: (w) => w.restore(),
        visible: (w) => w.isMaximized(),
      },
      {
        id: "refresh",
        title: "Refresh",
        icon: "⟳",
        onClick: (w) => void w.refresh(),
        visible: () => true,
      },
      {
        id: "popout",
        title: "Open in new window",
        icon: "🗗",
        onClick: (w) => w.openInWindow(),
        visible: () => true,
      },
      {
        id: "float",
        title: "Decouple / dock",
        icon: "⇱",
        onClick: (w) => w.toggleFloating(),
        visible: () => true,
      },
      {
        id: "close",
        title: "Close",
        icon: "×",
        onClick: (w) => w.close(),
        visible: () => true,
      },
    ];

    const all = [...defaultButtons, ...(this.opts.toolbar ?? [])];

    const render = () => {
      this.toolbarEl.innerHTML = "";
      for (const b of all) {
        if (b.visible && !b.visible(this)) continue;
        const btn = el("button", { class: "widget-toolbtn", type: "button", title: b.title, "data-btn": b.id }, b.icon ?? b.title);
        on(btn, "click", (ev) => {
          stop(ev);
          b.onClick(this);
          // re-render on state changes
          render();
        });
        this.toolbarEl.append(btn);
      }
    };
    render();

    // Burger menu duplicates toolbar actions (simple)
    on(this.burgerBtn, "click", (ev) => {
      stop(ev);
      this.showMenu();
    });
  }

  private showMenu(): void {
    document.querySelector(".widget-menu")?.remove();

    const menu = el("div", { class: "widget-menu", role: "menu" });

    const add = (label: string, fn: () => void, enabled = true) => {
      const b = el("button", { class: "widget-menu-item", type: "button" }, label) as HTMLButtonElement;
      b.disabled = !enabled;
      on(b, "click", (ev) => {
        stop(ev);
        fn();
        menu.remove();
      });
      menu.append(b);
    };

    add(this.minimized ? "Restore from minimize" : "Minimize", () => this.toggleMinimize());
    add(this.isMaximized() ? "Restore size" : "Maximize", () => (this.isMaximized() ? this.restore() : this.maximize()));
    add(this.isFloating() ? "Dock widget" : "Decouple (float)", () => this.toggleFloating());
    add("Refresh", () => void this.refresh(), !!this.opts.onRefresh);
    add("Close", () => this.close());

    document.body.append(menu);
    const r = this.burgerBtn.getBoundingClientRect();
    menu.style.left = cssPx(r.right - menu.offsetWidth);
    menu.style.top = cssPx(r.bottom + 6);

    const off = on(window, "pointerdown", (ev) => {
      const t = ev.target as HTMLElement;
      if (!t.closest(".widget-menu") && t !== this.burgerBtn) {
        menu.remove();
        off();
      }
    }, { capture: true });
  }

  private wireInteractions(handleCorner: HTMLElement): void {
    // Docked drag (swap cells) OR floating drag (move freely)
    const dragEnabled = this.opts.draggable ?? true;

    if (dragEnabled) {
      this.disposers.push(on(this.titleBar, "pointerdown", (ev) => {
        const p = ev as PointerEvent;
        const t = ev.target as HTMLElement;
        if (t.closest("button")) return; // don't start drag on buttons
        if (this.isMaximized()) return;

        if (this.isFloating()) {
          this.beginFloatingDrag(p);
        } else if (this.dash && this.dash.layout && this.cell) {
          this.dash.layout.beginDockDrag(this, { x: p.clientX, y: p.clientY });
        }
      }));
    }

    const resizable = this.opts.resizable ?? true;

    const startResize = () => (ev: PointerEvent) => {
      if (!resizable) return;
      if (this.isMaximized()) return;

      const edges = { right: this.resizeAvail.right, bottom: this.resizeAvail.bottom };
      if (!edges.right && !edges.bottom) return;

      stop(ev);

      const startX = ev.clientX;
      const startY = ev.clientY;
      const baseline = this.dash && this.cell
        ? { rows: this.dash.layout.getRowSizes(), cols: this.dash.layout.getColSizes() }
        : undefined;

      // Floating: resize the widget itself.
      const startRect = this.el.getBoundingClientRect();
      const startW = startRect.width;
      const startH = startRect.height;

      const move = (e: PointerEvent) => {
        const dx = e.clientX - startX;
        const dy = e.clientY - startY;

        if (this.isFloating()) {
          const w = Math.max(220, startW + (edges.right ? dx : 0));
          const h = Math.max(120, startH + (edges.bottom ? dy : 0));
          this.el.style.width = cssPx(w);
          this.el.style.height = cssPx(h);
        } else if (this.dash && this.cell) {
          this.dash.layout.resizeTracksFromCell(this.cell, dx, dy, edges, baseline);
        }
      };

      const up = () => {
        window.removeEventListener("pointermove", move, true);
        window.removeEventListener("pointerup", up, true);
        if (this.isFloating()) this.saveState();
      };

      window.addEventListener("pointermove", move, true);
      window.addEventListener("pointerup", up, true);
    };

    this.disposers.push(on(handleCorner, "pointerdown", startResize()));
  }

  private storageKey(): string {
    return `widget-state:${this.id}`;
  }

  getSavedState(): SavedWidgetState | null {
    const raw = localStorage.getItem(this.storageKey());
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  saveState(): void {
    const payload: SavedWidgetState = {
      state: this.state,
      minimized: this.minimized,
      dashId: this.dash?.id ?? this.prevDock?.dash.id ?? null,
      cell: this.cell,
    };

    if (this.isFloating() || this.isMaximized()) {
      payload.floating = {
        left: this.el.style.left,
        top: this.el.style.top,
        width: this.el.style.width,
        height: this.el.style.height,
      };
    }

    localStorage.setItem(this.storageKey(), JSON.stringify(payload));
  }

  maybeRestoreState(): void {
    if (this.restoredState) return;
    const saved = this.getSavedState();
    if (!saved) return;
    this.restoredState = true;

    this.minimized = !!saved.minimized;
    this.el.classList.toggle("is-minimized", this.minimized);

    if (saved.state === "floating") {
      this.float();
      if (saved.floating) {
        if (saved.floating.left) this.el.style.left = saved.floating.left;
        if (saved.floating.top) this.el.style.top = saved.floating.top;
        if (saved.floating.width) this.el.style.width = saved.floating.width;
        if (saved.floating.height) this.el.style.height = saved.floating.height;
      }
    } else if (saved.state === "maximized") {
      this.maximize();
    }
  }

  private beginFloatingDrag(ev: PointerEvent): void {
    stop(ev);
    this.el.setPointerCapture?.(ev.pointerId);

    const startX = ev.clientX;
    const startY = ev.clientY;

    const r = this.el.getBoundingClientRect();
    const ox = startX - r.left;
    const oy = startY - r.top;

    const move = (e: PointerEvent) => {
      const x = e.clientX - ox;
      const y = e.clientY - oy;
      this.el.style.left = cssPx(x);
      this.el.style.top = cssPx(y);
    };

    const up = () => {
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);
      this.saveState();
    };

    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
  }

  // --- API used by Dashboard ---
  setDocked(dash: DashboardView, cell: Cell): void {
    this.dash = dash;
    this.cell = cell;
    this.state = "docked";
    this.el.classList.remove("is-floating", "is-maximized");
    this.el.style.position = "";
    this.el.style.left = "";
    this.el.style.top = "";
    // In docked mode width/height are governed by the grid tracks.
    this.el.style.width = "";
    this.el.style.height = "";
  }

  setCell(cell: Cell): void {
    this.cell = cell;
  }

  getCell(): Cell | null {
    return this.cell;
  }

  setDockedResizeAvailability(avail: { right: boolean; bottom: boolean }): void {
    this.resizeAvail = avail;
    const none = !avail.right && !avail.bottom;
    this.el.classList.toggle("no-resize", none);
  }

  // --- Public API ---
  toggleMinimize(): void {
    this.minimized = !this.minimized;
    this.el.classList.toggle("is-minimized", this.minimized);
    this.saveState();
  }

  async refresh(): Promise<void> {
    this.el.classList.add("is-refreshing");
    try {
      await this.opts.onRefresh?.(this);
    } finally {
      this.el.classList.remove("is-refreshing");
    }
  }

  close(): void {
    this.opts.onClose?.(this);
    localStorage.removeItem(this.storageKey());
    this.destroy();
    this.el.remove();
  }

  destroy(): void {
    for (const d of this.disposers) d();
    this.disposers = [];
  }

  isFloating(): boolean {
    return this.state === "floating";
  }

  isMaximized(): boolean {
    return this.state === "maximized";
  }

  toggleFloating(): void {
    if (this.isFloating()) {
      this.dock();
    } else {
      this.float();
    }
  }

  openInWindow(): void {
    const win = window.open("", "_blank", "width=720,height=480");
    if (!win) return;
    const styles = Array.from(document.styleSheets)
      .map((s) => {
        try {
          return Array.from(s.cssRules ?? [])
            .map((r) => r.cssText)
            .join("\n");
        } catch {
          return "";
        }
      })
      .join("\n");
    win.document.write(`<!doctype html><html><head><title>${this.getTitle()}</title><style>${styles}</style></head><body></body></html>`);
    win.document.body.append(this.el.cloneNode(true));
    win.document.close();
  }

  float(): void {
    if (this.isMaximized()) this.restore();

    if (!this.dash || !this.cell) {
      // already detached or not yet docked
      this.state = "floating";
      this.el.classList.add("is-floating");
      this.saveState();
      return;
    }

    this.prevDock = { dash: this.dash, cell: { ...this.cell } };
    this.prevInlineStyle = this.el.getAttribute("style");

    const r = this.el.getBoundingClientRect();
    document.body.append(this.el);
    this.state = "floating";
    this.el.classList.add("is-floating");
    this.el.style.position = "absolute";
    this.el.style.left = cssPx(r.left);
    this.el.style.top = cssPx(r.top);
    this.el.style.width = cssPx(Math.max(260, r.width));
    this.el.style.height = cssPx(Math.max(160, r.height));

    // keep references
    this.dash = this.prevDock.dash;
    this.cell = this.prevDock.cell;
    this.saveState();
  }

  dock(): void {
    if (!this.prevDock) {
      // best effort: if we don't know original, just remove floating styles
      this.el.classList.remove("is-floating");
      this.state = "docked";
      this.el.style.position = "";
      this.el.style.left = "";
      this.el.style.top = "";
      this.el.style.width = "";
      this.el.style.height = "";
      return;
    }

    const { dash, cell } = this.prevDock;
    dash.layout.setWidget(cell, this); // re-attach
    this.state = "docked";
    this.el.classList.remove("is-floating");
    this.prevDock = null;

    if (this.prevInlineStyle) this.el.setAttribute("style", this.prevInlineStyle);
    this.prevInlineStyle = null;

    // grid governs size; remove explicit sizing
    this.el.style.width = "";
    this.el.style.height = "";
    this.el.style.left = "";
    this.el.style.top = "";
    this.el.style.position = "";
    this.saveState();
  }

  maximize(): void {
    if (this.isMaximized()) return;

    if (this.isFloating()) {
      // maximize over page
      this.prevInlineStyle = this.el.getAttribute("style");
      this.el.classList.add("is-maximized");
      this.state = "maximized";
      this.el.style.position = "fixed";
      this.el.style.left = "0";
      this.el.style.top = "0";
      this.el.style.width = "100vw";
      this.el.style.height = "100vh";
      this.saveState();
      return;
    }

    if (!this.dash) return;

    // Move to dashboard root to cover header/main/footer
    this.prevDock = this.cell ? { dash: this.dash, cell: { ...this.cell } } : null;
    this.prevInlineStyle = this.el.getAttribute("style");

    this.dash.el.append(this.el);

    this.el.classList.add("is-maximized");
    this.state = "maximized";
    this.el.style.position = "absolute";
    this.el.style.left = "0";
    this.el.style.top = "0";
    this.el.style.right = "0";
    this.el.style.bottom = "0";
    this.el.style.width = "";
    this.el.style.height = "";
    this.saveState();
  }

  restore(): void {
    if (!this.isMaximized()) return;

    this.el.classList.remove("is-maximized");
    this.state = this.prevDock ? "docked" : "floating";

    if (this.prevInlineStyle != null) {
      this.el.setAttribute("style", this.prevInlineStyle);
    } else {
      this.el.removeAttribute("style");
    }
    this.prevInlineStyle = null;

    if (this.prevDock) {
      const { dash, cell } = this.prevDock;
      dash.layout.setWidget(cell, this);
      this.prevDock = null;
    } else {
      // restore from fullscreen float to normal floating
      this.el.classList.add("is-floating");
      this.el.style.position = "absolute";
      // keep any previous left/top/size that user changed
    }
    this.saveState();
  }
}
