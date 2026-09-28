// examples/a2ui/static/renderer.js
// FEAT-610 — renders the agent-built linked dashboard (KPICard / Chart / DataTable) and wires per-widget refresh.
//
// Envelope shape (CreateSurface dump served by /api/a2ui/dashboard):
//   { surfaceId, components: [{id, component, ...}], dataModel: {key: {rows}},
//     metadata: {extensions: {parrot_data_sources: {key: source}}} }
// Bindings: Chart/DataTable `data.path` = "/<key>/rows"; KPICard `value.path` = "/<key>/rows/0/<column>".
import { createLane } from './linked.js';

const TOKEN_KEY = 'ai_parrot_token';
const UNASSIGNED = 'Unassigned';
const GRID_PAGE_SIZE = 20;

// ---------------------------------------------------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------------------------------------------------

/** Return a display label; NULL / empty buckets are shown as "Unassigned". */
export function label(value) {
  return value === null || value === undefined || value === '' ? UNASSIGNED : String(value);
}

/** Parse a JSON-pointer binding ("/key/rows" or "/key/rows/0/column") into `{key, column}`; null when unbound. */
export function parseBinding(binding) {
  const path = typeof binding === 'string' ? binding : binding && typeof binding === 'object' ? binding.path : null;
  if (typeof path !== 'string') return null;
  const parts = path.split('/').filter(Boolean);
  if (parts.length < 2 || parts[1] !== 'rows') return null;
  return { key: parts[0], column: parts.length >= 4 ? parts[3] : null };
}

/** Index the envelope: components by id, the linked sources, and the baked snapshot rows per source key. */
export function planDashboard(envelope) {
  const byId = {};
  for (const component of envelope.components ?? []) byId[component.id] = component;
  const sources = envelope.metadata?.extensions?.parrot_data_sources ?? {};
  const snapshot = {};
  for (const [key, value] of Object.entries(envelope.dataModel ?? {})) {
    snapshot[key] = Array.isArray(value?.rows) ? value.rows : [];
  }
  return { byId, rootId: byId.root ? 'root' : (envelope.components?.[0]?.id ?? 'root'), sources, snapshot };
}

/** The KPI number: the bound column of the first row, formatted for display. */
export function kpiText(rows, column) {
  const value = rows && rows.length > 0 && column ? rows[0][column] : null;
  if (value === null || value === undefined) return '—';
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString('en-US') : String(value);
}

/** Build the ECharts option for a Chart node (`type`: bar | pie | donut, `x` category column, `y` value columns). */
export function chartOption(node, rows) {
  const x = node.x;
  const ys = Array.isArray(node.y) ? node.y : node.y ? [node.y] : [];
  const title = { text: node.title ?? '' };
  if (node.type === 'pie' || node.type === 'donut') {
    return {
      title,
      tooltip: { trigger: 'item' },
      legend: {},
      series: [
        {
          type: 'pie',
          radius: node.type === 'donut' ? ['40%', '70%'] : '70%',
          data: rows.map((row) => ({ name: label(row[x]), value: Number(row[ys[0]]) })),
        },
      ],
    };
  }
  return {
    title,
    tooltip: { trigger: 'axis' },
    legend: ys.length > 1 ? {} : undefined,
    xAxis: { type: 'category', data: rows.map((row) => label(row[x])), axisLabel: { interval: 0, rotate: 45 } },
    yAxis: { type: 'value' },
    series: ys.map((column) => ({ name: column, type: 'bar', data: rows.map((row) => Number(row[column])) })),
  };
}

/** Column names for a DataTable: node.columns (strings or {name|field|id|key}) → the source fields → the row keys. */
export function gridColumns(node, source, rows) {
  const fromNode = (node.columns ?? [])
    .map((c) => (typeof c === 'string' ? c : (c?.name ?? c?.field ?? c?.id ?? c?.key)))
    .filter(Boolean);
  if (fromNode.length > 0) return fromNode;
  const fromSource = (source?.request?.fields ?? []).map((f) => f.split(/\s+as\s+/i).pop().trim());
  if (fromSource.length > 0) return fromSource;
  return rows && rows.length > 0 ? Object.keys(rows[0]) : [];
}

