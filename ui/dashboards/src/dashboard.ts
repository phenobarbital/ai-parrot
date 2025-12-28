import { clamp, cssPx, el, on, stop, uid, type Dispose } from "./utils";
import type { Widget } from "./widget";

export type DashboardTemplateParts = {
  header?: HTMLElement;
  footer?: HTMLElement;
};

export type DashboardTabOptions = {
  id?: string;
  title: string;
  closable?: boolean;
};

export type GridOptions = {
  rows: number;
  cols: number;
  minTrackPct?: number; // minimum track size as a percentage (0..1)
};

export type DashboardViewOptions = {
  id?: string;
  template?: DashboardTemplateParts;
  grid: GridOptions;
};

export class DashboardTabs {
  public readonly el: HTMLElement;
  private readonly tabBar: HTMLElement;
  private readonly tabStrip: HTMLElement;
  private readonly content: HTMLElement;

  private tabs: Map<string, DashboardView> = new Map();
  private activeId: string | null = null;

  constructor(mount: HTMLElement) {
    this.el = el("div", { class: "dashboards" });

    this.tabBar = el("div", { class: "dashboards-tabbar" });
    this.tabStrip = el("div", { class: "dashboards-tabs" });
    this.content = el("div", { class: "dashboards-content" });

    this.tabBar.append(this.tabStrip);
    this.el.append(this.tabBar, this.content);
    mount.append(this.el);
  }

  addDashboard(tab: DashboardTabOptions, view: DashboardViewOptions): DashboardView {
    const id = tab.id ?? view.id ?? uid("dash");
    if (this.tabs.has(id)) throw new Error(`Dashboard id already exists: ${id}`);

    const dash = new DashboardView(id, view);
    this.tabs.set(id, dash);
    this.content.append(dash.el);

    // Tab button
    const btn = el("button", { class: "dash-tab", "data-dash-id": id, type: "button" });
    const title = el("span", { class: "dash-tab-title" }, tab.title);
    const burger = el("button", { class: "dash-tab-burger", type: "button", title: "Dashboard menu" }, "☰");
    const close = el("button", { class: "dash-tab-close", type: "button", title: "Close dashboard" }, "×");

    btn.append(title);
    btn.append(burger);
    if (tab.closable ?? true) btn.append(close);

    // click-to-activate
    on(btn, "click", (ev) => {
      const t = ev.target as HTMLElement;
      if (t.closest(".dash-tab-close")) return; // handled separately
      if (t.closest(".dash-tab-burger")) return; // menu handled separately
      this.activate(id);
    });

    // close
    on(close, "click", (ev) => {
      stop(ev);
      this.removeDashboard(id);
    });

    // settings/burger menu (example only)
    on(burger, "click", (ev) => {
      stop(ev);
      this.showTabMenu(burger, id);
    });

    this.tabStrip.append(btn);

    if (!this.activeId) this.activate(id);
    return dash;
  }

  getDashboard(id: string): DashboardView | undefined {
    return this.tabs.get(id);
  }

  activate(id: string): void {
    if (!this.tabs.has(id)) return;

    this.activeId = id;
    for (const [dashId, dash] of this.tabs) {
      dash.el.classList.toggle("is-active", dashId === id);
    }
    this.tabStrip.querySelectorAll<HTMLElement>(".dash-tab").forEach((b) => {
      b.classList.toggle("is-active", b.dataset.dashId === id);
    });
  }

  removeDashboard(id: string): void {
    const dash = this.tabs.get(id);
    if (!dash) return;

    dash.destroy();
    dash.el.remove();
    this.tabs.delete(id);

    this.tabStrip.querySelectorAll(".dash-tab").forEach((b) => {
      if ((b as HTMLElement).dataset.dashId === id) b.remove();
    });

    // activate another tab if needed
    if (this.activeId === id) {
      const first = this.tabs.keys().next().value ?? null;
      this.activeId = null;
      if (first) this.activate(first);
    }
  }

