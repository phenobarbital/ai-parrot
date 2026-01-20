// app.js - Dashboard Demo (ES6 vanilla, no build required)
// ============================================================
// Supports THREE layout modes (configurable per dashboard):
//   - 'free': Free-drag with absolute positioning (no constraints)
//   - 'grid': Snap-to-grid with 12x12 cells (structured but flexible)
//   - 'dock': Classic dock mode with split zones (left/right/top/bottom/center)
// ============================================================

// === Utilities ===
const uid = (prefix = 'id') => `${prefix}_${Math.random().toString(36).slice(2, 9)}`;
const clamp = (v, min, max) => Math.min(Math.max(v, min), max);
const cssPx = (v) => typeof v === 'number' ? `${v}px` : v;
const stop = (ev) => { ev.preventDefault(); ev.stopPropagation(); };

function el(tag, attrs = {}, text = '') {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else node.setAttribute(k, v);
  }
  if (text) node.textContent = text;
  return node;
}

function on(target, event, handler, opts) {
  target.addEventListener(event, handler, opts);
  return () => target.removeEventListener(event, handler, opts);
}

const storage = {
  get(key) {
    try {
      const v = localStorage.getItem(key);
      return v ? JSON.parse(v) : null;
    } catch { return null; }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch { }
  },
  remove(key) {
    try { localStorage.removeItem(key); } catch { }
  }
};

// === Event Bus ===
class EventBus {
  constructor() {
    this.listeners = new Map();
  }
  on(event, callback) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event).add(callback);
    return () => this.listeners.get(event)?.delete(callback);
  }
  emit(event, data) {
    this.listeners.get(event)?.forEach(cb => cb(data));
  }
  off(event, callback) {
    if (callback) this.listeners.get(event)?.delete(callback);
    else this.listeners.delete(event);
  }
}

const bus = new EventBus();


// ============================================================
// FREE LAYOUT - Absolute positioning, free drag
// ============================================================

class FreeLayout {
  constructor(dashboard, config = {}) {
    this.dashboard = dashboard;
    this.config = {
      snapToGrid: config.snapToGrid ?? false,
      gridSize: config.gridSize ?? 20,
      padding: config.padding ?? 12
    };
    this.widgets = new Map();
    this.drag = null;

    this.el = el('div', { class: 'free-layout' });
    Object.assign(this.el.style, {
      position: 'relative',
      width: '100%',
      height: '100%',
      overflow: 'hidden'
    });

    this.loadState();
  }

  addWidget(widget, position = {}) {
    const saved = this.getSavedPosition(widget.id);
    const pos = saved || {
      x: position.x ?? this.config.padding,
      y: position.y ?? this.config.padding,
      width: position.width ?? 320,
      height: position.height ?? 240
    };

    // Si no hay posición guardada ni especificada, buscar espacio libre
    if (!saved && position.x === undefined && position.y === undefined) {
      const free = this.findFreePosition(pos.width, pos.height);
      pos.x = free.x;
      pos.y = free.y;
    }

    this.widgets.set(widget.id, { widget, position: pos });
    this.renderWidget(widget, pos);
    widget.setDockedFree(this.dashboard, pos);

    bus.emit('widget:added', { widget, dashboard: this.dashboard, position: pos });
    this.saveState();
  }

  removeWidget(widget) {
    const entry = this.widgets.get(widget.id);
    if (!entry) return;

    widget.el.remove();
    this.widgets.delete(widget.id);
    bus.emit('widget:removed', { widget, dashboard: this.dashboard });
    this.saveState();
  }

  moveWidget(widget, newPosition) {
    const entry = this.widgets.get(widget.id);
    if (!entry) return;

    const pos = this.constrainPosition({ ...entry.position, ...newPosition });
    entry.position = pos;
    this.renderWidget(widget, pos);
    widget.setPositionFree(pos);
    this.saveState();
  }

  resizeWidget(widget, newSize) {
    const entry = this.widgets.get(widget.id);
    if (!entry) return;

    entry.position.width = Math.max(150, newSize.width);
    entry.position.height = Math.max(100, newSize.height);
    this.renderWidget(widget, entry.position);
    widget.setPositionFree(entry.position);
    this.saveState();
  }

  getWidget(widgetId) { return this.widgets.get(widgetId)?.widget; }
  getWidgets() { return Array.from(this.widgets.values()).map(e => e.widget); }
  getPosition(widgetId) { return this.widgets.get(widgetId)?.position; }

  renderWidget(widget, position) {
    if (!widget.el.parentElement) this.el.appendChild(widget.el);
    Object.assign(widget.el.style, {
      position: 'absolute',
      left: cssPx(position.x),
      top: cssPx(position.y),
      width: cssPx(position.width),
      height: cssPx(position.height),
      minWidth: '150px',
      minHeight: '100px'
    });
  }

  constrainPosition(pos) {
    const rect = this.el.getBoundingClientRect();
    const maxX = Math.max(this.config.padding, rect.width - pos.width - this.config.padding);
    const maxY = Math.max(this.config.padding, rect.height - pos.height - this.config.padding);

    let x = clamp(pos.x, this.config.padding, maxX);
    let y = clamp(pos.y, this.config.padding, maxY);

    if (this.config.snapToGrid) {
      x = Math.round(x / this.config.gridSize) * this.config.gridSize;
      y = Math.round(y / this.config.gridSize) * this.config.gridSize;
    }

    return { ...pos, x, y };
  }

  // === Drag ===
  beginDrag(widget, ev) {
    const entry = this.widgets.get(widget.id);
    if (!entry) return;

    const rect = widget.el.getBoundingClientRect();
    const containerRect = this.el.getBoundingClientRect();
    const offsetX = ev.clientX - rect.left;
    const offsetY = ev.clientY - rect.top;

    widget.el.style.zIndex = '100';
    widget.el.classList.add('is-dragging');

    const onMove = (e) => {
      const x = e.clientX - containerRect.left - offsetX;
      const y = e.clientY - containerRect.top - offsetY;
      const newPos = this.constrainPosition({ ...entry.position, x, y });
      widget.el.style.left = cssPx(newPos.x);
      widget.el.style.top = cssPx(newPos.y);
      entry.position.x = newPos.x;
      entry.position.y = newPos.y;
    };

    const onUp = () => {
      window.removeEventListener('pointermove', onMove, true);
      window.removeEventListener('pointerup', onUp, true);
      widget.el.classList.remove('is-dragging');
      widget.el.style.zIndex = '';
      widget.setPositionFree(entry.position);
      this.saveState();
    };

    window.addEventListener('pointermove', onMove, true);
    window.addEventListener('pointerup', onUp, true);
  }

  beginResize(widget, ev) {
    const entry = this.widgets.get(widget.id);
    if (!entry) return;
    stop(ev);

    const startX = ev.clientX, startY = ev.clientY;
    const startW = entry.position.width, startH = entry.position.height;

    const onMove = (e) => {
      let newW = startW + (e.clientX - startX);
      let newH = startH + (e.clientY - startY);

      if (this.config.snapToGrid) {
        newW = Math.round(newW / this.config.gridSize) * this.config.gridSize;
        newH = Math.round(newH / this.config.gridSize) * this.config.gridSize;
      }

      entry.position.width = Math.max(150, newW);
      entry.position.height = Math.max(100, newH);
      widget.el.style.width = cssPx(entry.position.width);
      widget.el.style.height = cssPx(entry.position.height);
    };

    const onUp = () => {
      window.removeEventListener('pointermove', onMove, true);
      window.removeEventListener('pointerup', onUp, true);
      widget.setPositionFree(entry.position);
      this.saveState();
    };

    window.addEventListener('pointermove', onMove, true);
    window.addEventListener('pointerup', onUp, true);
  }

  // === Space Finding ===
  findFreePosition(width, height) {
    const rect = this.el.getBoundingClientRect();
    const step = this.config.snapToGrid ? this.config.gridSize : 30;
    const pad = this.config.padding;

    for (let y = pad; y < rect.height - height - pad; y += step) {
      for (let x = pad; x < rect.width - width - pad; x += step) {
        if (!this.hasOverlap({ x, y, width, height })) return { x, y };
      }
    }

    // Fallback: cascade
    const count = this.widgets.size;
    return {
      x: pad + (count * 40) % Math.max(1, rect.width - width - pad * 2),
      y: pad + (count * 40) % Math.max(1, rect.height - height - pad * 2)
    };
  }

  findFreeSpace(width, height) {
    const pos = this.findFreePosition(width ?? 320, height ?? 240);
    return { x: pos.x, y: pos.y, width: width ?? 320, height: height ?? 240 };
  }

