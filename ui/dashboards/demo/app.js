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

    this.el = el("div", { class: "dashboard-tabs" });
    this.tabStrip = el("div", { class: "dash-tab-strip" });

    // Add new tab button (like browsers)
    this.addTabBtn = el("button", { class: "dash-tab-add", type: "button", title: "Add new dashboard" }, "+");
    on(this.addTabBtn, "click", () => this.createNewDashboard());

    const tabContainer = el("div", { class: "dash-tab-container" });
    tabContainer.append(this.tabStrip, this.addTabBtn);

    this.content = el("div", { class: "dash-content" });

    this.el.append(tabContainer, this.content);
    mount.append(this.el);
  }

  createNewDashboard() {
    const count = this.tabs.size + 1;
    const dash = this.addDashboard(
      { title: `Dashboard ${count}`, icon: "📊", closable: true },
      { grid: { rows: 12, cols: 12 }, template: { header: null, footer: null } }
    );
    this.activate(dash.id);
    return dash;
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
    const burger = el("button", { class: "dash-tab-burger", type: "button", title: "Dashboard menu" }, "⌄");
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
      item("Add Widget…", () => {
        const dash = this.tabs.get(id);
        if (!dash) return;
        const title = prompt("Widget title?", "New Widget") || "New Widget";
        const widget = new Widget({
          title,
          icon: "📦",
          header: "",
          content: `<div class="hint">Empty widget content</div>`,
          footer: "",
        });
        // Find free space for a 4x4 widget
        const free = dash.layout.findFreeSpace(4, 4);
        if (free) {
          dash.layout.setWidget({ row: free.row, col: free.col, rowSpan: 4, colSpan: 4 }, widget);
        } else {
          // No free space, place at 0,0 with small size
          dash.layout.setWidget({ row: 0, col: 0, rowSpan: 3, colSpan: 3 }, widget);
        }
      }),
      item("Rename…", () => {
        const tabTitle = this.tabStrip.querySelector(`.dash-tab[data-dash-id="${id}"] .dash-tab-title`);
        const title = prompt("Dashboard name?", tabTitle?.textContent ?? "");
        if (title && tabTitle) tabTitle.textContent = title;
      }),
      item("▶ Slideshow", () => this.tabs.get(id)?.enterSlideshow()),
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
    this.layoutMode = opts.layoutMode ?? "grid";
    this.el = el("section", { class: "dashboard-view", "data-dashboard-id": id });
    this.header = el("div", { class: "dashboard-header" });
    this.main = el("div", { class: "dashboard-main" });
    this.footer = el("div", { class: "dashboard-footer" });

    if (opts.template?.header) this.header.append(opts.template.header);
    if (opts.template?.footer) this.footer.append(opts.template.footer);

    this.el.append(this.header, this.main, this.footer);

    // Create layout based on mode
    if (this.layoutMode === "dock") {
      this.layout = new DockLayout(this, opts.dock ?? {});
    } else {
      this.layout = new GridLayout(this, opts.grid ?? {});
    }

    // Slideshow state
    this.slideshowActive = false;
    this.slideshowIndex = 0;
    this.slideshowOverlay = null;
  }

  destroy() { this.layout.destroy(); }

  // Slideshow Mode
  getWidgets() {
    // Get all widgets from the layout
    if (this.layoutMode === "dock") {
      return Array.from(this.layout.widgets.values()).map(n => n.widget);
    } else {
      return Array.from(this.layout.placements.values()).map(p => p.widget);
    }
  }

  enterSlideshow() {
    const widgets = this.getWidgets();
    if (widgets.length === 0) return;

    this.slideshowActive = true;
    this.slideshowIndex = 0;

    // Create overlay
    this.slideshowOverlay = el("div", { class: "slideshow-overlay" });

    // Container for the widget
    this.slideshowContent = el("div", { class: "slideshow-content" });

    // Navigation controls
    const controls = el("div", { class: "slideshow-controls" });

    const prevBtn = el("button", { class: "slideshow-btn slideshow-prev", type: "button", title: "Previous" }, "◀");
    const nextBtn = el("button", { class: "slideshow-btn slideshow-next", type: "button", title: "Next" }, "▶");
    const closeBtn = el("button", { class: "slideshow-btn slideshow-close", type: "button", title: "Exit slideshow" }, "✕");
    const indicator = el("div", { class: "slideshow-indicator" });

    on(prevBtn, "click", () => this.slideshowPrev());
    on(nextBtn, "click", () => this.slideshowNext());
    on(closeBtn, "click", () => this.exitSlideshow());

    // Keyboard navigation
    this._slideshowKeyHandler = (e) => {
      if (e.key === "ArrowLeft") this.slideshowPrev();
      else if (e.key === "ArrowRight") this.slideshowNext();
      else if (e.key === "Escape") this.exitSlideshow();
    };
    window.addEventListener("keydown", this._slideshowKeyHandler);

    controls.append(prevBtn, indicator, nextBtn, closeBtn);
    this.slideshowOverlay.append(this.slideshowContent, controls);
    this.slideshowIndicator = indicator;

    document.body.append(this.slideshowOverlay);
    this.showSlideshowWidget(0);
  }

  showSlideshowWidget(index) {
    const widgets = this.getWidgets();
    if (widgets.length === 0) return;

    // Clamp index
    this.slideshowIndex = ((index % widgets.length) + widgets.length) % widgets.length;

    const widget = widgets[this.slideshowIndex];

    // Clear previous
    this.slideshowContent.innerHTML = "";

    // Clone the widget content for slideshow display
    const widgetClone = el("div", { class: "slideshow-widget" });
    widgetClone.innerHTML = widget.el.innerHTML;

    // Add widget header info
    const header = el("div", { class: "slideshow-widget-header" });
    header.innerHTML = `<span class="slideshow-icon">${widget.getIcon()}</span> <span class="slideshow-title">${widget.getTitle()}</span>`;

    widgetClone.prepend(header);
    this.slideshowContent.append(widgetClone);

    // Update indicator
    this.slideshowIndicator.textContent = `${this.slideshowIndex + 1} / ${widgets.length}`;
  }

  slideshowNext() {
    this.showSlideshowWidget(this.slideshowIndex + 1);
  }

  slideshowPrev() {
    this.showSlideshowWidget(this.slideshowIndex - 1);
  }

  exitSlideshow() {
    this.slideshowActive = false;
    window.removeEventListener("keydown", this._slideshowKeyHandler);
    this.slideshowOverlay?.remove();
    this.slideshowOverlay = null;
  }
}