// ---------------------------------------------------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------------------------------------------------

/** POST the credentials, store the JWT under `ai_parrot_token` and return it. */
export async function login(username, password, { fetchImpl = fetch, storage = localStorage } = {}) {
  const response = await fetchImpl('/api/v1/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Auth-Method': 'BasicAuth' },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) throw new Error(`Login failed: ${response.status}`);
  const data = await response.json();
  if (!data.token) throw new Error('No token received from server');
  storage.setItem(TOKEN_KEY, data.token);
  return data.token;
}

// ---------------------------------------------------------------------------------------------------------------------
// DOM widgets (every dynamic string goes through textContent — the envelope is LLM-built, never trusted as HTML)
// ---------------------------------------------------------------------------------------------------------------------

function el(doc, tag, className, text) {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function toolbar(doc, lane, key, onRefresh) {
  const bar = el(doc, 'div', 'widget-toolbar');
  const button = el(doc, 'button', 'refresh', 'Refresh');
  button.type = 'button';
  button.dataset.refresh = key;
  button.onclick = () => onRefresh();
  const status = el(doc, 'span', 'status', 'loading');
  status.dataset.status = key;
  bar.append(button, status);
  return { bar, status };
}

function makeKpi(doc, node, key, binding, lane) {
  const box = el(doc, 'div', 'kpi-card');
  box.dataset.widget = key;
  const value = el(doc, 'div', 'kpi-value', '—');
  const bar = toolbar(doc, lane, key, () => lane.refreshSource(key));
  box.append(el(doc, 'div', 'kpi-title', node.title ?? key), value, el(doc, 'div', 'kpi-description', node.description ?? ''), bar.bar);
  return {
    element: box,
    update(rows, status) {
      if (status) bar.status.textContent = status;
      if (rows) value.textContent = kpiText(rows, binding.column);
    },
  };
}

function makeChart(doc, node, key, lane) {
  const box = el(doc, 'div', 'chart-container');
  box.dataset.widget = key;
  const bar = toolbar(doc, lane, key, () => lane.refreshSource(key));
  const canvas = el(doc, 'div', 'chart');
  box.append(bar.bar, canvas);
  let instance = null;
  return {
    element: box,
    update(rows, status) {
      if (status) bar.status.textContent = status;
      if (!rows) return;
      const echarts = doc.defaultView?.echarts ?? globalThis.echarts;
      if (!echarts) {
        bar.status.textContent = 'echarts unavailable';
        return;
      }
      if (!instance) instance = echarts.init(canvas); // one instance per widget: repaint, never re-init
      instance.setOption(chartOption(node, rows), true);
    },
  };
}

function makeGrid(doc, node, key, source, lane) {
  const box = el(doc, 'div', 'datatable-container');
  box.dataset.widget = key;
  const state = { page: 0, total: 0, filters: {}, columns: gridColumns(node, source, []) };
  const status = el(doc, 'span', 'status', 'loading');
  status.dataset.status = key;
  const refresh = el(doc, 'button', 'refresh', 'Refresh');
  refresh.type = 'button';
  refresh.dataset.refresh = key;
  const bar = el(doc, 'div', 'widget-toolbar');
  bar.append(refresh, status);
  const table = el(doc, 'table', 'grid');
  const head = el(doc, 'thead');
  const filterRow = el(doc, 'tr', 'grid-filters');
  const titleRow = el(doc, 'tr');
  const body = el(doc, 'tbody');
  const pager = el(doc, 'div', 'grid-pager');
  const prev = el(doc, 'button', 'grid-prev', 'Previous');
  const next = el(doc, 'button', 'grid-next', 'Next');
  const info = el(doc, 'span', 'grid-info', '');
  prev.type = next.type = 'button';
  pager.append(prev, info, next);
  head.append(titleRow, filterRow);
  table.append(head, body);
  box.append(bar, table, pager);

  function buildHeader(columns) {
    titleRow.replaceChildren();
    filterRow.replaceChildren();
    for (const column of columns) {
      titleRow.append(el(doc, 'th', '', column));
      const cell = el(doc, 'th');
      const input = el(doc, 'input'); // column filters only: exact-match `filter`, no free-text search
      input.type = 'text';
      input.dataset.filter = column;
      input.placeholder = 'filter';
      input.onchange = () => {
        state.filters[column] = input.value.trim();
        state.page = 0;
        load();
      };
      cell.append(input);
      filterRow.append(cell);
    }
  }

  function paint(rows) {
    if (state.columns.length === 0 && rows.length > 0) {
      state.columns = Object.keys(rows[0]);
    }
    if (titleRow.childNodes.length !== state.columns.length) buildHeader(state.columns);
    body.replaceChildren();
    for (const row of rows) {
      const tr = el(doc, 'tr');
      for (const column of state.columns) tr.append(el(doc, 'td', '', row[column] === null || row[column] === undefined ? '' : String(row[column])));
      body.append(tr);
    }
    const pages = Math.max(1, Math.ceil(state.total / GRID_PAGE_SIZE));
    info.textContent = `page ${state.page + 1} / ${pages} · ${state.total.toLocaleString('en-US')} rows`;
    prev.disabled = state.page <= 0;
    next.disabled = state.page + 1 >= pages;
  }

  let seq = 0;
  async function load(refresh = false) {
    const mine = ++seq;
    status.textContent = 'loading';
    try {
      const { rows, total } = await lane.fetchPage(key, {
        offset: state.page * GRID_PAGE_SIZE,
        limit: GRID_PAGE_SIZE,
        filter: state.filters,
        refresh,
      });
      if (mine !== seq) return; // a newer page/filter request superseded this one
      state.total = total;
      paint(rows);
      status.textContent = 'ready';
    } catch (err) {
      if (mine === seq) status.textContent = err instanceof Error && err.name === 'SourceUnavailable' ? 'unavailable' : 'error';
    }
  }

  prev.onclick = () => {
    if (state.page > 0) {
      state.page -= 1;
      load();
    }
  };
  next.onclick = () => {
    state.page += 1;
    load();
  };
  // Per-widget refresh: the grid is server-paged and outside the lane's frames, so refresh is exactly this widget's own
  // page + count requests to its own source, both cache-bypassing (`refresh: true`); no other widget is touched.
  refresh.onclick = () => load(true);
  return {
    element: box,
    start: () => load(false),
    reload: () => load(true),
    update(rows, laneStatus) {
      // The lane's frame is a bounded preview; the grid's rows always come from `fetchPage`.
      if (laneStatus && laneStatus !== 'ready') status.textContent = laneStatus;
    },
  };
}

function renderNode(doc, id, ctx) {
  const node = ctx.plan.byId[id];
  if (!node) return null;
  switch (node.component) {
    case 'Column':
    case 'Row': {
      const box = el(doc, 'div', node.component === 'Row' ? 'row' : 'column');
      box.id = id;
      for (const childId of node.children ?? []) {
        const child = renderNode(doc, childId, ctx);
        if (child) box.append(child);
      }
      return box;
    }
    case 'Text':
      return el(doc, 'h2', 'dashboard-title', node.text ?? '');
    case 'KPICard': {
      const binding = parseBinding(node.value);
      if (!binding) return el(doc, 'div', 'notice', `KPICard '${id}' has no data binding`);
      return register(ctx, binding.key, makeKpi(doc, node, binding.key, binding, ctx.lane));
    }
    case 'Chart': {
      const binding = parseBinding(node.data);
      if (!binding) return el(doc, 'div', 'notice', `Chart '${id}' has no data binding`);
      return register(ctx, binding.key, makeChart(doc, node, binding.key, ctx.lane));
    }
    case 'DataTable': {
      const binding = parseBinding(node.data);
      if (!binding) return el(doc, 'div', 'notice', `DataTable '${id}' has no data binding`);
      const widget = makeGrid(doc, node, binding.key, ctx.plan.sources[binding.key], ctx.lane);
      ctx.grids.push(widget);
      return register(ctx, binding.key, widget);
    }
    default:
      return el(doc, 'div', 'notice', `Unsupported component: ${node.component}`);
  }
}

function register(ctx, key, widget) {
  ctx.widgets[key] = widget;
  return widget.element;
}

/**
 * Render the envelope into `container` and start the lane.
 *
 * @returns {{lane: object, widgets: object, refreshAll: Function}} The running lane, the widget registry keyed by
 * source key, and a refresh-everything helper.
 */
export function mountDashboard(envelope, { doc = document, container, token, baseUrl, laneFactory = createLane }) {
  const plan = planDashboard(envelope);
  const ctx = { plan, widgets: {}, grids: [], lane: null };
  const pagedKeys = Object.values(plan.byId)
    .filter((node) => node.component === 'DataTable')
    .map((node) => parseBinding(node.data)?.key)
    .filter(Boolean);
  const lane = laneFactory(plan.sources, {
    baseUrl,
    token,
    pagedKeys,
    onUpdate: (update) => ctx.widgets[update.key]?.update(update.rows, update.status),
  });
  ctx.lane = lane;
  const root = renderNode(doc, plan.rootId, ctx);
  if (root) container.append(root);
  for (const [key, widget] of Object.entries(ctx.widgets)) widget.update(plan.snapshot[key] ?? [], null); // baked snapshot first
  lane.start();
  for (const grid of ctx.grids) grid.start();
  // "Refresh all" re-fetches every linked source, then each server-paged grid reloads its current page (cache-bypassing).
  const refreshAll = async () => {
    await lane.refreshAll();
    await Promise.all(ctx.grids.map((grid) => grid.reload()));
  };
  return { lane, widgets: ctx.widgets, refreshAll };
}

// ---------------------------------------------------------------------------------------------------------------------
// Boot (browser only)
// ---------------------------------------------------------------------------------------------------------------------

function notice(doc, message) {
  const node = doc.getElementById('notice');
  if (node) node.textContent = message;
}

async function boot(doc = document) {
  // Bind the login form FIRST: with no token boot() returns early, and the form must still work.
  doc.getElementById('loginForm').onsubmit = async (event) => {
    event.preventDefault();
    try {
      await login(doc.getElementById('username').value, doc.getElementById('password').value);
      window.location.reload();
    } catch (error) {
      notice(doc, error.message);
    }
  };
  doc.getElementById('logout').onclick = () => {
    localStorage.removeItem(TOKEN_KEY);
    window.location.reload();
  };

  const token = localStorage.getItem(TOKEN_KEY);
  doc.getElementById('login').style.display = token ? 'none' : 'block';
  doc.getElementById('app').style.display = token ? 'block' : 'none';
  if (!token) return;

  try {
    const response = await fetch('/api/a2ui/dashboard', { headers: { Authorization: `Bearer ${token}` } });
    if (response.status === 401 || response.status === 403) {
      localStorage.removeItem(TOKEN_KEY);
      window.location.reload();
      return;
    }
    if (!response.ok) throw new Error(`Failed to load the dashboard: ${response.status}`);
    const envelope = await response.json();
    const { refreshAll } = mountDashboard(envelope, {
      doc,
      container: doc.getElementById('dashboard'),
      token,
      baseUrl: window.location.origin,
    });
    doc.getElementById('refreshAll').onclick = () => refreshAll();
  } catch (error) {
    notice(doc, error.message);
  }
}

if (typeof document !== 'undefined' && typeof window !== 'undefined' && !globalThis.__A2UI_NO_BOOT__) {
  document.addEventListener('DOMContentLoaded', () => boot(document));
}