  hasOverlap(rect, excludeId) {
    for (const [id, entry] of this.widgets) {
      if (id === excludeId) continue;
      const p = entry.position;
      if (!(rect.x >= p.x + p.width || rect.x + rect.width <= p.x ||
        rect.y >= p.y + p.height || rect.y + rect.height <= p.y)) {
        return true;
      }
    }
    return false;
  }

  // === Persistence ===
  storageKey() { return `free-layout:${this.dashboard.id}`; }

  saveState() {
    const positions = {};
    for (const [id, entry] of this.widgets) positions[id] = entry.position;
    storage.set(this.storageKey(), { positions });
  }

  loadState() {
    const state = storage.get(this.storageKey());
    if (state?.positions) this.savedPositions = state.positions;
  }

  getSavedPosition(widgetId) { return this.savedPositions?.[widgetId] ?? null; }

  reset() {
    storage.remove(this.storageKey());
    const pad = this.config.padding;
    let x = pad, y = pad;
    const rect = this.el.getBoundingClientRect();

    for (const entry of this.widgets.values()) {
      entry.position = { x, y, width: 320, height: 240 };
      this.renderWidget(entry.widget, entry.position);
      x += 340;
      if (x + 320 > rect.width - pad) { x = pad; y += 260; }
    }
    this.saveState();
  }

  destroy() { this.saveState(); }
}


// ============================================================
// DOCK LAYOUT - Classic split-based docking system
// ============================================================

class DockLayout {
  constructor(dashboard, config = {}) {
    this.dashboard = dashboard;
    this.config = {
      minPanelSize: config.minPanelSize ?? 100,
      gutterSize: config.gutterSize ?? 6,
    };

    this.widgets = new Map();
    this.root = null;
    this.drag = null;

    this.el = el('div', { class: 'dock-layout' });
    Object.assign(this.el.style, {
      display: 'flex',
      height: '100%',
      position: 'relative',
      overflow: 'hidden'
    });
  }

  // === Public API ===

  addWidget(widget, dockPosition = 'center') {
    this.widgets.set(widget.id, widget);

    if (!this.root) {
      this.root = this.createLeaf(widget);
      this.el.appendChild(this.root.el);
    } else {
      this.dockWidget(widget, this.root, dockPosition);
    }

    widget.setDocked(this.dashboard, { dockPosition });
    bus.emit('widget:added', { widget, dashboard: this.dashboard, placement: { dockPosition } });
  }

  removeWidget(widget) {
    if (!this.widgets.has(widget.id)) return;

    const leaf = this.findLeaf(this.root, widget.id);
    if (leaf) this.removeLeaf(leaf);

    this.widgets.delete(widget.id);
    widget.el.remove();
    bus.emit('widget:removed', { widget, dashboard: this.dashboard });
  }

  getWidget(widgetId) { return this.widgets.get(widgetId); }
  getWidgets() { return Array.from(this.widgets.values()); }
  getPlacement(widgetId) { return this.findLeaf(this.root, widgetId) ? { dockPosition: 'docked' } : null; }
  findFreeSpace() { return { dockPosition: 'center' }; }

  // === Dock Tree ===

  createLeaf(widget) {
    const leaf = {
      type: 'leaf',
      widgetId: widget.id,
      el: el('div', { class: 'dock-leaf', 'data-widget-id': widget.id }),
      parent: null
    };

    Object.assign(leaf.el.style, {
      flex: '1',
      display: 'flex',
      flexDirection: 'column',
      minWidth: `${this.config.minPanelSize}px`,
      minHeight: `${this.config.minPanelSize}px`,
      position: 'relative',
      overflow: 'hidden'
    });

    leaf.el.appendChild(widget.el);
    this.setupDropZones(leaf);
    return leaf;
  }

  createSplit(direction, children, sizes = null) {
    const split = {
      type: 'split',
      direction,
      children,
      sizes: sizes || children.map(() => 100 / children.length),
      el: el('div', { class: `dock-split dock-split-${direction}` }),
      parent: null
    };

    Object.assign(split.el.style, {
      display: 'flex',
      flexDirection: direction === 'horizontal' ? 'row' : 'column',
      flex: '1',
      minWidth: '0',
      minHeight: '0'
    });

    children.forEach((child, i) => {
      child.parent = split;
      child.el.style.flex = `0 0 ${split.sizes[i]}%`;
      split.el.appendChild(child.el);

      if (i < children.length - 1) {
        const gutter = this.createGutter(split, i, direction === 'horizontal');
        split.el.appendChild(gutter);
      }
    });

    return split;
  }

  createGutter(split, index, isHorizontal) {
    const gutter = el('div', { class: 'dock-gutter' });
    Object.assign(gutter.style, {
      flex: `0 0 ${this.config.gutterSize}px`,
      background: 'var(--border)',
      cursor: isHorizontal ? 'col-resize' : 'row-resize',
      transition: 'background 150ms'
    });

    on(gutter, 'mouseenter', () => gutter.style.background = 'var(--accent)');
    on(gutter, 'mouseleave', () => gutter.style.background = 'var(--border)');
    on(gutter, 'pointerdown', (ev) => {
      stop(ev);
      this.beginGutterResize(split, index, isHorizontal, ev);
    });

    return gutter;
  }

  beginGutterResize(split, index, isHorizontal, ev) {
    const startPos = isHorizontal ? ev.clientX : ev.clientY;
    const rect = split.el.getBoundingClientRect();
    const totalSize = isHorizontal ? rect.width : rect.height;
    const gutterTotal = (split.children.length - 1) * this.config.gutterSize;
    const availableSize = totalSize - gutterTotal;
    const startSizes = [...split.sizes];

    const onMove = (e) => {
      const currentPos = isHorizontal ? e.clientX : e.clientY;
      const delta = currentPos - startPos;
      const deltaPercent = (delta / availableSize) * 100;
      const minPercent = (this.config.minPanelSize / availableSize) * 100;

      let newSize1 = startSizes[index] + deltaPercent;
      let newSize2 = startSizes[index + 1] - deltaPercent;

      if (newSize1 < minPercent) { newSize1 = minPercent; newSize2 = startSizes[index] + startSizes[index + 1] - minPercent; }
      if (newSize2 < minPercent) { newSize2 = minPercent; newSize1 = startSizes[index] + startSizes[index + 1] - minPercent; }

      split.sizes[index] = newSize1;
      split.sizes[index + 1] = newSize2;
      split.children[index].el.style.flex = `0 0 ${newSize1}%`;
      split.children[index + 1].el.style.flex = `0 0 ${newSize2}%`;
    };

    const onUp = () => {
      window.removeEventListener('pointermove', onMove, true);
      window.removeEventListener('pointerup', onUp, true);
    };

    window.addEventListener('pointermove', onMove, true);
    window.addEventListener('pointerup', onUp, true);
  }

  dockWidget(widget, targetNode, position) {
    const newLeaf = this.createLeaf(widget);
    if (targetNode.type === 'leaf') {
      this.splitLeaf(targetNode, newLeaf, position);
    } else {
      this.dockToSplit(targetNode, newLeaf, position);
    }
  }

  splitLeaf(leaf, newLeaf, position) {
    const parent = leaf.parent;
    const direction = (position === 'left' || position === 'right') ? 'horizontal' : 'vertical';
    const insertBefore = (position === 'left' || position === 'top');
    const children = insertBefore ? [newLeaf, leaf] : [leaf, newLeaf];
    const split = this.createSplit(direction, children);

    if (parent) {
      const index = parent.children.indexOf(leaf);
      parent.children[index] = split;
      split.parent = parent;
      leaf.el.replaceWith(split.el);
    } else {
      this.root = split;
      this.el.innerHTML = '';
      this.el.appendChild(split.el);
    }
  }

  dockToSplit(split, newLeaf, position) {
    const direction = (position === 'left' || position === 'right') ? 'horizontal' : 'vertical';
    const insertBefore = (position === 'left' || position === 'top');

    if (split.direction === direction) {
      newLeaf.parent = split;
      const newSize = 100 / (split.children.length + 1);
      split.sizes = split.sizes.map(s => s * (1 - newSize / 100));

      if (insertBefore) {
        split.sizes.unshift(newSize);
        split.children.unshift(newLeaf);
        split.el.prepend(newLeaf.el);
        const gutter = this.createGutter(split, 0, direction === 'horizontal');
        newLeaf.el.after(gutter);
      } else {
        split.sizes.push(newSize);
        split.children.push(newLeaf);
        const gutter = this.createGutter(split, split.children.length - 2, direction === 'horizontal');
        split.el.appendChild(gutter);
        split.el.appendChild(newLeaf.el);
      }

      split.children.forEach((child, i) => { child.el.style.flex = `0 0 ${split.sizes[i]}%`; });
    } else {
      const parent = split.parent;
      const children = insertBefore ? [newLeaf, split] : [split, newLeaf];
      const newSplit = this.createSplit(direction, children);

      if (parent) {
        const index = parent.children.indexOf(split);
        parent.children[index] = newSplit;
        newSplit.parent = parent;
        split.el.replaceWith(newSplit.el);
      } else {
        this.root = newSplit;
        this.el.innerHTML = '';
        this.el.appendChild(newSplit.el);
      }
    }
  }