class GridLayout {
  constructor(dash, opts) {
    this.dash = dash;
    this.gridCols = 12;
    this.gridRows = 12;
    this.cellHeight = 60; // px per row unit

    this.gridEl = el("div", { class: "dashboard-grid" });
    this.gridEl.style.display = "grid";
    this.gridEl.style.gridTemplateColumns = `repeat(${this.gridCols}, 1fr)`;
    this.gridEl.style.gridTemplateRows = `repeat(${this.gridRows}, ${this.cellHeight}px)`;
    this.gridEl.style.gap = "4px";
    this.gridEl.style.height = "100%";
    this.gridEl.style.position = "relative";
    dash.main.append(this.gridEl);

    // Widget placements: Map<widgetId, { row, col, rowSpan, colSpan, widget }>
    this.placements = new Map();

    // Drag state
    this.dragging = null;
    this.dragGhost = null;
    this.hoverTarget = null;
    this.hoverTimer = null;
    this.swapModeActive = false;

    this.load();
  }

  // Place a widget on the grid
  setWidget(placement, widget) {
    const p = {
      row: clamp(placement.row ?? 0, 0, this.gridRows - 1),
      col: clamp(placement.col ?? 0, 0, this.gridCols - 1),
      rowSpan: clamp(placement.rowSpan ?? 3, 1, this.gridRows),
      colSpan: clamp(placement.colSpan ?? 6, 1, this.gridCols),
      widget,
    };

    // Check for collision and find free space if needed
    const existing = this.getWidgetAt(p.row, p.col);
    if (existing && existing !== widget) {
      // Find adjacent free space
      const free = this.findFreeSpace(p.colSpan, p.rowSpan);
      if (free) {
        p.row = free.row;
        p.col = free.col;
      }
    }

    this.placements.set(widget.id, p);
    this.renderWidget(widget);
    widget.setDocked(this.dash, { row: p.row, col: p.col });
    widget.setCell({ row: p.row, col: p.col, rowSpan: p.rowSpan, colSpan: p.colSpan });
    this.save();
  }

  renderWidget(widget) {
    const p = this.placements.get(widget.id);
    if (!p) return;

    widget.el.style.gridColumn = `${p.col + 1} / span ${p.colSpan}`;
    widget.el.style.gridRow = `${p.row + 1} / span ${p.rowSpan}`;
    widget.el.style.position = "";
    widget.el.style.left = "";
    widget.el.style.top = "";
    widget.el.style.width = "";
    widget.el.style.height = "";

    if (!widget.el.parentNode || widget.el.parentNode !== this.gridEl) {
      this.gridEl.append(widget.el);
    }
  }

  getWidgetAt(row, col) {
    for (const [id, p] of this.placements) {
      if (row >= p.row && row < p.row + p.rowSpan &&
        col >= p.col && col < p.col + p.colSpan) {
        return p.widget;
      }
    }
    return null;
  }

  findFreeSpace(colSpan, rowSpan) {
    for (let r = 0; r <= this.gridRows - rowSpan; r++) {
      for (let c = 0; c <= this.gridCols - colSpan; c++) {
        if (!this.isOccupied(r, c, rowSpan, colSpan)) {
          return { row: r, col: c };
        }
      }
    }
    return null;
  }

  isOccupied(row, col, rowSpan, colSpan) {
    for (let r = row; r < row + rowSpan; r++) {
      for (let c = col; c < col + colSpan; c++) {
        if (this.getWidgetAt(r, c)) return true;
      }
    }
    return false;
  }

  cellFromPoint(clientX, clientY) {
    const rect = this.gridEl.getBoundingClientRect();
    if (clientX < rect.left || clientX > rect.right || clientY < rect.top || clientY > rect.bottom) {
      return null;
    }

    const colWidth = rect.width / this.gridCols;
    const rowHeight = rect.height / this.gridRows;

    const col = Math.floor((clientX - rect.left) / colWidth);
    const row = Math.floor((clientY - rect.top) / rowHeight);

    return { row: clamp(row, 0, this.gridRows - 1), col: clamp(col, 0, this.gridCols - 1) };
  }

  // Check if area is occupied (excluding a specific widget)
  isOccupiedExcluding(row, col, rowSpan, colSpan, excludeWidgetId) {
    for (let r = row; r < row + rowSpan; r++) {
      for (let c = col; c < col + colSpan; c++) {
        for (const [id, p] of this.placements) {
          if (id === excludeWidgetId) continue;
          if (r >= p.row && r < p.row + p.rowSpan && c >= p.col && c < p.col + p.colSpan) {
            return true;
          }
        }
      }
    }
    return false;
  }