  private showTabMenu(anchor: HTMLElement, id: string): void {
    const existing = document.querySelector(".dash-menu");
    existing?.remove();

    const menu = el("div", { class: "dash-menu", role: "menu" });
    const item = (label: string, fn: () => void) => {
      const b = el("button", { class: "dash-menu-item", type: "button" }, label);
      on(b, "click", (ev) => {
        stop(ev);
        fn();
        menu.remove();
      });
      return b;
    };

    menu.append(
      item("Rename…", () => {
        const title = prompt("Dashboard name?", this.tabStrip.querySelector(`.dash-tab[data-dash-id="${id}"] .dash-tab-title`)?.textContent ?? "");
        if (title) {
          const tabTitle = this.tabStrip.querySelector(`.dash-tab[data-dash-id="${id}"] .dash-tab-title`);
          if (tabTitle) tabTitle.textContent = title;
        }
      }),
      item("Reset layout", () => this.tabs.get(id)?.layout.reset()),
    );

    document.body.append(menu);
    const r = anchor.getBoundingClientRect();
    menu.style.left = cssPx(r.right - menu.offsetWidth);
    menu.style.top = cssPx(r.bottom + 6);

    const off = on(window, "pointerdown", (ev) => {
      const t = ev.target as HTMLElement;
      if (!t.closest(".dash-menu") && t !== anchor) {
        menu.remove();
        off();
      }
    }, { capture: true });
  }
}

export class DashboardView {
  public readonly id: string;
  public readonly el: HTMLElement;
  public readonly header: HTMLElement;
  public readonly main: HTMLElement;
  public readonly footer: HTMLElement;

  public readonly layout: GridLayout;

  private disposers: Dispose[] = [];

  constructor(id: string, opts: DashboardViewOptions) {
    this.id = id;

    this.el = el("section", { class: "dashboard-view", "data-dashboard-id": id });
    this.header = el("div", { class: "dashboard-header" });
    this.main = el("div", { class: "dashboard-main" });
    this.footer = el("div", { class: "dashboard-footer" });

    // allow template injection (position controlled by CSS grid areas)
    if (opts.template?.header) this.header.append(opts.template.header);
    if (opts.template?.footer) this.footer.append(opts.template.footer);

    this.el.append(this.header, this.main, this.footer);

    this.layout = new GridLayout(this, opts.grid);
  }

  destroy(): void {
    this.layout.destroy();
    for (const d of this.disposers) d();
    this.disposers = [];
  }
}

export type Cell = { row: number; col: number };

export class GridLayout {
  private readonly dash: DashboardView;
  private readonly gridEl: HTMLElement;

  private readonly rows: number;
  private readonly cols: number;
  private readonly minTrackPct: number;

  private rowSizes: number[]; // fractions that sum to 1
  private colSizes: number[];

  private cellToWidget: Map<string, Widget> = new Map();

  private dragGhost: HTMLElement | null = null;
  private draggingWidget: Widget | null = null;

  constructor(dash: DashboardView, opts: GridOptions) {
    this.dash = dash;
    this.rows = Math.max(1, opts.rows);
    this.cols = Math.max(1, opts.cols);
    this.minTrackPct = clamp(opts.minTrackPct ?? 0.12, 0.05, 0.45);

    this.gridEl = el("div", { class: "dashboard-grid" });
    dash.main.append(this.gridEl);

    this.rowSizes = Array.from({ length: this.rows }, () => 1 / this.rows);
    this.colSizes = Array.from({ length: this.cols }, () => 1 / this.cols);

    this.load();
    this.applyTracks();
  }

  destroy(): void {
    this.save();
  }

  reset(): void {
    this.rowSizes = Array.from({ length: this.rows }, () => 1 / this.rows);
    this.colSizes = Array.from({ length: this.cols }, () => 1 / this.cols);
    this.applyTracks();
    this.save();
  }