  findLeaf(node, widgetId) {
    if (!node) return null;
    if (node.type === 'leaf') return node.widgetId === widgetId ? node : null;
    for (const child of node.children) {
      const found = this.findLeaf(child, widgetId);
      if (found) return found;
    }
    return null;
  }

  removeLeaf(leaf) {
    const parent = leaf.parent;
    if (!parent) { this.root = null; this.el.innerHTML = ''; return; }

    const index = parent.children.indexOf(leaf);
    parent.children.splice(index, 1);
    parent.sizes.splice(index, 1);
    leaf.el.remove();

    const gutters = parent.el.querySelectorAll('.dock-gutter');
    if (gutters[index]) gutters[index].remove();
    else if (gutters[index - 1]) gutters[index - 1].remove();

    const total = parent.sizes.reduce((a, b) => a + b, 0);
    parent.sizes = parent.sizes.map(s => (s / total) * 100);
    parent.children.forEach((child, i) => { child.el.style.flex = `0 0 ${parent.sizes[i]}%`; });

    if (parent.children.length === 1) {
      const remaining = parent.children[0];
      const grandparent = parent.parent;

      if (grandparent) {
        const parentIndex = grandparent.children.indexOf(parent);
        grandparent.children[parentIndex] = remaining;
        remaining.parent = grandparent;
        parent.el.replaceWith(remaining.el);
        remaining.el.style.flex = `0 0 ${grandparent.sizes[parentIndex]}%`;
      } else {
        this.root = remaining;
        remaining.parent = null;
        this.el.innerHTML = '';
        this.el.appendChild(remaining.el);
        remaining.el.style.flex = '1';
      }
    }
  }

  // === Drop Zones ===
  setupDropZones(leaf) {
    ['top', 'right', 'bottom', 'left', 'center'].forEach(zone => {
      const dropZone = el('div', { class: `dock-drop-zone dock-drop-${zone}`, 'data-zone': zone });
      leaf.el.appendChild(dropZone);
    });
  }

  showDropZones(excludeWidgetId) {
    this.el.querySelectorAll('.dock-leaf').forEach(leaf => {
      if (leaf.dataset.widgetId !== excludeWidgetId) leaf.classList.add('dock-drop-active');
    });
  }

  hideDropZones() {
    this.el.querySelectorAll('.dock-leaf').forEach(leaf => {
      leaf.classList.remove('dock-drop-active', 'dock-drop-hover');
    });
    this.el.querySelectorAll('.dock-drop-zone').forEach(zone => {
      zone.classList.remove('dock-zone-hover');
    });
  }

  // === Drag ===
  beginDrag(widget, ev) {
    if (!this.widgets.has(widget.id)) return;

    const rect = widget.el.getBoundingClientRect();
    const ghost = el('div', { class: 'widget-drag-ghost' });
    Object.assign(ghost.style, {
      position: 'fixed', width: cssPx(rect.width), height: cssPx(rect.height),
      left: cssPx(rect.left), top: cssPx(rect.top),
      pointerEvents: 'none', zIndex: '10000', opacity: '0.8',
      borderRadius: '12px', background: 'rgba(59, 130, 246, 0.1)',
      border: '2px solid rgba(59, 130, 246, 0.5)', backdropFilter: 'blur(4px)'
    });
    document.body.appendChild(ghost);

    this.drag = { widget, ghost, offsetX: ev.clientX - rect.left, offsetY: ev.clientY - rect.top };
    widget.el.classList.add('is-dragging');
    this.showDropZones(widget.id);

    const onMove = (e) => this.handleDragMove(e);
    const onUp = (e) => {
      window.removeEventListener('pointermove', onMove, true);
      window.removeEventListener('pointerup', onUp, true);
      this.handleDragEnd(e);
    };

    window.addEventListener('pointermove', onMove, true);
    window.addEventListener('pointerup', onUp, true);
  }

  handleDragMove(ev) {
    if (!this.drag) return;
    const { ghost, offsetX, offsetY, widget } = this.drag;

    ghost.style.left = cssPx(ev.clientX - offsetX);
    ghost.style.top = cssPx(ev.clientY - offsetY);

    const target = document.elementFromPoint(ev.clientX, ev.clientY);
    this.el.querySelectorAll('.dock-zone-hover').forEach(z => z.classList.remove('dock-zone-hover'));
    this.el.querySelectorAll('.dock-drop-hover').forEach(l => l.classList.remove('dock-drop-hover'));

    if (target) {
      const zone = target.closest('.dock-drop-zone');
      const leaf = target.closest('.dock-leaf');

      if (zone && leaf && leaf.dataset.widgetId !== widget.id) {
        zone.classList.add('dock-zone-hover');
        leaf.classList.add('dock-drop-hover');
        this.drag.targetLeaf = leaf;
        this.drag.targetZone = zone.dataset.zone;
      } else {
        this.drag.targetLeaf = null;
        this.drag.targetZone = null;
      }
    }
  }

  handleDragEnd(ev) {
    if (!this.drag) return;
    const { widget, ghost, targetLeaf, targetZone } = this.drag;

    widget.el.classList.remove('is-dragging');
    ghost.remove();
    this.hideDropZones();

    if (targetLeaf && targetZone && targetZone !== 'center') {
      const targetWidgetId = targetLeaf.dataset.widgetId;
      const leaf = this.findLeaf(this.root, widget.id);
      if (leaf) this.removeLeaf(leaf);

      const targetLeafNode = this.findLeaf(this.root, targetWidgetId);
      if (targetLeafNode) {
        const newLeaf = this.createLeaf(widget);
        this.splitLeaf(targetLeafNode, newLeaf, targetZone);
      }
    } else if (targetZone === 'center' && targetLeaf) {
      // Swap
      const targetWidgetId = targetLeaf.dataset.widgetId;
      const targetWidget = this.widgets.get(targetWidgetId);
      const sourceLeaf = this.findLeaf(this.root, widget.id);
      const destLeaf = this.findLeaf(this.root, targetWidgetId);

      if (sourceLeaf && destLeaf && targetWidget) {
        sourceLeaf.widgetId = targetWidgetId;
        destLeaf.widgetId = widget.id;
        sourceLeaf.el.dataset.widgetId = targetWidgetId;
        destLeaf.el.dataset.widgetId = widget.id;

        const tempHolder = el('div');
        sourceLeaf.el.insertBefore(tempHolder, sourceLeaf.el.firstChild);
        destLeaf.el.insertBefore(widget.el, destLeaf.el.firstChild);
        tempHolder.replaceWith(targetWidget.el);
      }
    }

    this.drag = null;
  }

  beginResize(widget, ev) { /* Dock mode uses gutters */ }
  reset() {
    const widgets = this.getWidgets();
    this.root = null;
    this.el.innerHTML = '';
    widgets.forEach((w, i) => {
      this.addWidget(w, i === 0 ? 'center' : ['right', 'bottom', 'left'][i % 3]);
    });
  }
  destroy() { }
}


// ============================================================
// GRID LAYOUT - Free-drag with snap-to-grid
// ============================================================

class GridLayout {
  constructor(dashboard, config = {}) {
    this.dashboard = dashboard;
    this.config = { cols: config.cols ?? 12, rows: config.rows ?? 12, gap: config.gap ?? 8, minCellSpan: config.minCellSpan ?? 2 };
    this.widgets = new Map();
    this.drag = null;
    this.dropPreview = null;
    this.activeDropZone = null;

    this.el = el('div', { class: 'grid-layout' });
    this.applyGridStyles();
  }

  applyGridStyles() {
    const { cols, rows, gap } = this.config;
    Object.assign(this.el.style, {
      display: 'grid', gridTemplateColumns: `repeat(${cols}, 1fr)`, gridTemplateRows: `repeat(${rows}, 1fr)`,
      gap: `${gap}px`, height: '100%', position: 'relative', padding: `${gap}px`
    });
  }

  addWidget(widget, placement) {
    const normalized = this.normalizePlacement(placement);
    const final = this.resolveCollisions(widget.id, normalized);
    this.widgets.set(widget.id, { widget, placement: final });
    this.renderWidget(widget, final);
    widget.setDocked(this.dashboard, final);
    bus.emit('widget:added', { widget, dashboard: this.dashboard, placement: final });
  }

