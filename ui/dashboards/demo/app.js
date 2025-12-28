// --- tiny utils ---
function clamp(n, min, max) { return Math.max(min, Math.min(max, n)); }
function cssPx(n) { return `${Math.round(n)}px`; }
function uid(prefix = "id") { return `${prefix}-${Math.random().toString(36).slice(2, 10)}`; }
function stop(ev) { ev.preventDefault(); ev.stopPropagation(); }
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  for (const ch of children) node.append(typeof ch === "string" ? document.createTextNode(ch) : ch);
  return node;
}
function on(target, type, handler, options) {
  target.addEventListener(type, handler, options);
  return () => target.removeEventListener(type, handler, options);
}

// --- DashboardTabs / DashboardView / GridLayout ---
class DashboardTabs {
  constructor(mount) {
    this.tabs = new Map();
    this.activeId = null;

    this.el = el("div", { class: "dashboards" });
    this.tabBar = el("div", { class: "dashboards-tabbar" });
    this.tabStrip = el("div", { class: "dashboards-tabs" });
    this.content = el("div", { class: "dashboards-content" });

    this.tabBar.append(this.tabStrip);
    this.el.append(this.tabBar, this.content);
    mount.append(this.el);
  }

  addDashboard(tab, view) {
    const id = tab.id ?? view.id ?? uid("dash");
    if (this.tabs.has(id)) throw new Error(`Dashboard id already exists: ${id}`);

    const dash = new DashboardView(id, view);
    this.tabs.set(id, dash);
    this.content.append(dash.el);

    const btn = el("button", { class: "dash-tab", "data-dash-id": id, type: "button" });
    const icon = el("span", { class: "dash-tab-icon" }, tab.icon ?? "⬢");
    const title = el("span", { class: "dash-tab-title" }, tab.title);
    const burger = el("button", { class: "dash-tab-burger", type: "button", title: "Dashboard menu" }, "☰");
    const close = el("button", { class: "dash-tab-close", type: "button", title: "Close dashboard" }, "×");

    btn.append(icon, title, burger);
    if (tab.closable ?? true) btn.append(close);

    on(btn, "click", (ev) => {
      const t = ev.target;
      if (t.closest(".dash-tab-close")) return;
      if (t.closest(".dash-tab-burger")) return;
      this.activate(id);
    });

    on(close, "click", (ev) => { stop(ev); this.removeDashboard(id); });
    on(burger, "click", (ev) => { stop(ev); this.showTabMenu(burger, id); });

    this.tabStrip.append(btn);
    if (!this.activeId) this.activate(id);
    return dash;
  }

  activate(id) {
    if (!this.tabs.has(id)) return;
    this.activeId = id;

    for (const [dashId, dash] of this.tabs) dash.el.classList.toggle("is-active", dashId === id);
    this.tabStrip.querySelectorAll(".dash-tab").forEach((b) => b.classList.toggle("is-active", b.dataset.dashId === id));
  }

  removeDashboard(id) {
    const dash = this.tabs.get(id);
    if (!dash) return;
    dash.destroy();
    dash.el.remove();
    this.tabs.delete(id);

    this.tabStrip.querySelectorAll(".dash-tab").forEach((b) => { if (b.dataset.dashId === id) b.remove(); });

    if (this.activeId === id) {
      const first = this.tabs.keys().next().value ?? null;
      this.activeId = null;
      if (first) this.activate(first);
    }
  }

  showTabMenu(anchor, id) {
    document.querySelector(".dash-menu")?.remove();

    const menu = el("div", { class: "dash-menu", role: "menu" });

    const item = (label, fn) => {
      const b = el("button", { class: "dash-menu-item", type: "button" }, label);
      on(b, "click", (ev) => { stop(ev); fn(); menu.remove(); });
      return b;
    };

    menu.append(
      item("Rename…", () => {
        const tabTitle = this.tabStrip.querySelector(`.dash-tab[data-dash-id="${id}"] .dash-tab-title`);
        const title = prompt("Dashboard name?", tabTitle?.textContent ?? "");
        if (title && tabTitle) tabTitle.textContent = title;
      }),
      item("Reset layout", () => this.tabs.get(id)?.layout.reset())
    );

    document.body.append(menu);
    const r = anchor.getBoundingClientRect();
    menu.style.left = cssPx(r.right - menu.offsetWidth);
    menu.style.top = cssPx(r.bottom + 6);

    const off = on(window, "pointerdown", (ev) => {
      const t = ev.target;
      if (!t.closest(".dash-menu") && t !== anchor) { menu.remove(); off(); }
    }, { capture: true });
  }
}