  private key(cell: Cell): string {
    return `${cell.row}:${cell.col}`;
  }

  setWidget(cell: Cell, widget: Widget): void {
    const k = this.key(cell);
    this.cellToWidget.set(k, widget);

    widget.setDocked(this.dash, cell);
    this.gridEl.append(widget.el);

    widget.el.style.gridRow = `${cell.row + 1}`;
    widget.el.style.gridColumn = `${cell.col + 1}`;

    this.updateWidgetHandles();
    this.save();
  }

  moveWidget(from: Cell, to: Cell): void {
    const fromK = this.key(from);
    const toK = this.key(to);
    const a = this.cellToWidget.get(fromK);
    const b = this.cellToWidget.get(toK);

    if (!a) return;

    this.cellToWidget.set(toK, a);
    a.setCell(to);
    a.el.style.gridRow = `${to.row + 1}`;
    a.el.style.gridColumn = `${to.col + 1}`;

    if (b) {
      this.cellToWidget.set(fromK, b);
      b.setCell(from);
      b.el.style.gridRow = `${from.row + 1}`;
      b.el.style.gridColumn = `${from.col + 1}`;
    } else {
      this.cellToWidget.delete(fromK);
    }

    this.updateWidgetHandles();
    this.save();
  }

  getWidgetAt(cell: Cell): Widget | undefined {
    return this.cellToWidget.get(this.key(cell));
  }

  cellFromPoint(clientX: number, clientY: number): Cell | null {
    const r = this.gridEl.getBoundingClientRect();
    if (clientX < r.left || clientX > r.right || clientY < r.top || clientY > r.bottom) return null;

    const x = (clientX - r.left) / r.width;  // 0..1
    const y = (clientY - r.top) / r.height; // 0..1

    let acc = 0;
    let col = 0;
    for (let i = 0; i < this.colSizes.length; i++) {
      acc += this.colSizes[i];
      if (x <= acc + 1e-9) { col = i; break; }
    }

    acc = 0;
    let row = 0;
    for (let i = 0; i < this.rowSizes.length; i++) {
      acc += this.rowSizes[i];
      if (y <= acc + 1e-9) { row = i; break; }
    }

    return { row, col };
  }

  /** Called by Widget (docked mode) for resize gestures. */
  resizeTracksFromCell(cell: Cell, dx: number, dy: number, edges: { right?: boolean; bottom?: boolean }): void {
    const gridRect = this.gridEl.getBoundingClientRect();
    if (edges.right && cell.col < this.cols - 1) {
      const delta = dx / gridRect.width;
      this.adjustColSplit(cell.col, delta);
    }
    if (edges.bottom && cell.row < this.rows - 1) {
      const delta = dy / gridRect.height;
      this.adjustRowSplit(cell.row, delta);
    }
    this.applyTracks();
    this.save();
  }

  /** Adjust split between col i and i+1 by delta (+ makes left larger). */
  private adjustColSplit(i: number, delta: number): void {
    const a = this.colSizes[i];
    const b = this.colSizes[i + 1];
    const na = clamp(a + delta, this.minTrackPct, 1);
    const nb = clamp(b - (na - a), this.minTrackPct, 1);
    const drift = (a + b) - (na + nb);

    this.colSizes[i] = na + drift / 2;
    this.colSizes[i + 1] = nb + drift / 2;

    this.renormalize(this.colSizes);
  }

  /** Adjust split between row i and i+1 by delta (+ makes top larger). */
  private adjustRowSplit(i: number, delta: number): void {
    const a = this.rowSizes[i];
    const b = this.rowSizes[i + 1];
    const na = clamp(a + delta, this.minTrackPct, 1);
    const nb = clamp(b - (na - a), this.minTrackPct, 1);
    const drift = (a + b) - (na + nb);

    this.rowSizes[i] = na + drift / 2;
    this.rowSizes[i + 1] = nb + drift / 2;

    this.renormalize(this.rowSizes);
  }