  removeWidget(widget) {
    if (!this.widgets.get(widget.id)) return;
    widget.el.remove();
    this.widgets.delete(widget.id);
    bus.emit('widget:removed', { widget, dashboard: this.dashboard });
  }

  moveWidget(widget, newPlacement) {
    const entry = this.widgets.get(widget.id);
    if (!entry) return;
    const normalized = this.normalizePlacement(newPlacement);
    entry.placement = normalized;
    this.renderWidget(widget, normalized);
    widget.setPlacement(normalized);
  }

  swapWidgets(widgetA, widgetB) {
    const entryA = this.widgets.get(widgetA.id), entryB = this.widgets.get(widgetB.id);
    if (!entryA || !entryB) return;
    const pA = { ...entryA.placement }, pB = { ...entryB.placement };
    entryA.placement = pB; entryB.placement = pA;
    this.renderWidget(widgetA, pB); this.renderWidget(widgetB, pA);
    widgetA.setPlacement(pB); widgetB.setPlacement(pA);
  }

  getWidget(widgetId) { return this.widgets.get(widgetId)?.widget; }
  getWidgets() { return Array.from(this.widgets.values()).map(e => e.widget); }
  getPlacement(widgetId) { return this.widgets.get(widgetId)?.placement; }

  renderWidget(widget, placement) {
    const { row, col, rowSpan, colSpan } = placement;
    if (!widget.el.parentElement) this.el.appendChild(widget.el);
    Object.assign(widget.el.style, {
      gridColumn: `${col + 1} / span ${colSpan}`, gridRow: `${row + 1} / span ${rowSpan}`,
      position: 'relative', minWidth: '0', minHeight: '0'
    });
  }

  beginDrag(widget, ev) {
    const entry = this.widgets.get(widget.id);
    if (!entry) return;
    const rect = widget.el.getBoundingClientRect();

    const ghost = el('div', { class: 'widget-drag-ghost' });
    Object.assign(ghost.style, {
      position: 'fixed', width: cssPx(rect.width), height: cssPx(rect.height),
      left: cssPx(rect.left), top: cssPx(rect.top), pointerEvents: 'none', zIndex: '10000',
      opacity: '0.8', borderRadius: '12px', background: 'rgba(59, 130, 246, 0.1)',
      border: '2px solid rgba(59, 130, 246, 0.5)', backdropFilter: 'blur(4px)'
    });
    document.body.appendChild(ghost);

    this.drag = { widget, startX: ev.clientX, startY: ev.clientY, offsetX: ev.clientX - rect.left, offsetY: ev.clientY - rect.top, originalPlacement: { ...entry.placement }, ghost };
    widget.el.classList.add('is-dragging');
    this.createDropPreview();

    const onMove = (e) => this.handleDragMove(e);
    const onUp = (e) => { window.removeEventListener('pointermove', onMove, true); window.removeEventListener('pointerup', onUp, true); this.handleDragEnd(e); };
    window.addEventListener('pointermove', onMove, true);
    window.addEventListener('pointerup', onUp, true);
  }

  handleDragMove(ev) {
    if (!this.drag) return;
    const { ghost, originalPlacement, widget, offsetX, offsetY } = this.drag;
    const ghostLeft = ev.clientX - offsetX;
    const ghostTop = ev.clientY - offsetY;

    ghost.style.left = cssPx(ghostLeft);
    ghost.style.top = cssPx(ghostTop);

    const cell = this.cellFromPoint(ghostLeft, ghostTop);
    if (!cell) { this.hideDropPreview(); this.activeDropZone = null; return; }
    const dropZone = this.computeDropZone(cell, originalPlacement);
    this.activeDropZone = dropZone;
    this.updateDropPreview(dropZone);
  }

  handleDragEnd(ev) {
    if (!this.drag) return;
    const { widget, ghost } = this.drag;
    widget.el.classList.remove('is-dragging');
    ghost.remove();
    this.hideDropPreview();

    if (this.activeDropZone?.isValid) {
      const { zone, targetWidget, previewPlacement } = this.activeDropZone;
      if (zone === 'swap' && targetWidget) {
        const target = this.widgets.get(targetWidget)?.widget;
        if (target) this.swapWidgets(widget, target);
      } else {
        this.moveWidget(widget, previewPlacement);
      }
    }
    this.drag = null; this.activeDropZone = null;
  }

  cellFromPoint(x, y) {
    const rect = this.el.getBoundingClientRect();
    if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) return null;
    const { cols, rows, gap } = this.config;
    const cellW = (rect.width - gap * 2) / cols, cellH = (rect.height - gap * 2) / rows;
    return { col: clamp(Math.floor((x - rect.left - gap) / cellW), 0, cols - 1), row: clamp(Math.floor((y - rect.top - gap) / cellH), 0, rows - 1) };
  }

  computeDropZone(cell, originalPlacement) {
    const { row, col } = cell;
    const { cols, rows } = this.config;
    const { rowSpan, colSpan } = originalPlacement;

    const targetEntry = this.findWidgetAtCell(row, col);
    if (targetEntry && targetEntry.widget.id !== this.drag?.widget.id) {
      return { zone: 'swap', targetWidget: targetEntry.widget.id, previewPlacement: targetEntry.placement, isValid: true };
    }

    const previewPlacement = { row: clamp(row, 0, rows - rowSpan), col: clamp(col, 0, cols - colSpan), rowSpan, colSpan };
    return { zone: 'center', previewPlacement, isValid: this.canPlace(previewPlacement, this.drag?.widget.id) };
  }

  findWidgetAtCell(row, col) {
    for (const entry of this.widgets.values()) {
      const p = entry.placement;
      if (row >= p.row && row < p.row + p.rowSpan && col >= p.col && col < p.col + p.colSpan) return entry;
    }
    return null;
  }

  canPlace(placement, excludeId) {
    for (const [id, entry] of this.widgets) {
      if (id === excludeId) continue;
      if (this.placementsOverlap(placement, entry.placement)) return false;
    }
    return true;
  }

  placementsOverlap(a, b) {
    return !(a.col >= b.col + b.colSpan || a.col + a.colSpan <= b.col || a.row >= b.row + b.rowSpan || a.row + a.rowSpan <= b.row);
  }

  createDropPreview() {
    if (this.dropPreview) return;
    this.dropPreview = el('div', { class: 'grid-drop-preview' });
    Object.assign(this.dropPreview.style, { position: 'absolute', pointerEvents: 'none', zIndex: '100', display: 'none', borderRadius: '12px', transition: 'all 0.15s ease' });
    this.el.appendChild(this.dropPreview);
  }

  updateDropPreview(zone) {
    if (!this.dropPreview) return;
    const { previewPlacement, isValid, zone: zoneType } = zone;
    const { row, col, rowSpan, colSpan } = previewPlacement;
    Object.assign(this.dropPreview.style, {
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      gridColumn: `${col + 1} / span ${colSpan}`, gridRow: `${row + 1} / span ${rowSpan}`,
      background: isValid ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)',
      border: `2px dashed ${isValid ? '#22c55e' : '#ef4444'}`
    });
    this.dropPreview.textContent = zoneType === 'swap' ? '⇄ Swap' : isValid ? '✓ Drop' : '✗ No space';
    this.dropPreview.style.color = isValid ? '#22c55e' : '#ef4444';
    this.dropPreview.style.fontWeight = '600';
  }

  hideDropPreview() { if (this.dropPreview) this.dropPreview.style.display = 'none'; }

  beginResize(widget, ev) {
    const entry = this.widgets.get(widget.id);
    if (!entry) return;
    stop(ev);
    const startX = ev.clientX, startY = ev.clientY, startPlacement = { ...entry.placement };
    const gridRect = this.el.getBoundingClientRect();
    const { cols, rows, gap, minCellSpan } = this.config;
    const cellW = (gridRect.width - gap * 2) / cols, cellH = (gridRect.height - gap * 2) / rows;

    const onMove = (e) => {
      const dCols = Math.round((e.clientX - startX) / cellW), dRows = Math.round((e.clientY - startY) / cellH);
      const newColSpan = clamp(startPlacement.colSpan + dCols, minCellSpan, cols - startPlacement.col);
      const newRowSpan = clamp(startPlacement.rowSpan + dRows, minCellSpan, rows - startPlacement.row);
      const newPlacement = { ...startPlacement, colSpan: newColSpan, rowSpan: newRowSpan };
      if (this.canPlace(newPlacement, widget.id)) { entry.placement = newPlacement; this.renderWidget(widget, newPlacement); }
    };
    const onUp = () => { window.removeEventListener('pointermove', onMove, true); window.removeEventListener('pointerup', onUp, true); widget.setPlacement(entry.placement); };
    window.addEventListener('pointermove', onMove, true);
    window.addEventListener('pointerup', onUp, true);
  }

  findFreeSpace(colSpan, rowSpan) {
    const { cols, rows } = this.config;
    for (let r = 0; r <= rows - rowSpan; r++) {
      for (let c = 0; c <= cols - colSpan; c++) {
        const p = { row: r, col: c, rowSpan, colSpan };
        if (this.canPlace(p)) return p;
      }
    }
    return null;
  }

  normalizePlacement(p) {
    const { cols, rows, minCellSpan } = this.config;
    return { row: clamp(p.row, 0, rows - 1), col: clamp(p.col, 0, cols - 1), rowSpan: clamp(p.rowSpan, minCellSpan, rows), colSpan: clamp(p.colSpan, minCellSpan, cols) };
  }

  resolveCollisions(widgetId, placement) {
    if (this.canPlace(placement, widgetId)) return placement;
    const free = this.findFreeSpace(placement.colSpan, placement.rowSpan);
    if (free) return free;
    const minP = { ...placement, rowSpan: this.config.minCellSpan, colSpan: this.config.minCellSpan };
    return this.findFreeSpace(minP.colSpan, minP.rowSpan) ?? { row: 0, col: 0, rowSpan: 2, colSpan: 2 };
  }

  reset() {
    let col = 0, row = 0;
    for (const entry of this.widgets.values()) {
      entry.placement = { row, col, rowSpan: 4, colSpan: 4 };
      this.renderWidget(entry.widget, entry.placement);
      col += 4;
      if (col >= this.config.cols) { col = 0; row += 4; }
    }
  }

  destroy() { this.dropPreview?.remove(); }
}