  // Find nearest free space excluding a widget
  findNearestFreeExcluding(row, col, colSpan, rowSpan, excludeWidgetId) {
    // First try the exact position
    const clampedRow = Math.min(row, this.gridRows - rowSpan);
    const clampedCol = Math.min(col, this.gridCols - colSpan);
    if (!this.isOccupiedExcluding(clampedRow, clampedCol, rowSpan, colSpan, excludeWidgetId)) {
      return { row: clampedRow, col: clampedCol };
    }

    // Search in expanding rings
    for (let d = 1; d < Math.max(this.gridRows, this.gridCols); d++) {
      for (let dr = -d; dr <= d; dr++) {
        for (let dc = -d; dc <= d; dc++) {
          if (Math.abs(dr) !== d && Math.abs(dc) !== d) continue;
          const r = clampedRow + dr, c = clampedCol + dc;
          if (r >= 0 && r <= this.gridRows - rowSpan && c >= 0 && c <= this.gridCols - colSpan) {
            if (!this.isOccupiedExcluding(r, c, rowSpan, colSpan, excludeWidgetId)) {
              return { row: r, col: c };
            }
          }
        }
      }
    }
    return null;
  }

  // Create or update drop preview placeholder
  createDropPreview() {
    if (!this.dropPreview) {
      this.dropPreview = el("div", { class: "grid-drop-preview" });
      this.gridEl.append(this.dropPreview);
    }
    return this.dropPreview;
  }

  updateDropPreview(row, col, rowSpan, colSpan, isValid) {
    const preview = this.createDropPreview();
    preview.style.gridColumn = `${col + 1} / span ${colSpan}`;
    preview.style.gridRow = `${row + 1} / span ${rowSpan}`;
    preview.style.display = "block";
    preview.classList.toggle("is-invalid", !isValid);
  }

  hideDropPreview() {
    if (this.dropPreview) {
      this.dropPreview.style.display = "none";
    }
  }

