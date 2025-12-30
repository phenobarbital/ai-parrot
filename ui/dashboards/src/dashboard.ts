import { clamp, cssPx, el, on, stop, uid, type Dispose } from "./utils";
import type { Widget } from "./widget";

export type DashboardTemplateParts = {
  header?: HTMLElement;
  footer?: HTMLElement;
};

export type DashboardTabOptions = {
  id?: string;
  title: string;
  icon?: string;
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
    const icon = el("span", { class: "dash-tab-icon" }, tab.icon ?? "⬢");
    const title = el("span", { class: "dash-tab-title" }, tab.title);
    const burger = el("button", { class: "dash-tab-burger", type: "button", title: "Dashboard menu" }, "⌄");
    const close = el("button", { class: "dash-tab-close", type: "button", title: "Close dashboard" }, "×");

    btn.append(icon, title, burger);
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

type CellSlot = {
  container: HTMLElement;
  tabStrip: HTMLElement;
  stack: HTMLElement;
  tabs: Map<string, { widget: Widget; tab: HTMLElement }>;
  activeId: string | null;
};

export class GridLayout {
  private readonly dash: DashboardView;
  private readonly gridEl: HTMLElement;

  private readonly rows: number;
  private readonly cols: number;
  private readonly minTrackPct: number;

  private rowSizes: number[]; // fractions that sum to 1
  private colSizes: number[];

  private cellSlots: Map<string, CellSlot> = new Map();
  private widgetToCell: Map<string, string> = new Map();

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
    const target = this.normalizeCellFromSaved(widget, cell);
    this.detachWidget(widget);

    const slot = this.ensureSlot(target);
    const tab = el(
      "button",
      { class: "widget-tab", type: "button", "data-widget-id": widget.id },
      el("span", { class: "widget-tab-icon" }, widget.getIcon()),
      el("span", { class: "widget-tab-title" }, widget.getTitle()),
    );

    slot.tabStrip.append(tab);
    slot.tabs.set(widget.id, { widget, tab });
    slot.tabStrip.classList.toggle("has-tabs", slot.tabs.size > 1);

    widget.setDocked(this.dash, target);
    widget.el.classList.add("is-active");
    slot.stack.append(widget.el);

    on(tab, "click", () => this.setActiveWidget(slot, widget.id));

    this.widgetToCell.set(widget.id, this.key(target));
    if (!slot.activeId) this.setActiveWidget(slot, widget.id);
    widget.maybeRestoreState();

    this.updateWidgetHandles();
    this.save();
    widget.saveState();
  }

  moveWidget(from: Cell, to: Cell, widget?: Widget): void {
    const fromKey = this.key(from);
    const slot = this.cellSlots.get(fromKey);
    if (!slot) return;
    const entry = widget ? slot.tabs.get(widget.id) : slot.tabs.get(slot.activeId ?? Array.from(slot.tabs.keys())[0] ?? "");
    const w = entry?.widget;
    if (!w) return;

    this.removeFromSlot(slot, w, fromKey);
    const target = this.normalizeCell(to);
    this.setWidget(target, w);
  }

  private swapWidgets(from: Cell, to: Cell, a: Widget, b: Widget): void {
    const fromKey = this.key(from);
    const toKey = this.key(to);
    const fromSlot = this.cellSlots.get(fromKey);
    const toSlot = this.cellSlots.get(toKey);

    if (!fromSlot || !toSlot) {
      this.moveWidget(from, to, a);
      return;
    }

    this.removeFromSlot(fromSlot, a, fromKey);
    this.removeFromSlot(toSlot, b, toKey);

    this.setWidget(this.normalizeCell(to), a);
    this.setWidget(this.normalizeCell(from), b);

    const newFromSlot = this.cellSlots.get(this.key(from));
    const newToSlot = this.cellSlots.get(this.key(to));
    if (newFromSlot) this.setActiveWidget(newFromSlot, b.id);
    if (newToSlot) this.setActiveWidget(newToSlot, a.id);
  }

  getWidgetAt(cell: Cell): Widget | undefined {
    const slot = this.cellSlots.get(this.key(cell));
    if (!slot) return undefined;
    const active = slot.activeId ?? Array.from(slot.tabs.keys())[0];
    return active ? slot.tabs.get(active)?.widget : undefined;
  }

  private normalizeCell(cell: Cell): Cell {
    return {
      row: clamp(cell.row, 0, this.rows - 1),
      col: clamp(cell.col, 0, this.cols - 1),
    };
  }

  private normalizeCellFromSaved(widget: Widget, fallback: Cell): Cell {
    const saved = widget.getSavedState();
    if (saved?.dashId === this.dash.id && saved.cell) return this.normalizeCell(saved.cell);
    return this.normalizeCell(fallback);
  }

  private ensureSlot(cell: Cell): CellSlot {
    const key = this.key(cell);
    const existing = this.cellSlots.get(key);
    if (existing) return existing;

    const container = el("div", { class: "dashboard-cell" });
    container.style.gridRow = `${cell.row + 1}`;
    container.style.gridColumn = `${cell.col + 1}`;

    const tabStrip = el("div", { class: "widget-tabstrip" });
    const stack = el("div", { class: "widget-stack" });
    container.append(tabStrip, stack);
    this.gridEl.append(container);

    const slot: CellSlot = { container, tabStrip, stack, tabs: new Map(), activeId: null };
    this.cellSlots.set(key, slot);
    return slot;
  }

  private setActiveWidget(slot: CellSlot, widgetId: string): void {
    slot.activeId = widgetId;
    for (const [id, entry] of slot.tabs) {
      const active = id === widgetId;
      entry.tab.classList.toggle("is-active", active);
      entry.widget.el.classList.toggle("is-active", active);
    }
  }

  private detachWidget(widget: Widget): void {
    const key = this.widgetToCell.get(widget.id);
    if (!key) return;
    const slot = this.cellSlots.get(key);
    if (!slot) return;
    this.removeFromSlot(slot, widget, key);
  }

  private removeFromSlot(slot: CellSlot, widget: Widget, key?: string): void {
    const entry = slot.tabs.get(widget.id);
    if (!entry) return;
    entry.tab.remove();
    widget.el.remove();
    slot.tabs.delete(widget.id);
    slot.tabStrip.classList.toggle("has-tabs", slot.tabs.size > 1);

    if (slot.activeId === widget.id) {
      const next = slot.tabs.keys().next().value ?? null;
      slot.activeId = next;
      if (next) this.setActiveWidget(slot, next);
    }

    if (slot.tabs.size === 0) {
      slot.container.remove();
      this.cellSlots.delete(key ?? this.key(widget.getCell() ?? { row: 0, col: 0 }));
    }
    this.widgetToCell.delete(widget.id);
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
  resizeTracksFromCell(
    cell: Cell,
    dx: number,
    dy: number,
    edges: { right?: boolean; bottom?: boolean },
    baseline?: { rows: number[]; cols: number[] },
  ): void {
    const gridRect = this.gridEl.getBoundingClientRect();

    const nextCols = baseline?.cols ? [...baseline.cols] : [...this.colSizes];
    const nextRows = baseline?.rows ? [...baseline.rows] : [...this.rowSizes];

    if (edges.right && cell.col < this.cols - 1) {
      const delta = dx / gridRect.width;
      const [a, b] = this.adjustSplit(nextCols[cell.col], nextCols[cell.col + 1], delta);
      nextCols[cell.col] = a;
      nextCols[cell.col + 1] = b;
    }
    if (edges.bottom && cell.row < this.rows - 1) {
      const delta = dy / gridRect.height;
      const [a, b] = this.adjustSplit(nextRows[cell.row], nextRows[cell.row + 1], delta);
      nextRows[cell.row] = a;
      nextRows[cell.row + 1] = b;
    }

    this.colSizes = nextCols;
    this.rowSizes = nextRows;
    this.renormalize(this.colSizes);
    this.renormalize(this.rowSizes);
    this.applyTracks();
    this.save();
  }

  /** Adjust split between two tracks with a delta (+ makes first larger). */
  private adjustSplit(a: number, b: number, delta: number): [number, number] {
    const total = a + b;
    const na = clamp(a + delta, this.minTrackPct, total - this.minTrackPct);
    const nb = clamp(total - na, this.minTrackPct, total - this.minTrackPct);
    return [na, nb];
  }

  private renormalize(arr: number[]): void {
    const sum = arr.reduce((s, n) => s + n, 0);
    for (let i = 0; i < arr.length; i++) arr[i] = arr[i] / sum;
  }

  getRowSizes(): number[] {
    return [...this.rowSizes];
  }

  getColSizes(): number[] {
    return [...this.colSizes];
  }

  private applyTracks(): void {
    this.gridEl.style.gridTemplateColumns = this.colSizes.map((f) => `${(f * 100).toFixed(3)}%`).join(" ");
    this.gridEl.style.gridTemplateRows = this.rowSizes.map((f) => `${(f * 100).toFixed(3)}%`).join(" ");
    this.updateWidgetHandles();
  }

  updateWidgetHandles(): void {
    // Hide right/bottom resize handles on last col/row to avoid "resizing into nowhere".
    for (const [k, slot] of this.cellSlots) {
      const [rowS, colS] = k.split(":");
      const row = Number(rowS);
      const col = Number(colS);
      for (const { widget } of slot.tabs.values()) {
        widget.setDockedResizeAvailability({
          right: col < this.cols - 1,
          bottom: row < this.rows - 1,
        });
      }
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
          const target = this.getWidgetAt(cell);
          if (target && target !== widget) {
            this.swapWidgets(from, cell, widget, target);
          } else {
            this.moveWidget(from, cell, widget);
          }
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