// ============================================================
// WIDGET
// ============================================================

class Widget {
  constructor(opts) {
    this.opts = opts;
    this.id = opts.id ?? uid('widget');
    this.dashboard = null;
    this.placement = null;
    this.mode = 'docked';
    this.minimized = false;
    this.lastDocked = null;
    this.floatingStyles = null;
    this.disposers = [];

    this.el = el('article', { class: 'widget', 'data-widget-id': this.id });
    this.titleBar = el('header', { class: 'widget-titlebar' });
    const iconEl = el('span', { class: 'widget-icon' }, opts.icon ?? '▣');
    this.titleText = el('span', { class: 'widget-title' }, opts.title);
    this.burgerBtn = el('button', { class: 'widget-burger', type: 'button', title: 'Menu' }, '☰');
    this.toolbar = el('div', { class: 'widget-toolbar' });

    const titleGroup = el('div', { class: 'widget-title-group' });
    titleGroup.append(iconEl, this.titleText);
    const actionsGroup = el('div', { class: 'widget-actions' });
    actionsGroup.append(this.toolbar, this.burgerBtn);
    this.titleBar.append(titleGroup, actionsGroup);

    this.headerSection = el('div', { class: 'widget-header' });
    this.contentSection = el('div', { class: 'widget-content' });
    this.footerSection = el('div', { class: 'widget-footer' });
    this.setSection(this.headerSection, opts.header);
    this.setSection(this.contentSection, opts.content);
    this.setSection(this.footerSection, opts.footer);

    this.resizeHandle = el('div', { class: 'widget-resize-handle', title: 'Resize' });
    this.el.append(this.titleBar, this.headerSection, this.contentSection, this.footerSection, this.resizeHandle);
    this.buildToolbar();
    this.setupInteractions();
  }

  getTitle() { return this.titleText.textContent ?? this.opts.title; }
  getIcon() { return this.opts.icon ?? '▣'; }
  getDashboard() { return this.dashboard; }
  getPlacement() { return this.placement; }
  isFloating() { return this.mode === 'floating'; }
  isMaximized() { return this.mode === 'maximized'; }
  isDocked() { return this.mode === 'docked'; }
  isMinimized() { return this.minimized; }

  setDocked(dashboard, placement) {
    this.dashboard = dashboard;
    this.placement = placement ? { ...placement } : null;
    this.mode = 'docked';
    this.lastDocked = { dashboard, placement: placement ? { ...placement } : null };
    this.el.classList.remove('is-floating', 'is-maximized');
    Object.assign(this.el.style, { position: '', left: '', top: '', width: '', height: '', zIndex: '' });
  }

  setPlacement(placement) {
    this.placement = placement ? { ...placement } : null;
    if (this.lastDocked && placement) this.lastDocked.placement = { ...placement };
  }

  // For FreeLayout
  setDockedFree(dashboard, position) {
    this.dashboard = dashboard;
    this.placement = position ? { ...position } : null;
    this.mode = 'docked';
    this.lastDocked = { dashboard, placement: position ? { ...position } : null };
    this.el.classList.remove('is-floating', 'is-maximized');
  }

  setPositionFree(position) {
    this.placement = position ? { ...position } : null;
    if (this.lastDocked && position) this.lastDocked.placement = { ...position };
  }

  setSection(section, content) {
    section.innerHTML = '';
    if (!content) { section.style.display = 'none'; return; }
    section.style.display = '';
    if (typeof content === 'string') section.innerHTML = content;
    else section.appendChild(content);
  }

  setContent(content) { this.setSection(this.contentSection, content); }

  toggleMinimize() {
    this.minimized = !this.minimized;
    this.el.classList.toggle('is-minimized', this.minimized);
    bus.emit('widget:minimized', { widget: this });
  }

  float() {
    if (this.isFloating()) return;
    if (this.isMaximized()) this.restore();
    if (this.dashboard && this.placement) this.lastDocked = { dashboard: this.dashboard, placement: { ...this.placement } };
    const rect = this.el.getBoundingClientRect();
    document.body.appendChild(this.el);
    this.mode = 'floating';
    this.el.classList.add('is-floating');
    this.el.classList.remove('is-maximized');
    Object.assign(this.el.style, { position: 'fixed', left: cssPx(rect.left), top: cssPx(rect.top), width: cssPx(Math.max(280, rect.width)), height: cssPx(Math.max(200, rect.height)), zIndex: '9999' });
    this.floatingStyles = { left: this.el.style.left, top: this.el.style.top, width: this.el.style.width, height: this.el.style.height };
    bus.emit('widget:floated', { widget: this });
    this.renderToolbar();
  }

  dock() {
    if (!this.isFloating()) return;
    let targetDash = this.lastDocked?.dashboard ?? this.dashboard;
    let targetPlacement = this.lastDocked?.placement ?? this.placement;
    if (!targetDash) { const c = window.__dashboardContainer; if (c) targetDash = c.getActiveDashboard(); }
    if (!targetDash) { console.warn('No dashboard to dock'); return; }
    if (!targetPlacement) targetPlacement = targetDash.layout.findFreeSpace?.(4, 4) ?? { row: 0, col: 0, rowSpan: 4, colSpan: 4 };
    this.el.remove();
    this.el.classList.remove('is-floating', 'is-maximized');
    Object.assign(this.el.style, { position: '', left: '', top: '', width: '', height: '', zIndex: '' });
    this.mode = 'docked';
    targetDash.layout.addWidget(this, targetPlacement);
    bus.emit('widget:docked', { widget: this, dashboard: targetDash, placement: targetPlacement });
    this.renderToolbar();
  }

  toggleFloating() { if (this.isFloating()) this.dock(); else this.float(); }

  maximize() {
    if (this.isMaximized()) return;
    if (this.isFloating()) this.floatingStyles = { left: this.el.style.left, top: this.el.style.top, width: this.el.style.width, height: this.el.style.height };
    else if (this.dashboard && this.placement) this.lastDocked = { dashboard: this.dashboard, placement: { ...this.placement } };
    if (!this.el.parentElement || this.el.parentElement !== document.body) document.body.appendChild(this.el);
    this.mode = 'maximized';
    this.el.classList.add('is-maximized');
    this.el.classList.remove('is-floating');
    Object.assign(this.el.style, { position: 'fixed', left: '0', top: '0', width: '100vw', height: '100vh', zIndex: '10000' });
    bus.emit('widget:maximized', { widget: this });
    this.renderToolbar();
  }

  restore() {
    if (!this.isMaximized()) return;
    this.el.classList.remove('is-maximized');
    if (this.floatingStyles) { this.mode = 'floating'; this.el.classList.add('is-floating'); Object.assign(this.el.style, this.floatingStyles); this.el.style.zIndex = '9999'; }
    else if (this.lastDocked) { this.dock(); return; }
    else { this.mode = 'floating'; this.el.classList.add('is-floating'); Object.assign(this.el.style, { position: 'fixed', left: '50%', top: '50%', transform: 'translate(-50%, -50%)', width: '400px', height: '300px', zIndex: '9999' }); }
    bus.emit('widget:restored', { widget: this });
    this.renderToolbar();
  }