  // Drag and Drop
  beginDrag(widget, ev) {
    if (this.dragging) return;

    const p = this.placements.get(widget.id);
    if (!p) return;

    this.dragging = { widget, originalPlacement: { row: p.row, col: p.col, rowSpan: p.rowSpan, colSpan: p.colSpan } };

    // Create ghost (follows cursor)
    const rect = widget.el.getBoundingClientRect();
    this.dragGhost = el("div", { class: "widget-drag-ghost" });
    this.dragGhost.style.width = cssPx(rect.width);
    this.dragGhost.style.height = cssPx(rect.height);
    this.dragGhost.style.left = cssPx(rect.left);
    this.dragGhost.style.top = cssPx(rect.top);
    document.body.append(this.dragGhost);

    widget.el.classList.add("is-dragging");

    const move = (e) => {
      this.dragGhost.style.left = cssPx(e.clientX - rect.width / 2);
      this.dragGhost.style.top = cssPx(e.clientY - rect.height / 2);

      const cell = this.cellFromPoint(e.clientX, e.clientY);
      this.updateDropTarget(cell, widget, p);
    };

    const up = (e) => {
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);
      this.endDrag(e);
    };

    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
  }

  updateDropTarget(cell, draggedWidget, draggedP) {
    // Clear previous highlights
    this.gridEl.querySelectorAll(".grid-drop-target, .grid-swap-target").forEach(n => {
      n.classList.remove("grid-drop-target", "grid-swap-target");
    });

    if (!cell) {
      this.clearHoverTimer();
      this.hideDropPreview();
      return;
    }

    const targetWidget = this.getWidgetAt(cell.row, cell.col);

    // Calculate where the widget would land
    const targetRow = Math.min(cell.row, this.gridRows - draggedP.rowSpan);
    const targetCol = Math.min(cell.col, this.gridCols - draggedP.colSpan);

    // Check if this position is valid (excluding the dragged widget itself)
    const isValid = !this.isOccupiedExcluding(targetRow, targetCol, draggedP.rowSpan, draggedP.colSpan, draggedWidget.id);

    // Show drop preview
    this.updateDropPreview(targetRow, targetCol, draggedP.rowSpan, draggedP.colSpan, isValid || (targetWidget && targetWidget !== draggedWidget));

    if (targetWidget && targetWidget !== draggedWidget) {
      // Hovering over another widget
      if (this.hoverTarget !== targetWidget) {
        this.clearHoverTimer();
        this.hoverTarget = targetWidget;
        this.swapModeActive = false;

        // Start timer for swap mode
        this.hoverTimer = setTimeout(() => {
          this.swapModeActive = true;
          targetWidget.el.classList.add("grid-swap-target");
        }, 1500);
      }

      if (this.swapModeActive) {
        targetWidget.el.classList.add("grid-swap-target");
      } else {
        targetWidget.el.classList.add("grid-drop-target");
      }
    } else {
      this.clearHoverTimer();
    }
  }

  clearHoverTimer() {
    if (this.hoverTimer) {
      clearTimeout(this.hoverTimer);
      this.hoverTimer = null;
    }
    this.hoverTarget = null;
    this.swapModeActive = false;
  }

  endDrag(ev) {
    if (!this.dragging) return;

    const { widget, originalPlacement } = this.dragging;

    widget.el.classList.remove("is-dragging");
    this.dragGhost?.remove();
    this.dragGhost = null;
    this.hideDropPreview();

    this.gridEl.querySelectorAll(".grid-drop-target, .grid-swap-target").forEach(n => {
      n.classList.remove("grid-drop-target", "grid-swap-target");
    });

    const cell = this.cellFromPoint(ev.clientX, ev.clientY);

    if (cell) {
      const targetWidget = this.getWidgetAt(cell.row, cell.col);
      const p = this.placements.get(widget.id);

      if (targetWidget && targetWidget !== widget) {
        if (this.swapModeActive) {
          // SWAP widgets - exchange BOTH positions AND sizes
          const targetP = this.placements.get(targetWidget.id);

          // Store all original values
          const srcRow = p.row, srcCol = p.col, srcRowSpan = p.rowSpan, srcColSpan = p.colSpan;
          const dstRow = targetP.row, dstCol = targetP.col, dstRowSpan = targetP.rowSpan, dstColSpan = targetP.colSpan;

          // Swap everything - source gets destination's position AND size
          p.row = dstRow;
          p.col = dstCol;
          p.rowSpan = dstRowSpan;
          p.colSpan = dstColSpan;

          // Target gets source's position AND size
          targetP.row = srcRow;
          targetP.col = srcCol;
          targetP.rowSpan = srcRowSpan;
          targetP.colSpan = srcColSpan;

          this.renderWidget(widget);
          this.renderWidget(targetWidget);
          widget.setCell({ row: p.row, col: p.col, rowSpan: p.rowSpan, colSpan: p.colSpan });
          targetWidget.setCell({ row: targetP.row, col: targetP.col, rowSpan: targetP.rowSpan, colSpan: targetP.colSpan });
        } else {
          // Position at nearest free space
          const free = this.findNearestFreeExcluding(cell.row, cell.col, p.colSpan, p.rowSpan, widget.id);
          if (free) {
            p.row = free.row;
            p.col = free.col;
            this.renderWidget(widget);
            widget.setCell({ row: p.row, col: p.col, rowSpan: p.rowSpan, colSpan: p.colSpan });
          }
          // else: snap back (placement unchanged)
        }
      } else {
        // Empty area or same widget - try to move there
        const targetRow = Math.min(cell.row, this.gridRows - p.rowSpan);
        const targetCol = Math.min(cell.col, this.gridCols - p.colSpan);

        if (!this.isOccupiedExcluding(targetRow, targetCol, p.rowSpan, p.colSpan, widget.id)) {
          p.row = targetRow;
          p.col = targetCol;
          this.renderWidget(widget);
          widget.setCell({ row: p.row, col: p.col, rowSpan: p.rowSpan, colSpan: p.colSpan });
        } else {
          // Find nearest free space
          const free = this.findNearestFreeExcluding(cell.row, cell.col, p.colSpan, p.rowSpan, widget.id);
          if (free) {
            p.row = free.row;
            p.col = free.col;
            this.renderWidget(widget);
            widget.setCell({ row: p.row, col: p.col, rowSpan: p.rowSpan, colSpan: p.colSpan });
          }
        }
      }
    }

    this.clearHoverTimer();
    this.dragging = null;
    this.save();
  }

  findNearestFree(row, col, colSpan, rowSpan) {
    return this.findNearestFreeExcluding(row, col, colSpan, rowSpan, null);
  }

  // Resize
  beginResize(widget, handle, ev) {
    const p = this.placements.get(widget.id);
    if (!p) return;

    stop(ev);
    const startX = ev.clientX, startY = ev.clientY;
    const startColSpan = p.colSpan, startRowSpan = p.rowSpan;
    const rect = this.gridEl.getBoundingClientRect();
    const colWidth = rect.width / this.gridCols;
    const rowHeight = rect.height / this.gridRows;

    const move = (e) => {
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;

      const dCols = Math.round(dx / colWidth);
      const dRows = Math.round(dy / rowHeight);

      p.colSpan = clamp(startColSpan + dCols, 1, this.gridCols - p.col);
      p.rowSpan = clamp(startRowSpan + dRows, 1, this.gridRows - p.row);

      this.renderWidget(widget);
    };

    const up = () => {
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);
      widget.setCell({ row: p.row, col: p.col, rowSpan: p.rowSpan, colSpan: p.colSpan });
      this.save();
    };

    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
  }

  detachWidget(widget) {
    this.placements.delete(widget.id);
    widget.el.remove();
  }

  storageKey() { return `dash-layout:${this.dash.id}`; }

  save() {
    const data = {};
    for (const [id, p] of this.placements) {
      data[id] = { row: p.row, col: p.col, rowSpan: p.rowSpan, colSpan: p.colSpan };
    }
    localStorage.setItem(this.storageKey(), JSON.stringify(data));
  }

  load() {
    const raw = localStorage.getItem(this.storageKey());
    if (!raw) return;
    try {
      this.savedPlacements = JSON.parse(raw);
    } catch {
      this.savedPlacements = {};
    }
  }

  getSavedPlacement(widgetId) {
    return this.savedPlacements?.[widgetId] ?? null;
  }

  destroy() { this.save(); }
  reset() { localStorage.removeItem(this.storageKey()); }
}

// --- DockLayout (GoldenLayout-inspired) ---
class DockLayout {
  constructor(dash, opts) {
    this.dash = dash;
    this.minSize = opts.minSize ?? 0.1; // 10% minimum

    this.containerEl = el("div", { class: "dock-container" });
    this.containerEl.style.height = "100%";
    this.containerEl.style.display = "flex";
    this.containerEl.style.flexDirection = "column";
    dash.main.append(this.containerEl);

    // Root node of the layout tree
    // Node types: { type: "row"|"column"|"stack"|"widget", children?: [], widget?: Widget, size: number }
    this.root = null;
    this.widgets = new Map(); // widgetId -> node reference

    // Drag state
    this.dragging = null;
    this.dropPreview = null;
    this.activeDropZone = null;

    this.load();
    this.render();
  }

  // Create a node
  createNode(type, opts = {}) {
    return {
      id: uid("node"),
      type,
      size: opts.size ?? 1,
      children: opts.children ?? [],
      widget: opts.widget ?? null,
      el: null
    };
  }

  // Add widget to layout
  setWidget(placement, widget) {
    this.addWidget(widget);
  }