class DashboardView {
  constructor(id, opts) {
    this.id = id;
    this.el = el("section", { class: "dashboard-view", "data-dashboard-id": id });
    this.header = el("div", { class: "dashboard-header" });
    this.main = el("div", { class: "dashboard-main" });
    this.footer = el("div", { class: "dashboard-footer" });

    if (opts.template?.header) this.header.append(opts.template.header);
    if (opts.template?.footer) this.footer.append(opts.template.footer);

    this.el.append(this.header, this.main, this.footer);

    this.layout = new GridLayout(this, opts.grid);
  }
  destroy() { this.layout.destroy(); }
}

class GridLayout {
  constructor(dash, opts) {
    this.dash = dash;
    this.rows = Math.max(1, opts.rows);
    this.cols = Math.max(1, opts.cols);
    this.minTrackPct = clamp(opts.minTrackPct ?? 0.12, 0.05, 0.45);

    this.gridEl = el("div", { class: "dashboard-grid" });
    dash.main.append(this.gridEl);

    this.rowSizes = Array.from({ length: this.rows }, () => 1 / this.rows);
    this.colSizes = Array.from({ length: this.cols }, () => 1 / this.cols);
    this.cellSlots = new Map();
    this.widgetToCell = new Map();

    this.dragGhost = null;
    this.draggingWidget = null;

    this.load();
    this.applyTracks();
  }

  key(cell) { return `${cell.row}:${cell.col}`; }

  normalizeCell(cell) {
    return {
      row: clamp(cell.row, 0, this.rows - 1),
      col: clamp(cell.col, 0, this.cols - 1),
    };
  }

  normalizeCellFromSaved(widget, fallback) {
    const saved = widget.getSavedState();
    if (saved?.dashId === this.dash.id && saved.cell) return this.normalizeCell(saved.cell);
    return this.normalizeCell(fallback);
  }

  ensureSlot(cell) {
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
    const slot = { container, tabStrip, stack, tabs: new Map(), activeId: null };
    this.cellSlots.set(key, slot);
    return slot;
  }

  setActiveWidget(slot, widgetId) {
    slot.activeId = widgetId;
    for (const [id, entry] of slot.tabs) {
      const active = id === widgetId;
      entry.tab.classList.toggle("is-active", active);
      entry.widget.el.classList.toggle("is-active", active);
    }
  }

  detachWidget(widget) {
    const key = this.widgetToCell.get(widget.id);
    if (!key) return;
    const slot = this.cellSlots.get(key);
    if (!slot) return;
    this.removeFromSlot(slot, widget, key);
  }