  async refresh() {
    if (!this.opts.onRefresh) return;
    this.el.classList.add('is-refreshing');
    try { await this.opts.onRefresh(this); } finally { this.el.classList.remove('is-refreshing'); }
  }

  close() {
    this.opts.onClose?.(this);
    if (this.dashboard) this.dashboard.layout.removeWidget(this);
    this.destroy();
    this.el.remove();
  }

  openInNewWindow() {
    const win = window.open('', '_blank', 'width=720,height=480');
    if (!win) return;
    const styles = Array.from(document.styleSheets).map(s => { try { return Array.from(s.cssRules ?? []).map(r => r.cssText).join('\n'); } catch { return ''; } }).join('\n');
    win.document.write(`<!DOCTYPE html><html><head><title>${this.getTitle()}</title><style>${styles}</style></head><body class="widget-popup-body">${this.el.outerHTML}</body></html>`);
    win.document.close();
  }

  buildToolbar() { this.renderToolbar(); }

  renderToolbar() {
    const buttons = [
      { id: 'minimize', title: this.minimized ? 'Restore' : 'Minimize', icon: '−', onClick: () => this.toggleMinimize(), visible: this.opts.minimizable !== false },
      { id: 'maximize', title: 'Maximize', icon: '□', onClick: () => this.maximize(), visible: !this.isMaximized() && this.opts.maximizable !== false },
      { id: 'restore', title: 'Restore', icon: '❐', onClick: () => this.restore(), visible: this.isMaximized() },
      { id: 'float', title: this.isFloating() ? 'Dock' : 'Float', icon: this.isFloating() ? '⊡' : '⊟', onClick: () => this.toggleFloating(), visible: this.opts.floatable !== false },
      { id: 'refresh', title: 'Refresh', icon: '↻', onClick: () => this.refresh(), visible: !!this.opts.onRefresh },
      { id: 'popout', title: 'Open in new window', icon: '↗', onClick: () => this.openInNewWindow(), visible: true },
      { id: 'close', title: 'Close', icon: '×', onClick: () => this.close(), visible: this.opts.closable !== false }
    ];
    this.toolbar.innerHTML = '';
    for (const btn of buttons) {
      if (!btn.visible) continue;
      const button = el('button', { class: 'widget-toolbtn', type: 'button', title: btn.title, 'data-btn-id': btn.id }, btn.icon);
      this.disposers.push(on(button, 'click', (ev) => { stop(ev); btn.onClick(); this.renderToolbar(); }));
      this.toolbar.appendChild(button);
    }
  }

  setupInteractions() {
    if (this.opts.draggable !== false) {
      this.disposers.push(on(this.titleBar, 'pointerdown', (ev) => {
        if (ev.target.closest('button') || this.isMaximized()) return;
        if (this.isFloating()) this.beginFloatingDrag(ev);
        else if (this.dashboard) this.dashboard.layout.beginDrag(this, ev);
      }));
    }
    if (this.opts.resizable !== false) {
      this.disposers.push(on(this.resizeHandle, 'pointerdown', (ev) => {
        if (this.isMaximized()) return;
        if (this.isFloating()) this.beginFloatingResize(ev);
        else if (this.dashboard) this.dashboard.layout.beginResize(this, ev);
      }));
    }
    this.disposers.push(on(this.burgerBtn, 'click', (ev) => { stop(ev); this.showBurgerMenu(); }));
    this.disposers.push(on(this.titleBar, 'dblclick', (ev) => { if (ev.target.closest('button')) return; if (this.isMaximized()) this.restore(); else this.maximize(); }));
  }

  beginFloatingDrag(ev) {
    stop(ev);
    const rect = this.el.getBoundingClientRect();
    const offsetX = ev.clientX - rect.left, offsetY = ev.clientY - rect.top;
    const onMove = (e) => { this.el.style.left = cssPx(e.clientX - offsetX); this.el.style.top = cssPx(e.clientY - offsetY); };
    const onUp = () => { window.removeEventListener('pointermove', onMove, true); window.removeEventListener('pointerup', onUp, true); this.floatingStyles = { left: this.el.style.left, top: this.el.style.top, width: this.el.style.width, height: this.el.style.height }; };
    window.addEventListener('pointermove', onMove, true);
    window.addEventListener('pointerup', onUp, true);
  }

  beginFloatingResize(ev) {
    stop(ev);
    const rect = this.el.getBoundingClientRect();
    const startX = ev.clientX, startY = ev.clientY, startW = rect.width, startH = rect.height;
    const onMove = (e) => { this.el.style.width = cssPx(Math.max(200, startW + e.clientX - startX)); this.el.style.height = cssPx(Math.max(150, startH + e.clientY - startY)); };
    const onUp = () => { window.removeEventListener('pointermove', onMove, true); window.removeEventListener('pointerup', onUp, true); this.floatingStyles = { left: this.el.style.left, top: this.el.style.top, width: this.el.style.width, height: this.el.style.height }; };
    window.addEventListener('pointermove', onMove, true);
    window.addEventListener('pointerup', onUp, true);
  }

  showBurgerMenu() {
    document.querySelector('.widget-context-menu')?.remove();
    const menu = el('div', { class: 'widget-context-menu', role: 'menu' });
    const items = [
      { label: this.minimized ? 'Restore' : 'Minimize', action: () => this.toggleMinimize() },
      { label: this.isMaximized() ? 'Restore size' : 'Maximize', action: () => this.isMaximized() ? this.restore() : this.maximize() },
      { label: this.isFloating() ? 'Dock' : 'Float', action: () => this.toggleFloating() },
      { divider: true },
      { label: 'Refresh', action: () => this.refresh(), disabled: !this.opts.onRefresh },
      { label: 'Open in new window', action: () => this.openInNewWindow() },
      { divider: true },
      { label: 'Close', action: () => this.close() }
    ];
    for (const item of items) {
      if (item.divider) { menu.appendChild(el('hr', { class: 'widget-menu-divider' })); continue; }
      const btn = el('button', { class: 'widget-menu-item', type: 'button', disabled: item.disabled ? 'true' : '' }, item.label);
      on(btn, 'click', () => { item.action(); menu.remove(); });
      menu.appendChild(btn);
    }
    document.body.appendChild(menu);
    const rect = this.burgerBtn.getBoundingClientRect();
    Object.assign(menu.style, { position: 'fixed', top: cssPx(rect.bottom + 4), right: cssPx(window.innerWidth - rect.right), zIndex: '100000' });
    const closeMenu = (e) => { if (!e.target.closest('.widget-context-menu')) { menu.remove(); document.removeEventListener('pointerdown', closeMenu, true); } };
    setTimeout(() => document.addEventListener('pointerdown', closeMenu, true), 0);
  }

  destroy() { for (const d of this.disposers) d(); this.disposers = []; }
}


// ============================================================
// DASHBOARD VIEW
// ============================================================

class DashboardView {
  constructor(id, title, icon, opts = {}) {
    this.id = id;
    this._title = title;
    this._icon = icon;
    this.layoutMode = opts.layoutMode ?? 'grid';
    this.slideshowState = null;

    this.el = el('section', { class: 'dashboard-view', 'data-dashboard-id': id });
    this.header = el('div', { class: 'dashboard-header' });
    this.main = el('div', { class: 'dashboard-main' });
    this.footer = el('div', { class: 'dashboard-footer' });

    if (opts.template?.header) this.header.appendChild(opts.template.header);
    if (opts.template?.footer) this.footer.appendChild(opts.template.footer);
    this.el.append(this.header, this.main, this.footer);

    this.layout = this.layoutMode === 'dock'
      ? new DockLayout(this, opts.dock)
      : this.layoutMode === 'free'
        ? new FreeLayout(this, opts.free)
        : new GridLayout(this, opts.grid);
    this.main.appendChild(this.layout.el);
  }

  getTitle() { return this._title; }
  setTitle(title) { this._title = title; }
  getIcon() { return this._icon; }
  setIcon(icon) { this._icon = icon; }
  getLayoutMode() { return this.layoutMode; }
  getWidgets() { return this.layout.getWidgets(); }
  addWidget(widget, placement) { this.layout.addWidget(widget, placement); }
  removeWidget(widget) { this.layout.removeWidget(widget); }