  addWidget(widget, opts = {}) {
    const node = this.createNode("widget", { widget, size: 1 });
    this.widgets.set(widget.id, node);

    if (!this.root) {
      // First widget - becomes the root
      this.root = node;
    } else if (opts.target && opts.position) {
      // Insert relative to a target
      this.insertAt(node, opts.target, opts.position);
    } else {
      // Add to root as a new column/row
      if (this.root.type === "widget") {
        // Wrap in a row
        const oldRoot = this.root;
        this.root = this.createNode("row", { children: [oldRoot, node], size: 1 });
        oldRoot.size = 0.5;
        node.size = 0.5;
      } else if (this.root.type === "row") {
        // Add to the row
        this.root.children.push(node);
        this.normalizeChildSizes(this.root);
      } else if (this.root.type === "column") {
        // Add to last row or create new row
        this.root.children.push(node);
        this.normalizeChildSizes(this.root);
      }
    }

    widget.setDocked(this.dash, { row: 0, col: 0 });
    this.render();
    this.save();
  }

  // Insert a node relative to a target
  insertAt(node, targetNode, position) {
    const parent = this.findParent(this.root, targetNode);

    if (position === "center") {
      // Create a stack (tabs)
      if (targetNode.type === "stack") {
        targetNode.children.push(node);
      } else if (targetNode.type === "widget") {
        // Convert widget node to stack
        const stackNode = this.createNode("stack", {
          children: [{ ...targetNode }, node],
          size: targetNode.size
        });
        this.replaceNode(parent, targetNode, stackNode);
      }
    } else if (position === "left" || position === "right") {
      // Split horizontally
      this.splitNode(parent, targetNode, node, "row", position === "left" ? "before" : "after");
    } else if (position === "top" || position === "bottom") {
      // Split vertically  
      this.splitNode(parent, targetNode, node, "column", position === "top" ? "before" : "after");
    }
  }

  splitNode(parent, targetNode, newNode, direction, insertPos) {
    const targetSize = targetNode.size;
    targetNode.size = 0.5;
    newNode.size = 0.5;

    const children = insertPos === "before" ? [newNode, targetNode] : [targetNode, newNode];
    const containerNode = this.createNode(direction, { children, size: targetSize });

    if (!parent) {
      // Target is root
      this.root = containerNode;
    } else if (parent.type === direction) {
      // Same direction - just insert as sibling
      const idx = parent.children.indexOf(targetNode);
      if (insertPos === "before") {
        parent.children.splice(idx, 0, newNode);
      } else {
        parent.children.splice(idx + 1, 0, newNode);
      }
      this.normalizeChildSizes(parent);
    } else {
      // Different direction - wrap in new container
      this.replaceNode(parent, targetNode, containerNode);
    }
  }

  replaceNode(parent, oldNode, newNode) {
    if (!parent) {
      this.root = newNode;
    } else {
      const idx = parent.children.indexOf(oldNode);
      if (idx >= 0) parent.children[idx] = newNode;
    }
  }

  findParent(current, target) {
    if (!current || !current.children) return null;
    for (const child of current.children) {
      if (child === target) return current;
      const found = this.findParent(child, target);
      if (found) return found;
    }
    return null;
  }

  findNodeByWidgetId(widgetId) {
    return this.widgets.get(widgetId);
  }

  normalizeChildSizes(node) {
    if (!node.children || node.children.length === 0) return;
    const total = node.children.reduce((sum, c) => sum + c.size, 0);
    for (const child of node.children) {
      child.size = child.size / total;
    }
  }

  // Render the layout tree to DOM
  render() {
    this.containerEl.innerHTML = "";
    if (this.root) {
      const rootEl = this.renderNode(this.root);
      this.containerEl.append(rootEl);
    }
  }

  renderNode(node) {
    if (node.type === "widget") {
      return this.renderWidgetNode(node);
    } else if (node.type === "row" || node.type === "column") {
      return this.renderContainerNode(node);
    } else if (node.type === "stack") {
      return this.renderStackNode(node);
    }
    return el("div");
  }

  renderWidgetNode(node) {
    const wrapper = el("div", { class: "dock-widget-wrapper" });
    wrapper.style.flex = `${node.size}`;
    wrapper.style.minWidth = "0";
    wrapper.style.minHeight = "0";
    wrapper.style.position = "relative";

    if (node.widget) {
      wrapper.append(node.widget.el);
      node.widget.el.style.width = "100%";
      node.widget.el.style.height = "100%";
      node.widget.el.style.position = "absolute";
      node.widget.el.style.inset = "0";
    }

    // Store reference for drop zone detection
    node.el = wrapper;
    wrapper._dockNode = node;

    return wrapper;
  }

  renderContainerNode(node) {
    const container = el("div", { class: `dock-${node.type}` });
    container.style.display = "flex";
    container.style.flexDirection = node.type === "row" ? "row" : "column";
    container.style.flex = `${node.size}`;
    container.style.gap = "4px";
    container.style.minWidth = "0";
    container.style.minHeight = "0";

    node.children.forEach((child, i) => {
      const childEl = this.renderNode(child);
      container.append(childEl);

      // Add resize handle between children
      if (i < node.children.length - 1) {
        const handle = el("div", { class: `dock-resize-handle dock-resize-${node.type === "row" ? "h" : "v"}` });
        handle._resizeIndex = i;
        handle._parentNode = node;
        on(handle, "pointerdown", (ev) => this.beginResize(node, i, ev));
        container.append(handle);
      }
    });

    node.el = container;
    return container;
  }