  private renormalize(arr: number[]): void {
    const sum = arr.reduce((s, n) => s + n, 0);
    for (let i = 0; i < arr.length; i++) arr[i] = arr[i] / sum;
  }

  private applyTracks(): void {
    this.gridEl.style.gridTemplateColumns = this.colSizes.map((f) => `${(f * 100).toFixed(3)}%`).join(" ");
    this.gridEl.style.gridTemplateRows = this.rowSizes.map((f) => `${(f * 100).toFixed(3)}%`).join(" ");
    this.updateWidgetHandles();
  }

  updateWidgetHandles(): void {
    // Hide right/bottom resize handles on last col/row to avoid "resizing into nowhere".
    for (const [k, w] of this.cellToWidget) {
      const [rowS, colS] = k.split(":");
      const row = Number(rowS);
      const col = Number(colS);
      w.setDockedResizeAvailability({
        right: col < this.cols - 1,
        bottom: row < this.rows - 1,
      });
    }
  }

  /** Docked drag: begin dragging a widget (called by Widget). */
  beginDockDrag(widget: Widget, pointer: { x: number; y: number }): void {
    if (this.draggingWidget) return;
    this.draggingWidget = widget;

    const r = widget.el.getBoundingClientRect();
    this.dragGhost = el("div", { class: "widget-drag-ghost" });
    this.dragGhost.style.left = cssPx(r.left);
    this.dragGhost.style.top = cssPx(r.top);
    this.dragGhost.style.width = cssPx(r.width);
    this.dragGhost.style.height = cssPx(r.height);
    document.body.append(this.dragGhost);

    widget.el.classList.add("is-dragging");

    const move = (ev: PointerEvent) => {
      this.dragGhost!.style.left = cssPx(ev.clientX - r.width / 2);
      this.dragGhost!.style.top = cssPx(ev.clientY - r.height / 2);

      const cell = this.cellFromPoint(ev.clientX, ev.clientY);
      this.gridEl.querySelectorAll(".grid-drop-target").forEach((n) => n.classList.remove("grid-drop-target"));

      if (cell) {
        const w = this.getWidgetAt(cell);
        if (w && w !== widget) w.el.classList.add("grid-drop-target");
      }
    };

    const up = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);

      widget.el.classList.remove("is-dragging");
      this.dragGhost?.remove();
      this.dragGhost = null;

      const cell = this.cellFromPoint(ev.clientX, ev.clientY);
      this.gridEl.querySelectorAll(".grid-drop-target").forEach((n) => n.classList.remove("grid-drop-target"));

      if (cell) {
        const from = widget.getCell();
        if (from && (from.row !== cell.row || from.col !== cell.col)) {
          // swap
          this.moveWidget(from, cell);
        }
      }
      this.draggingWidget = null;
    };

    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
  }

  private storageKey(): string {
    return `dash-layout:${this.dash.id}`;
  }

  save(): void {
    const payload = {
      rows: this.rows,
      cols: this.cols,
      rowSizes: this.rowSizes,
      colSizes: this.colSizes,
      // widget positions are already intrinsic to their cell, saved by each widget itself if needed
    };
    localStorage.setItem(this.storageKey(), JSON.stringify(payload));
  }

  load(): void {
    const raw = localStorage.getItem(this.storageKey());
    if (!raw) return;
    try {
      const data = JSON.parse(raw);
      if (Array.isArray(data.rowSizes) && data.rowSizes.length === this.rows) this.rowSizes = data.rowSizes;
      if (Array.isArray(data.colSizes) && data.colSizes.length === this.cols) this.colSizes = data.colSizes;
      this.renormalize(this.rowSizes);
      this.renormalize(this.colSizes);
    } catch {
      // ignore
    }
  }
}