  enterSlideshow() {
    const widgets = this.getWidgets();
    if (widgets.length === 0) return;
    this.slideshowState = { index: 0, widgets };

    const overlay = el('div', { class: 'slideshow-overlay' });
    const content = el('div', { class: 'slideshow-content' });
    const controls = el('div', { class: 'slideshow-controls' });

    const prevBtn = el('button', { class: 'slideshow-btn', type: 'button' }, '◀');
    const indicator = el('span', { class: 'slideshow-indicator' });
    const nextBtn = el('button', { class: 'slideshow-btn', type: 'button' }, '▶');
    const closeBtn = el('button', { class: 'slideshow-btn slideshow-close', type: 'button' }, '✕');

    on(prevBtn, 'click', () => this.slideshowPrev());
    on(nextBtn, 'click', () => this.slideshowNext());
    on(closeBtn, 'click', () => this.exitSlideshow());

    controls.append(prevBtn, indicator, nextBtn, closeBtn);
    overlay.append(content, controls);
    document.body.appendChild(overlay);

    this.slideshowState.overlay = overlay;
    this.slideshowState.content = content;
    this.slideshowState.indicator = indicator;

    const keyHandler = (e) => { if (e.key === 'ArrowLeft') this.slideshowPrev(); else if (e.key === 'ArrowRight') this.slideshowNext(); else if (e.key === 'Escape') this.exitSlideshow(); };
    window.addEventListener('keydown', keyHandler);
    this.slideshowState.keyHandler = keyHandler;
    this.showSlideshowWidget(0);
    bus.emit('slideshow:start', { dashboard: this });
  }

  showSlideshowWidget(index) {
    if (!this.slideshowState) return;
    const { widgets, content, indicator } = this.slideshowState;
    const len = widgets.length;
    this.slideshowState.index = ((index % len) + len) % len;
    const widget = widgets[this.slideshowState.index];
    if (content) {
      content.innerHTML = '';
      const clone = el('div', { class: 'slideshow-widget' });
      clone.innerHTML = `<div class="slideshow-widget-header"><span class="slideshow-icon">${widget.getIcon()}</span><span class="slideshow-title">${widget.getTitle()}</span></div><div class="slideshow-widget-body">${widget.el.querySelector('.widget-content')?.innerHTML ?? ''}</div>`;
      content.appendChild(clone);
    }
    if (indicator) indicator.textContent = `${this.slideshowState.index + 1} / ${len}`;
  }

  slideshowNext() { if (this.slideshowState) this.showSlideshowWidget(this.slideshowState.index + 1); }
  slideshowPrev() { if (this.slideshowState) this.showSlideshowWidget(this.slideshowState.index - 1); }

  exitSlideshow() {
    if (!this.slideshowState) return;
    if (this.slideshowState.keyHandler) window.removeEventListener('keydown', this.slideshowState.keyHandler);
    this.slideshowState.overlay?.remove();
    this.slideshowState = null;
    bus.emit('slideshow:end', { dashboard: this });
  }

  destroy() { this.exitSlideshow(); this.layout.destroy(); }
}


// ============================================================
// DASHBOARD CONTAINER
// ============================================================

class DashboardContainer {
  constructor(mount) {
    window.__dashboardContainer = this;
    this.el = el('div', { class: 'dashboard-container' });
    this.tabBar = el('div', { class: 'dashboard-tabbar' });
    this.tabStrip = el('div', { class: 'dashboard-tabs' });
    this.addBtn = el('button', { class: 'dashboard-tab-add', type: 'button', title: 'New dashboard' }, '+');
    this.disposers = [];
    this.disposers.push(on(this.addBtn, 'click', () => this.createDashboard()));
    this.tabBar.append(this.tabStrip, this.addBtn);
    this.content = el('div', { class: 'dashboard-content' });
    this.el.append(this.tabBar, this.content);
    mount.appendChild(this.el);
    this.dashboards = new Map();
    this.activeId = null;
  }

  getAllDashboards() { return Array.from(this.dashboards.values()); }
  getDashboard(id) { return this.dashboards.get(id); }
  getActiveDashboard() { return this.activeId ? this.dashboards.get(this.activeId) : undefined; }
  getAllWidgets() { const w = []; for (const d of this.dashboards.values()) w.push(...d.getWidgets()); return w; }
  findWidget(widgetId) { for (const d of this.dashboards.values()) { const w = d.layout.getWidget(widgetId); if (w) return { widget: w, dashboard: d }; } return null; }

  createDashboard(options = {}) {
    const count = this.dashboards.size + 1;
    return this.addDashboard(
      { title: options.title ?? `Dashboard ${count}`, icon: options.icon ?? '📊', closable: true },
      { layoutMode: options.layoutMode ?? 'grid', grid: { cols: 12, rows: 12 } }
    );
  }

  addDashboard(tab, view = {}) {
    const id = tab.id ?? uid('dash');
    if (this.dashboards.has(id)) throw new Error(`Dashboard "${id}" exists`);
    const dash = new DashboardView(id, tab.title, tab.icon ?? '📊', view);
    this.dashboards.set(id, dash);
    this.content.appendChild(dash.el);
    const tabEl = this.createTabElement(id, tab, view.layoutMode);
    this.tabStrip.appendChild(tabEl);
    if (!this.activeId) this.activate(id);
    bus.emit('dashboard:added', { dashboard: dash });
    return dash;
  }

  removeDashboard(id) {
    const dash = this.dashboards.get(id);
    if (!dash) return;
    dash.destroy();
    dash.el.remove();
    this.dashboards.delete(id);
    this.tabStrip.querySelector(`[data-dashboard-id="${id}"]`)?.remove();
    if (this.activeId === id) { this.activeId = null; const first = this.dashboards.keys().next().value; if (first) this.activate(first); }
    bus.emit('dashboard:removed', { dashboard: dash });
  }

  activate(id) {
    if (!this.dashboards.has(id)) return;
    this.activeId = id;
    for (const [dId, d] of this.dashboards) d.el.classList.toggle('is-active', dId === id);
    this.tabStrip.querySelectorAll('.dashboard-tab').forEach(t => t.classList.toggle('is-active', t.dataset.dashboardId === id));
    bus.emit('dashboard:activated', { dashboard: this.dashboards.get(id) });
  }

  forEach(callback) { this.dashboards.forEach((d, id) => callback(d, id)); }

  createTabElement(id, tab, layoutMode) {
    const tabEl = el('button', { class: 'dashboard-tab', type: 'button', 'data-dashboard-id': id });
    const icon = el('span', { class: 'dashboard-tab-icon' }, tab.icon ?? '📊');
    const title = el('span', { class: 'dashboard-tab-title' }, tab.title);
    const mode = el('span', { class: 'dashboard-tab-mode', title: `Layout: ${layoutMode ?? 'grid'}` }, layoutMode === 'dock' ? '⊞' : '⊡');
    const menu = el('button', { class: 'dashboard-tab-menu', type: 'button', title: 'Menu' }, '⋮');
    const close = el('button', { class: 'dashboard-tab-close', type: 'button', title: 'Close' }, '×');

    tabEl.append(icon, title, mode, menu);
    if (tab.closable !== false) tabEl.appendChild(close);

    this.disposers.push(on(tabEl, 'click', (ev) => { if (ev.target.closest('.dashboard-tab-close, .dashboard-tab-menu')) return; this.activate(id); }));
    this.disposers.push(on(close, 'click', (ev) => { stop(ev); this.removeDashboard(id); }));
    this.disposers.push(on(menu, 'click', (ev) => { stop(ev); this.showTabMenu(menu, id); }));
    return tabEl;
  }

  showTabMenu(anchor, id) {
    document.querySelector('.dashboard-menu')?.remove();
    const menu = el('div', { class: 'dashboard-menu', role: 'menu' });
    const dash = this.dashboards.get(id);
    if (!dash) return;

    const items = [
      { label: 'Rename...', action: () => { const t = prompt('Name:', dash.getTitle()); if (t) { dash.setTitle(t); const el = this.tabStrip.querySelector(`[data-dashboard-id="${id}"] .dashboard-tab-title`); if (el) el.textContent = t; } } },
      {
        label: 'Add Widget...', action: () => {
          const t = prompt('Title:', 'New Widget') ?? 'New Widget';
          const w = new Widget({ title: t, icon: '📦' });
          let p;
          if (dash.layoutMode === 'dock') p = 'center';
          else if (dash.layoutMode === 'free') p = dash.layout.findFreeSpace(320, 240);
          else p = dash.layout.findFreeSpace(4, 4) ?? { row: 0, col: 0, rowSpan: 4, colSpan: 4 };
          dash.addWidget(w, p);
        }
      },
      { divider: true },
      { label: `Mode: ${dash.getLayoutMode().toUpperCase()}`, disabled: true },
      { divider: true },
      { label: '▶ Slideshow', action: () => dash.enterSlideshow() },
      { divider: true },
      { label: 'Reset Layout', action: () => dash.layout.reset() }
    ];

    for (const item of items) {
      if (item.divider) { menu.appendChild(el('hr', { class: 'dashboard-menu-divider' })); continue; }
      const btn = el('button', { class: 'dashboard-menu-item', type: 'button', disabled: item.disabled ? 'true' : '' }, item.label);
      if (!item.disabled) on(btn, 'click', () => { item.action(); menu.remove(); });
      menu.appendChild(btn);
    }
    document.body.appendChild(menu);
    const rect = anchor.getBoundingClientRect();
    Object.assign(menu.style, { position: 'fixed', top: cssPx(rect.bottom + 4), left: cssPx(rect.left), zIndex: '100000' });
    const closeMenu = (e) => { if (!e.target.closest('.dashboard-menu')) { menu.remove(); document.removeEventListener('pointerdown', closeMenu, true); } };
    setTimeout(() => document.addEventListener('pointerdown', closeMenu, true), 0);
  }