  renderStackNode(node) {
    const container = el("div", { class: "dock-stack" });
    container.style.flex = `${node.size}`;
    container.style.display = "flex";
    container.style.flexDirection = "column";
    container.style.minWidth = "0";
    container.style.minHeight = "0";

    // Tab bar
    const tabBar = el("div", { class: "dock-stack-tabs" });
    const content = el("div", { class: "dock-stack-content" });
    content.style.flex = "1";
    content.style.position = "relative";
    content.style.minHeight = "0";

    node.children.forEach((child, i) => {
      const isActive = i === (node.activeIndex ?? 0);
      const tab = el("button", { class: `dock-stack-tab ${isActive ? "is-active" : ""}`, type: "button" });
      tab.textContent = child.widget?.getTitle() ?? `Tab ${i + 1}`;
      on(tab, "click", () => {
        node.activeIndex = i;
        this.render();
      });
      tabBar.append(tab);

      if (isActive && child.widget) {
        content.append(child.widget.el);
        child.widget.el.style.position = "absolute";
        child.widget.el.style.inset = "0";
      }
    });

    container.append(tabBar, content);
    node.el = container;
    return container;
  }

  // Drag and Drop
  beginDrag(widget, ev) {
    const node = this.findNodeByWidgetId(widget.id);
    if (!node) return;

    this.dragging = { widget, node };

    // Create drag ghost
    const rect = widget.el.getBoundingClientRect();
    this.dragGhost = el("div", { class: "widget-drag-ghost" });
    this.dragGhost.style.width = cssPx(rect.width);
    this.dragGhost.style.height = cssPx(rect.height);
    this.dragGhost.style.left = cssPx(rect.left);
    this.dragGhost.style.top = cssPx(rect.top);
    document.body.append(this.dragGhost);

    widget.el.classList.add("is-dragging");

    const move = (e) => {
      this.dragGhost.style.left = cssPx(e.clientX - rect.width / 2);
      this.dragGhost.style.top = cssPx(e.clientY - rect.height / 2);
      this.updateDropZone(e);
    };

    const up = (e) => {
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);
      this.endDrag(e);
    };

    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
  }

  updateDropZone(ev) {
    this.clearDropZone();

    const target = this.findDropTarget(ev.clientX, ev.clientY);
    if (!target || target.node === this.dragging.node) return;

    const zone = this.computeDropZone(target.el, ev.clientX, ev.clientY);
    this.activeDropZone = { node: target.node, zone };

    // Show drop indicator
    this.showDropIndicator(target.el, zone);
  }

  findDropTarget(x, y) {
    // Find the deepest widget wrapper under the cursor
    const elements = document.elementsFromPoint(x, y);
    for (const el of elements) {
      if (el._dockNode && el._dockNode.type === "widget") {
        return { el, node: el._dockNode };
      }
    }
    return null;
  }

  computeDropZone(el, x, y) {
    const rect = el.getBoundingClientRect();
    const relX = (x - rect.left) / rect.width;
    const relY = (y - rect.top) / rect.height;

    // Edge zones are 20% each, center is 60%
    const edgeSize = 0.2;

    if (relX < edgeSize) return "left";
    if (relX > 1 - edgeSize) return "right";
    if (relY < edgeSize) return "top";
    if (relY > 1 - edgeSize) return "bottom";
    return "center";
  }

  showDropIndicator(targetEl, zone) {
    this.clearDropZone();

    const indicator = el("div", { class: `dock-drop-indicator dock-drop-${zone}` });
    targetEl.append(indicator);
    this.dropPreview = indicator;

    // Zone labels
    const labels = { left: "◀", right: "▶", top: "▲", bottom: "▼", center: "⊞ Tab" };
    indicator.textContent = labels[zone] ?? "";
  }

  clearDropZone() {
    this.dropPreview?.remove();
    this.dropPreview = null;
  }

  endDrag(ev) {
    if (!this.dragging) return;

    const { widget, node } = this.dragging;

    widget.el.classList.remove("is-dragging");
    this.dragGhost?.remove();
    this.dragGhost = null;
    this.clearDropZone();

    if (this.activeDropZone) {
      const { node: targetNode, zone } = this.activeDropZone;
      if (targetNode !== node) {
        // Remove from current position
        this.removeNode(node);
        // Insert at new position
        this.insertAt(node, targetNode, zone);
        this.cleanupTree();
        this.render();
        this.save();
      }
    }

    this.activeDropZone = null;
    this.dragging = null;
  }

  removeNode(node) {
    const parent = this.findParent(this.root, node);
    if (parent && parent.children) {
      const idx = parent.children.indexOf(node);
      if (idx >= 0) parent.children.splice(idx, 1);
    } else if (this.root === node) {
      this.root = null;
    }
  }

  cleanupTree() {
    // Remove empty containers and unwrap single-child containers
    this.root = this.cleanupNode(this.root);
  }

  cleanupNode(node) {
    if (!node) return null;

    if (node.children) {
      node.children = node.children.map(c => this.cleanupNode(c)).filter(c => c !== null);

      if (node.children.length === 0) return null;
      if (node.children.length === 1 && (node.type === "row" || node.type === "column")) {
        // Unwrap single child
        const child = node.children[0];
        child.size = node.size;
        return child;
      }
    }

    return node;
  }

  // Resize handles
  beginResize(parentNode, idx, ev) {
    stop(ev);
    const child1 = parentNode.children[idx];
    const child2 = parentNode.children[idx + 1];
    const startSize1 = child1.size;
    const startSize2 = child2.size;
    const totalSize = startSize1 + startSize2;

    const isHorizontal = parentNode.type === "row";
    const startPos = isHorizontal ? ev.clientX : ev.clientY;
    const containerRect = parentNode.el.getBoundingClientRect();
    const containerSize = isHorizontal ? containerRect.width : containerRect.height;

    const move = (e) => {
      const currentPos = isHorizontal ? e.clientX : e.clientY;
      const delta = (currentPos - startPos) / containerSize;

      let newSize1 = startSize1 + delta;
      let newSize2 = startSize2 - delta;

      // Enforce minimum sizes
      if (newSize1 < this.minSize) {
        newSize1 = this.minSize;
        newSize2 = totalSize - newSize1;
      }
      if (newSize2 < this.minSize) {
        newSize2 = this.minSize;
        newSize1 = totalSize - newSize2;
      }

      child1.size = newSize1;
      child2.size = newSize2;

      // Update inline styles directly for smooth resize
      child1.el.style.flex = `${newSize1}`;
      child2.el.style.flex = `${newSize2}`;
    };

    const up = () => {
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);
      this.save();
    };

    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
  }

  // Persistence
  storageKey() { return `dash-dock:${this.dash.id}`; }

  save() {
    if (!this.root) return;
    const data = this.serializeNode(this.root);
    localStorage.setItem(this.storageKey(), JSON.stringify(data));
  }

  serializeNode(node) {
    const data = { type: node.type, size: node.size };
    if (node.widget) data.widgetId = node.widget.id;
    if (node.children) data.children = node.children.map(c => this.serializeNode(c));
    if (node.activeIndex !== undefined) data.activeIndex = node.activeIndex;
    return data;
  }

  load() {
    const raw = localStorage.getItem(this.storageKey());
    if (!raw) return;
    try {
      this.savedLayout = JSON.parse(raw);
    } catch {
      this.savedLayout = null;
    }
  }

  findFreeSpace(colSpan, rowSpan) {
    // For dock layout, always return a valid position (we'll add to the layout)
    return { row: 0, col: 0 };
  }

  detachWidget(widget) {
    const node = this.findNodeByWidgetId(widget.id);
    if (node) {
      this.removeNode(node);
      this.widgets.delete(widget.id);
      this.cleanupTree();
      this.render();
    }
  }

  destroy() { this.save(); }
  reset() { localStorage.removeItem(this.storageKey()); this.root = null; this.render(); }
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
    this.burgerBtn = el("button", { class: "widget-burger", type: "button", title: "Widget menu" }, "⌄");
    this.titleBar = el("div", { class: "widget-titlebar" }, iconEl, this.titleText, this.toolbarEl, this.burgerBtn);

    this.sectionHeader = el("div", { class: "widget-section widget-header" });
    this.sectionContent = el("div", { class: "widget-section widget-content" });
    this.sectionFooter = el("div", { class: "widget-section widget-footer" });

    this.setSection(this.sectionHeader, opts.header ?? "");
    this.setSection(this.sectionContent, opts.content ?? "");
    this.setSection(this.sectionFooter, opts.footer ?? "");

    const handleBR = el("div", { class: "widget-resize-handle handle-br", title: "Resize" });

    // allow footer modifications
    this.footerBar = el("div", { class: "widget-footer-actions", style: "display:flex; gap:4px; margin-right:auto" });
    // if options provided a string footer, we wrap it or append to it. 
    // For this demo, let's just make the footer flex and put our bar in it.
    if (this.sectionFooter.childNodes.length === 0) {
      this.sectionFooter.append(this.footerBar);
    } else {
      // if user supplied something, we prepend our bar or append? 
      // User said "button bar on bottom left".
      this.sectionFooter.prepend(this.footerBar);
    }

    this.el.append(this.titleBar, this.sectionHeader, this.sectionContent, this.sectionFooter, handleBR);

    this.buildToolbar();
    this.wireInteractions(handleBR);
  }

  addFooterBtn(icon, title, onClick) {
    const btn = el("button", { class: "footer-icon-btn", type: "button", title: title }, icon);
    on(btn, "click", (ev) => {
      stop(ev);
      onClick(this);
    });
    this.footerBar.append(btn);
    return btn;
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

    const items = [
      {
        label: "Change Color...",
        click: () => this.showColorPicker(),
      },
      {
        label: this.minimized ? "Restore from minimize" : "Minimize",
        click: () => this.toggleMinimize(),
      },
      {
        label: this.isMaximized() ? "Restore size" : "Maximize",
        click: () => (this.isMaximized() ? this.restore() : this.maximize()),
      },
      {
        label: this.isFloating() ? "Dock widget" : "Decouple (float)",
        click: () => this.toggleFloating(),
      },
      {
        label: "Refresh",
        click: () => void this.refresh(),
        enabled: !!this.opts.onRefresh,
      },
      {
        label: "Close",
        click: () => this.close(),
      },
    ];

    for (const item of items) {
      const b = el("button", { class: "widget-menu-item", type: "button" }, item.label);
      b.disabled = item.enabled === false;
      on(b, "click", (ev) => { stop(ev); item.click(); menu.remove(); });
      menu.append(b);
    }

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
        const t = ev.target;
        if (t.closest("button")) return;
        if (this.isMaximized()) return;

        if (this.isFloating()) {
          this.beginFloatingDrag(ev);
        } else if (this.dash && this.dash.layout) {
          // Use new GridLayout drag
          this.dash.layout.beginDrag(this, ev);
        }
      }));
    }

    const resizable = this.opts.resizable ?? true;

    this.disposers.push(on(handleCorner, "pointerdown", (ev) => {
      if (!resizable) return;
      if (this.isMaximized()) return;

      if (this.isFloating()) {
        // Floating resize (original behavior)
        stop(ev);
        const startX = ev.clientX, startY = ev.clientY;
        const startRect = this.el.getBoundingClientRect();
        const startW = startRect.width, startH = startRect.height;

        const move = (e) => {
          const dx = e.clientX - startX;
          const dy = e.clientY - startY;
          const w = Math.max(220, startW + dx);
          const h = Math.max(120, startH + dy);
          this.el.style.width = cssPx(w);
          this.el.style.height = cssPx(h);
        };

        const up = () => {
          window.removeEventListener("pointermove", move, true);
          window.removeEventListener("pointerup", up, true);
          this.saveState();
        };

        window.addEventListener("pointermove", move, true);
        window.addEventListener("pointerup", up, true);
      } else if (this.dash && this.dash.layout) {
        // Use new GridLayout resize
        this.dash.layout.beginResize(this, handleCorner, ev);
      }
    }));
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

  showColorPicker() {
    const overlay = el("div", { class: "modal-overlay" });
    const box = el("div", { class: "modal-box" });
    const title = el("div", { class: "modal-title" }, "Widget Color");

    const input = el("input", { type: "color", class: "color-picker-input", value: "#ffffff" });
    // Try to get current bg if any
    const currentBg = this.titleBar.style.backgroundColor;
    if (currentBg) input.value = this.rgbToHex(currentBg) || "#ffffff";

    const actions = el("div", { class: "modal-actions" });
    const cancel = el("button", { class: "widget-toolbtn", style: "width:auto; padding:0 8px;" }, "Cancel");
    const save = el("button", { class: "widget-toolbtn", style: "width:auto; padding:0 8px; background:var(--accent); color:#fff;" }, "Apply");

    on(cancel, "click", () => overlay.remove());
    on(save, "click", () => {
      this.titleBar.style.backgroundColor = input.value;
      // Check contrast? 
      this.titleBar.style.borderRadius = "8px 8px 0 0"; // Ensure it looks like a highlighted bar
      overlay.remove();
    });

    on(overlay, "click", (e) => { if (e.target === overlay) overlay.remove(); });

    actions.append(cancel, save);
    box.append(title, input, actions);
    overlay.append(box);
    document.body.append(overlay);
  }

  rgbToHex(rgb) {
    if (!rgb) return null;
    const res = rgb.match(/\d+/g);
    if (!res) return null;
    return "#" + res.map(x => parseInt(x).toString(16).padStart(2, '0')).join('');
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
      footer: "", // empty footer container for our buttons
      onRefresh: async (w) => {
        await new Promise((r) => setTimeout(r, 350));
        const chart = w.el.querySelector(".mini-chart");
        if (chart) chart.textContent = `Refreshed at ${new Date().toLocaleTimeString()}`;
      },
    });

  const configWidget = (w) => {
    w.addFooterBtn("📎", "Attach", (inst) => alert(`Attach on ${inst.getTitle()}`));
    w.addFooterBtn("🕒", "History", (inst) => alert(`History on ${inst.getTitle()}`));
    w.addFooterBtn("📄", "Document", (inst) => alert(`Doc on ${inst.getTitle()}`));
    return w;
  };

  const wA1 = configWidget(mkWidget("Sales", "💶", "blue"));
  const wA2 = configWidget(mkWidget("Traffic", "📈", "green"));
  const wA3 = configWidget(mkWidget("Errors", "🧯", "red"));
  const wA4 = configWidget(mkWidget("Notes", "📝", "gray"));

  // Dashboard A: 4 widgets in a 2x2 layout on a 12x12 grid
  // Each widget spans 6 cols x 6 rows = fills half width, half height
  dash1.layout.setWidget({ row: 0, col: 0, rowSpan: 6, colSpan: 6 }, wA1);
  dash1.layout.setWidget({ row: 0, col: 6, rowSpan: 6, colSpan: 6 }, wA2);
  dash1.layout.setWidget({ row: 6, col: 0, rowSpan: 6, colSpan: 6 }, wA3);
  dash1.layout.setWidget({ row: 6, col: 6, rowSpan: 6, colSpan: 6 }, wA4);

  const wB1 = mkWidget("Map", "🗺️", "indigo");
  const wB2 = mkWidget("Queue", "📬", "teal");
  const wB3 = mkWidget("Builds", "🧱", "orange");
  const wTabbed = new Widget({
    title: "Dev Console",
    icon: "🧩",
    header: `<div class="hint">Header: slate</div>`,
    content: makeTabbedContent(),
    footer: "",
  });
  wTabbed.addFooterBtn("📎", "Attach", () => { });
  wTabbed.addFooterBtn("🕒", "History", () => { });
  wTabbed.addFooterBtn("📄", "Document", () => { });

  // Dashboard B: Grid layout with different arrangement
  dash2.layout.setWidget({ row: 0, col: 0, rowSpan: 6, colSpan: 4 }, wB1);
  dash2.layout.setWidget({ row: 0, col: 4, rowSpan: 6, colSpan: 4 }, wB2);
  dash2.layout.setWidget({ row: 0, col: 8, rowSpan: 6, colSpan: 4 }, wB3);
  dash2.layout.setWidget({ row: 6, col: 0, rowSpan: 6, colSpan: 12 }, wTabbed);

  // Dashboard C: Dock layout mode (GoldenLayout-style)
  const dash3 = tabs.addDashboard(
    { title: "Dashboard C (Dock)", icon: "🧱", closable: true },
    { layoutMode: "dock", dock: {}, template: { header: section("Dock Mode"), footer: section("Footer C") } }
  );

  const wC1 = mkWidget("Panel 1", "📦", "dock-1");
  const wC2 = mkWidget("Panel 2", "📫", "dock-2");
  const wC3 = mkWidget("Panel 3", "📋", "dock-3");
  const wC4 = mkWidget("Panel 4", "📊", "dock-4");

  dash3.layout.addWidget(wC1);
  dash3.layout.addWidget(wC2);
  dash3.layout.addWidget(wC3);
  dash3.layout.addWidget(wC4);

  tabs.activate(dash1.id);
}

boot(document.getElementById("app"));