  removeFromSlot(slot, widget, key) {
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

  setWidget(cell, widget) {
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

  getWidgetAt(cell) {
    const slot = this.cellSlots.get(this.key(cell));
    if (!slot) return undefined;
    const active = slot.activeId ?? Array.from(slot.tabs.keys())[0];
    return active ? slot.tabs.get(active)?.widget : undefined;
  }

  moveWidget(from, to, widget) {
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

  cellFromPoint(clientX, clientY) {
    const r = this.gridEl.getBoundingClientRect();
    if (clientX < r.left || clientX > r.right || clientY < r.top || clientY > r.bottom) return null;

    const x = (clientX - r.left) / r.width;
    const y = (clientY - r.top) / r.height;

    let acc = 0;
    let col = 0;
    for (let i = 0; i < this.colSizes.length; i++) { acc += this.colSizes[i]; if (x <= acc + 1e-9) { col = i; break; } }
    acc = 0;
    let row = 0;
    for (let i = 0; i < this.rowSizes.length; i++) { acc += this.rowSizes[i]; if (y <= acc + 1e-9) { row = i; break; } }

    return { row, col };
  }

  resizeTracksFromCell(cell, dx, dy, edges) {
    const rect = this.gridEl.getBoundingClientRect();
    if (edges.right && cell.col < this.cols - 1) {
      const delta = dx / rect.width;
      this.adjustColSplit(cell.col, delta);
    }
    if (edges.bottom && cell.row < this.rows - 1) {
      const delta = dy / rect.height;
      this.adjustRowSplit(cell.row, delta);
    }
    this.applyTracks();
    this.save();
  }

  adjustColSplit(i, delta) {
    const a = this.colSizes[i], b = this.colSizes[i + 1];
    const na = clamp(a + delta, this.minTrackPct, 1);
    const nb = clamp(b - (na - a), this.minTrackPct, 1);
    const drift = (a + b) - (na + nb);
    this.colSizes[i] = na + drift / 2;
    this.colSizes[i + 1] = nb + drift / 2;
    this.renormalize(this.colSizes);
  }
  adjustRowSplit(i, delta) {
    const a = this.rowSizes[i], b = this.rowSizes[i + 1];
    const na = clamp(a + delta, this.minTrackPct, 1);
    const nb = clamp(b - (na - a), this.minTrackPct, 1);
    const drift = (a + b) - (na + nb);
    this.rowSizes[i] = na + drift / 2;
    this.rowSizes[i + 1] = nb + drift / 2;
    this.renormalize(this.rowSizes);
  }

  renormalize(arr) {
    const sum = arr.reduce((s, n) => s + n, 0);
    for (let i = 0; i < arr.length; i++) arr[i] = arr[i] / sum;
  }

  applyTracks() {
    this.gridEl.style.gridTemplateColumns = this.colSizes.map((f) => `${(f * 100).toFixed(3)}%`).join(" ");
    this.gridEl.style.gridTemplateRows = this.rowSizes.map((f) => `${(f * 100).toFixed(3)}%`).join(" ");
    this.updateWidgetHandles();
  }

  updateWidgetHandles() {
    for (const [k, slot] of this.cellSlots) {
      const [rowS, colS] = k.split(":");
      const row = Number(rowS), col = Number(colS);
      for (const { widget } of slot.tabs.values()) {
        widget.setDockedResizeAvailability({ right: col < this.cols - 1, bottom: row < this.rows - 1 });
      }
    }
  }

  beginDockDrag(widget, pointer) {
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

    const move = (ev) => {
      this.dragGhost.style.left = cssPx(ev.clientX - r.width / 2);
      this.dragGhost.style.top = cssPx(ev.clientY - r.height / 2);

      const cell = this.cellFromPoint(ev.clientX, ev.clientY);
      this.gridEl.querySelectorAll(".grid-drop-target").forEach((n) => n.classList.remove("grid-drop-target"));
      if (cell) {
        const w = this.getWidgetAt(cell);
        if (w && w !== widget) w.el.classList.add("grid-drop-target");
      }
    };

    const up = (ev) => {
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);

      widget.el.classList.remove("is-dragging");
      this.dragGhost?.remove();
      this.dragGhost = null;

      const cell = this.cellFromPoint(ev.clientX, ev.clientY);
      this.gridEl.querySelectorAll(".grid-drop-target").forEach((n) => n.classList.remove("grid-drop-target"));

      if (cell) {
        const from = widget.getCell();
        if (from && (from.row !== cell.row || from.col !== cell.col)) this.moveWidget(from, cell, widget);
      }
      this.draggingWidget = null;
    };

    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
  }

  storageKey() { return `dash-layout:${this.dash.id}`; }
  save() {
    const payload = { rows: this.rows, cols: this.cols, rowSizes: this.rowSizes, colSizes: this.colSizes };
    localStorage.setItem(this.storageKey(), JSON.stringify(payload));
  }
  load() {
    const raw = localStorage.getItem(this.storageKey());
    if (!raw) return;
    try {
      const data = JSON.parse(raw);
      if (Array.isArray(data.rowSizes) && data.rowSizes.length === this.rows) this.rowSizes = data.rowSizes;
      if (Array.isArray(data.colSizes) && data.colSizes.length === this.cols) this.colSizes = data.colSizes;
      this.renormalize(this.rowSizes);
      this.renormalize(this.colSizes);
    } catch {}
  }
  destroy() { this.save(); }
  reset() {
    this.rowSizes = Array.from({ length: this.rows }, () => 1 / this.rows);
    this.colSizes = Array.from({ length: this.cols }, () => 1 / this.cols);
    this.applyTracks();
    this.save();
  }
}

// --- Widget ---
class Widget {
  constructor(opts) {
    this.opts = opts;
    this.id = opts.id ?? uid("w");
    this.dash = null;
    this.cell = null;
    this.state = "docked";
    this.minimized = false;
    this.prevDock = null;
    this.prevInlineStyle = null;
    this.resizeAvail = { right: true, bottom: true };
    this.disposers = [];
    this.restoredState = false;

    this.el = el("article", { class: "widget", "data-widget-id": this.id });

    const iconEl = el("span", { class: "widget-icon", title: "Widget icon" }, opts.icon ?? "▣");
    this.titleText = el("span", { class: "widget-title" }, opts.title);
    this.toolbarEl = el("div", { class: "widget-toolbar" });
    this.burgerBtn = el("button", { class: "widget-burger", type: "button", title: "Widget menu" }, "☰");
    this.titleBar = el("div", { class: "widget-titlebar" }, iconEl, this.titleText, this.toolbarEl, this.burgerBtn);

    this.sectionHeader = el("div", { class: "widget-section widget-header" });
    this.sectionContent = el("div", { class: "widget-section widget-content" });
    this.sectionFooter = el("div", { class: "widget-section widget-footer" });

    this.setSection(this.sectionHeader, opts.header ?? "");
    this.setSection(this.sectionContent, opts.content ?? "");
    this.setSection(this.sectionFooter, opts.footer ?? "");

    const handleBR = el("div", { class: "widget-resize-handle handle-br", title: "Resize" });

    this.el.append(this.titleBar, this.sectionHeader, this.sectionContent, this.sectionFooter, handleBR);

    this.buildToolbar();
    this.wireInteractions(handleBR);
  }

  setSection(section, value) {
    section.innerHTML = "";
    if (typeof value === "string") section.innerHTML = value;
    else section.append(value);
  }

  getTitle() { return this.titleText.textContent ?? this.opts.title; }

  getIcon() { return this.opts.icon ?? "▣"; }

  buildToolbar() {
    const defaultButtons = [
      { id: "min", title: "Minimize / restore", icon: "▁", onClick: (w) => w.toggleMinimize(), visible: () => true },
      { id: "max", title: "Maximize", icon: "⛶", onClick: (w) => w.maximize(), visible: (w) => !w.isMaximized() },
      { id: "restore", title: "Restore", icon: "🗗", onClick: (w) => w.restore(), visible: (w) => w.isMaximized() },
      { id: "refresh", title: "Refresh", icon: "⟳", onClick: (w) => void w.refresh(), visible: () => true },
      { id: "popout", title: "Open in new window", icon: "🗗", onClick: (w) => w.openInWindow(), visible: () => true },
      { id: "float", title: "Decouple / dock", icon: "⇱", onClick: (w) => w.toggleFloating(), visible: () => true },
      { id: "close", title: "Close", icon: "×", onClick: (w) => w.close(), visible: () => true },
    ];

    const all = [...defaultButtons, ...(this.opts.toolbar ?? [])];

    const render = () => {
      this.toolbarEl.innerHTML = "";
      for (const b of all) {
        if (b.visible && !b.visible(this)) continue;
        const btn = el("button", { class: "widget-toolbtn", type: "button", title: b.title, "data-btn": b.id }, b.icon ?? b.title);
        on(btn, "click", (ev) => { stop(ev); b.onClick(this); render(); });
        this.toolbarEl.append(btn);
      }
    };
    render();

    on(this.burgerBtn, "click", (ev) => { stop(ev); this.showMenu(); });
  }

  showMenu() {
    document.querySelector(".widget-menu")?.remove();
    const menu = el("div", { class: "widget-menu", role: "menu" });

    const add = (label, fn, enabled = true) => {
      const b = el("button", { class: "widget-menu-item", type: "button" }, label);
      b.disabled = !enabled;
      on(b, "click", (ev) => { stop(ev); fn(); menu.remove(); });
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
      const t = ev.target;
      if (!t.closest(".widget-menu") && t !== this.burgerBtn) { menu.remove(); off(); }
    }, { capture: true });
  }

  wireInteractions(handleCorner) {
    const dragEnabled = this.opts.draggable ?? true;

    if (dragEnabled) {
      this.disposers.push(on(this.titleBar, "pointerdown", (ev) => {
        const p = ev;
        const t = ev.target;
        if (t.closest("button")) return;
        if (this.isMaximized()) return;

        if (this.isFloating()) this.beginFloatingDrag(p);
        else if (this.dash && this.cell) this.dash.layout.beginDockDrag(this, { x: p.clientX, y: p.clientY });
      }));
    }

    const resizable = this.opts.resizable ?? true;
    const startResize = () => (ev) => {
      if (!resizable) return;
      if (this.isMaximized()) return;

      const edges = { right: this.resizeAvail.right, bottom: this.resizeAvail.bottom };
      if (!edges.right && !edges.bottom) return;

      stop(ev);
      const startX = ev.clientX, startY = ev.clientY;
      const startRect = this.el.getBoundingClientRect();
      const startW = startRect.width, startH = startRect.height;

      const move = (e) => {
        const dx = e.clientX - startX;
        const dy = e.clientY - startY;

        if (this.isFloating()) {
          const w = Math.max(220, startW + (edges.right ? dx : 0));
          const h = Math.max(120, startH + (edges.bottom ? dy : 0));
          this.el.style.width = cssPx(w);
          this.el.style.height = cssPx(h);
        } else if (this.dash && this.cell) {
          this.dash.layout.resizeTracksFromCell(this.cell, dx, dy, edges);
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

  storageKey() { return `widget-state:${this.id}`; }

  getSavedState() {
    const raw = localStorage.getItem(this.storageKey());
    if (!raw) return null;
    try { return JSON.parse(raw); } catch { return null; }
  }

  saveState() {
    const payload = {
      state: this.state,
      minimized: this.minimized,
      dashId: this.dash?.id ?? this.prevDock?.dash.id ?? null,
      cell: this.cell,
    };
    if (this.isFloating() || this.isMaximized()) {
      payload.floating = { left: this.el.style.left, top: this.el.style.top, width: this.el.style.width, height: this.el.style.height };
    }
    localStorage.setItem(this.storageKey(), JSON.stringify(payload));
  }

  maybeRestoreState() {
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

  beginFloatingDrag(ev) {
    stop(ev);
    this.el.setPointerCapture?.(ev.pointerId);

    const startX = ev.clientX, startY = ev.clientY;
    const r = this.el.getBoundingClientRect();
    const ox = startX - r.left, oy = startY - r.top;

    const move = (e) => {
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

  // used by layout
  setDocked(dash, cell) {
    this.dash = dash;
    this.cell = cell;
    this.state = "docked";
    this.el.classList.remove("is-floating", "is-maximized");
    this.el.style.position = "";
    this.el.style.left = "";
    this.el.style.top = "";
    this.el.style.width = "";
    this.el.style.height = "";
  }
  setCell(cell) { this.cell = cell; }
  getCell() { return this.cell; }
  setDockedResizeAvailability(avail) {
    this.resizeAvail = avail;
    this.el.classList.toggle("no-resize", !avail.right && !avail.bottom);
  }

  // public API
  toggleMinimize() {
    this.minimized = !this.minimized;
    this.el.classList.toggle("is-minimized", this.minimized);
    this.saveState();
  }

  async refresh() {
    this.el.classList.add("is-refreshing");
    try { await this.opts.onRefresh?.(this); }
    finally { this.el.classList.remove("is-refreshing"); }
  }

  close() {
    this.opts.onClose?.(this);
    localStorage.removeItem(this.storageKey());
    this.destroy();
    this.el.remove();
  }

  destroy() {
    for (const d of this.disposers) d();
    this.disposers = [];
  }

  isFloating() { return this.state === "floating"; }
  isMaximized() { return this.state === "maximized"; }

  toggleFloating() { this.isFloating() ? this.dock() : this.float(); }

  openInWindow() {
    const win = window.open("", "_blank", "width=720,height=480");
    if (!win) return;
    const styles = Array.from(document.styleSheets).map((s) => {
      try { return Array.from(s.cssRules ?? []).map((r) => r.cssText).join("\n"); }
      catch { return ""; }
    }).join("\n");
    win.document.write(`<!doctype html><html><head><title>${this.getTitle()}</title><style>${styles}</style></head><body></body></html>`);
    win.document.body.append(this.el.cloneNode(true));
    win.document.close();
  }

  float() {
    if (this.isMaximized()) this.restore();

    if (!this.dash || !this.cell) {
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

    this.dash = this.prevDock.dash;
    this.cell = this.prevDock.cell;
    this.saveState();
  }

  dock() {
    if (!this.prevDock) {
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
    dash.layout.setWidget(cell, this);
    this.state = "docked";
    this.el.classList.remove("is-floating");
    this.prevDock = null;

    if (this.prevInlineStyle) this.el.setAttribute("style", this.prevInlineStyle);
    this.prevInlineStyle = null;

    this.el.style.width = "";
    this.el.style.height = "";
    this.el.style.left = "";
    this.el.style.top = "";
    this.el.style.position = "";
    this.saveState();
  }

  maximize() {
    if (this.isMaximized()) return;

    if (this.isFloating()) {
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

  restore() {
    if (!this.isMaximized()) return;

    this.el.classList.remove("is-maximized");
    this.state = this.prevDock ? "docked" : "floating";

    if (this.prevInlineStyle != null) this.el.setAttribute("style", this.prevInlineStyle);
    else this.el.removeAttribute("style");
    this.prevInlineStyle = null;

    if (this.prevDock) {
      const { dash, cell } = this.prevDock;
      dash.layout.setWidget(cell, this);
      this.prevDock = null;
    } else {
      this.el.classList.add("is-floating");
      this.el.style.position = "absolute";
    }
    this.saveState();
  }
}

// --- Demo boot ---
function section(label) {
  const d = document.createElement("div");
  d.className = "demo-section";
  d.innerHTML = `<strong>${label}</strong>`;
  return d;
}
function lorem(n = 1) {
  const s = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. ";
  return Array.from({ length: n }, () => s).join("");
}

function makeTabbedContent() {
  const tabs = [
    { id: "logs", title: "Logs", body: "Streaming recent log lines from services." },
    { id: "metrics", title: "Metrics", body: "CPU, memory, and queue depth charts." },
    { id: "notes", title: "Notes", body: "Scratchpad for runbook links and TODOs." },
  ];

  const container = el("div", { class: "inner-tabs" });
  const tablist = el("div", { class: "inner-tablist" });
  const panels = tabs.map((t) => el("div", { class: "inner-panel", "data-id": t.id }, t.body));

  let active = tabs[0].id;
  const setActive = (id) => {
    active = id;
    tablist.querySelectorAll(".inner-tab").forEach((b) => b.classList.toggle("is-active", b.dataset.id === id));
    panels.forEach((p) => p.classList.toggle("is-active", p.dataset.id === id));
  };

  for (const t of tabs) {
    const btn = el("button", { class: "inner-tab", type: "button", "data-id": t.id }, t.title);
    on(btn, "click", () => setActive(t.id));
    tablist.append(btn);
  }

  container.append(tablist, ...panels);
  setActive(active);
  return container;
}

function boot(mount) {
  const tabs = new DashboardTabs(mount);

  const dash1 = tabs.addDashboard(
    { title: "Dashboard A", icon: "🧭", closable: true },
    { grid: { rows: 2, cols: 2 }, template: { header: section("Header A (no widgets here)"), footer: section("Footer A") } }
  );

  const dash2 = tabs.addDashboard(
    { title: "Dashboard B", icon: "📊", closable: true },
    { grid: { rows: 2, cols: 2 }, template: { header: section("Header B"), footer: section("Footer B") } }
  );

  const mkWidget = (title, icon, hint) =>
    new Widget({
      title,
      icon,
      header: `<div class="hint">Header: ${hint}</div>`,
      content: `<div class="hint">${lorem(2)}</div><div class="mini-chart"></div>`,
      footer: `<div class="hint">Footer actions</div>`,
      onRefresh: async (w) => {
        await new Promise((r) => setTimeout(r, 350));
        const chart = w.el.querySelector(".mini-chart");
        if (chart) chart.textContent = `Refreshed at ${new Date().toLocaleTimeString()}`;
      },
    });

  const wA1 = mkWidget("Sales", "💶", "blue");
  const wA2 = mkWidget("Traffic", "📈", "green");
  const wA3 = mkWidget("Errors", "🧯", "red");
  const wA4 = mkWidget("Notes", "📝", "gray");

  dash1.layout.setWidget({ row: 0, col: 0 }, wA1);
  dash1.layout.setWidget({ row: 0, col: 1 }, wA2);
  dash1.layout.setWidget({ row: 1, col: 0 }, wA3);
  dash1.layout.setWidget({ row: 1, col: 1 }, wA4);

  const wB1 = mkWidget("Map", "🗺️", "indigo");
  const wB2 = mkWidget("Queue", "📬", "teal");
  const wB3 = mkWidget("Builds", "🧱", "orange");
  const wB4 = mkWidget("Alerts", "🚨", "yellow");
  const wTabbed = new Widget({
    title: "Dev Console",
    icon: "🧩",
    header: `<div class="hint">Header: slate</div>`,
    content: makeTabbedContent(),
    footer: `<div class="hint">Footer actions</div>`,
  });

  dash2.layout.setWidget({ row: 0, col: 0 }, wB1);
  dash2.layout.setWidget({ row: 0, col: 1 }, wB2);
  dash2.layout.setWidget({ row: 1, col: 0 }, wB3);
  dash2.layout.setWidget({ row: 1, col: 1 }, wB4);
  dash2.layout.setWidget({ row: 1, col: 1 }, wTabbed);

  tabs.activate(dash1.id);
}

boot(document.getElementById("app"));