  destroy() { delete window.__dashboardContainer; for (const d of this.dashboards.values()) d.destroy(); for (const d of this.disposers) d(); }
}


// ============================================================
// DEMO INITIALIZATION
// ============================================================

function initDemo() {
  const mount = document.getElementById('app') || document.body;
  const container = new DashboardContainer(mount);

  // ========================================
  // Dashboard 1: Sales (GRID MODE - snap-to-grid)
  // ========================================
  const salesDash = container.addDashboard(
    { id: 'sales', title: 'Sales (Grid)', icon: '💰', closable: false },
    { layoutMode: 'grid', grid: { cols: 12, rows: 12 } }
  );

  const revenueWidget = new Widget({
    id: 'revenue', title: 'Revenue', icon: '📈',
    content: `<div class="metric-card"><div class="metric-value">$1,234,567</div><div class="metric-label">Total Revenue</div><div class="metric-trend positive">↑ 12.5%</div></div>`,
    onRefresh: async (w) => { await new Promise(r => setTimeout(r, 500)); const val = Math.floor(Math.random() * 1000000 + 1000000); w.setContent(`<div class="metric-card"><div class="metric-value">$${val.toLocaleString()}</div><div class="metric-label">Total Revenue</div><div class="metric-trend positive">↑ ${(Math.random() * 20).toFixed(1)}%</div></div>`); }
  });
  salesDash.addWidget(revenueWidget, { row: 0, col: 0, rowSpan: 4, colSpan: 6 });

  const usersWidget = new Widget({
    id: 'users', title: 'Active Users', icon: '👥',
    content: `<div class="metric-card"><div class="metric-value">8,432</div><div class="metric-label">Online Now</div><div class="metric-trend positive">↑ 5.2%</div></div>`
  });
  salesDash.addWidget(usersWidget, { row: 0, col: 6, rowSpan: 4, colSpan: 6 });

  const conversionWidget = new Widget({
    id: 'conversion', title: 'Conversion Rate', icon: '🎯',
    content: `<div class="metric-card"><div class="metric-value">3.24%</div><div class="metric-label">Visitor to Customer</div><div class="progress-bar"><div class="progress-fill" style="width: 32.4%"></div></div></div>`
  });
  salesDash.addWidget(conversionWidget, { row: 4, col: 0, rowSpan: 4, colSpan: 4 });

  const ordersWidget = new Widget({
    id: 'orders', title: 'Recent Orders', icon: '📋',
    content: `<ul class="order-list"><li><span class="order-id">#12847</span><span class="order-amount">$234.00</span><span class="order-status completed">Completed</span></li><li><span class="order-id">#12846</span><span class="order-amount">$89.50</span><span class="order-status pending">Pending</span></li><li><span class="order-id">#12845</span><span class="order-amount">$567.00</span><span class="order-status completed">Completed</span></li></ul>`,
    onRefresh: async (w) => { await new Promise(r => setTimeout(r, 300)); const statuses = ['completed', 'pending', 'processing']; const items = Array.from({ length: 3 }, () => { const id = 12847 + Math.floor(Math.random() * 100); const amt = (Math.random() * 500 + 50).toFixed(2); const st = statuses[Math.floor(Math.random() * statuses.length)]; return `<li><span class="order-id">#${id}</span><span class="order-amount">$${amt}</span><span class="order-status ${st}">${st}</span></li>`; }).join(''); w.setContent(`<ul class="order-list">${items}</ul>`); }
  });
  salesDash.addWidget(ordersWidget, { row: 4, col: 4, rowSpan: 8, colSpan: 8 });

  // ========================================
  // Dashboard 2: Analytics (FREE MODE - absolute positioning)
  // ========================================
  const freeDash = container.addDashboard(
    { id: 'analytics', title: 'Analytics (Free)', icon: '📊', closable: true },
    { layoutMode: 'free', free: { snapToGrid: true, gridSize: 10 } }
  );

  const visitsWidget = new Widget({
    id: 'visits', title: 'Page Visits', icon: '👁️',
    content: `<div class="metric-card"><div class="metric-value">45,678</div><div class="metric-label">Today</div><div class="metric-trend positive">↑ 8.3%</div></div>`
  });
  freeDash.addWidget(visitsWidget, { x: 20, y: 20, width: 280, height: 180 });

  const bounceWidget = new Widget({
    id: 'bounce', title: 'Bounce Rate', icon: '📉',
    content: `<div class="metric-card"><div class="metric-value">32.1%</div><div class="metric-label">Average</div><div class="progress-bar"><div class="progress-fill warning" style="width: 32.1%"></div></div></div>`
  });
  freeDash.addWidget(bounceWidget, { x: 320, y: 20, width: 280, height: 180 });

  const sessionWidget = new Widget({
    id: 'session', title: 'Session Duration', icon: '⏱️',
    content: `<div class="metric-card"><div class="metric-value">4m 32s</div><div class="metric-label">Average Time</div></div>`
  });
  freeDash.addWidget(sessionWidget, { x: 20, y: 220, width: 400, height: 200 });

  // ========================================
  // Dashboard 3: Monitoring (DOCK MODE - split zones)
  // ========================================
  const dockDash = container.addDashboard(
    { id: 'monitor', title: 'Monitoring (Dock)', icon: '🖥️', closable: true },
    { layoutMode: 'dock' }
  );

  const cpuWidget = new Widget({
    id: 'cpu', title: 'CPU Usage', icon: '⚙️',
    content: `<div class="metric-card"><div class="metric-value">42%</div><div class="metric-label">Average Load</div><div class="progress-bar"><div class="progress-fill cpu" style="width: 42%"></div></div></div>`,
    onRefresh: async (w) => { await new Promise(r => setTimeout(r, 200)); const val = Math.floor(Math.random() * 80 + 10); w.setContent(`<div class="metric-card"><div class="metric-value">${val}%</div><div class="metric-label">Average Load</div><div class="progress-bar"><div class="progress-fill cpu" style="width: ${val}%"></div></div></div>`); }
  });
  dockDash.addWidget(cpuWidget, 'center');

  const memWidget = new Widget({
    id: 'memory', title: 'Memory', icon: '💾',
    content: `<div class="metric-card"><div class="metric-value">6.2 GB</div><div class="metric-label">of 16 GB Used</div><div class="progress-bar"><div class="progress-fill memory" style="width: 38.75%"></div></div></div>`
  });
  dockDash.addWidget(memWidget, 'right');

  const netWidget = new Widget({
    id: 'network', title: 'Network', icon: '📡',
    content: `<div class="metric-card"><div class="metric-row"><span class="metric-label">↓ Download</span><span class="metric-value small">125 MB/s</span></div><div class="metric-row"><span class="metric-label">↑ Upload</span><span class="metric-value small">45 MB/s</span></div></div>`
  });
  dockDash.addWidget(netWidget, 'bottom');

  const alertsWidget = new Widget({
    id: 'alerts', title: 'Alerts', icon: '🔔',
    content: `<ul class="alert-list"><li class="alert warning">⚠️ High CPU on server-03</li><li class="alert info">ℹ️ Backup completed</li><li class="alert error">❌ Connection timeout: db-replica</li></ul>`
  });
  dockDash.addWidget(alertsWidget, 'left');

  // Expose for debugging
  window.dashboardDemo = { container, salesDash, freeDash, dockDash, Widget, DashboardContainer, DashboardView, GridLayout, FreeLayout, DockLayout, bus };

  console.log('Dashboard Demo initialized!');
  console.log('- Sales: GRID mode (snap-to-grid cells)');
  console.log('- Analytics: FREE mode (drag anywhere)');
  console.log('- Monitoring: DOCK mode (split zones)');
  console.log('Access via window.dashboardDemo');
}

// Auto-init on DOM ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initDemo);
} else {
  initDemo();
}