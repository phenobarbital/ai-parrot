// examples/a2ui/static/linked.js
// FEAT-610 — vanilla port of the FEAT-598 linked lane (ui/.../a2ui/linked/{fetch,conditions,index}.ts).

export const DEFAULT_MAX_FETCH_ROWS = 5000;

export class SourceUnavailable extends Error {
  constructor(slug) {
    super(`source '${slug}' unavailable`);
    this.name = 'SourceUnavailable';
  }
}

/**
 * Route rule (same as ui/.../api/querysource.ts): tenant → `/api/v1/{tenant}/queries/{slug}`; `isMultiquery` →
 * `/api/v3/queries/{slug}` (MultiQS, the only HTTP lane that expands a MultiQuery pipeline); otherwise the plain
 * `QS()` route `/api/v2/services/queries/{slug}`. MultiQS favours availability over latency (definition load, threads,
 * retries) — it is the pipeline/ETL lane, never the lane for a regular slug.
 */
export function queryUrl(baseUrl, slug, tenant, isMultiquery = false) {
  const base = baseUrl.replace(/\/$/, '');
  const s = encodeURIComponent(slug);
  if (tenant) return `${base}/api/v1/${encodeURIComponent(tenant)}/queries/${s}`;
  return isMultiquery ? `${base}/api/v3/queries/${s}` : `${base}/api/v2/services/queries/${s}`;
}

/**
 * Normalise a QuerySource JSON payload to a single row array (S4, same rule as the TS lane).
 * A plain array is already the single frame (the server unwraps a one-frame MultiQuery result before serializing);
 * a keyed object selects `src.multi_output` when set, else `'result'`, else the sole key when there is exactly one.
 * Anything else (ambiguous multi-frame with no selector, or an unexpected shape) yields `[]`.
 */
function selectFrame(payload, src) {
  if (Array.isArray(payload)) return payload;
  if (payload && typeof payload === 'object') {
    const frames = payload;
    const keys = Object.keys(frames);
    let selected;
    if (src.multi_output && Object.prototype.hasOwnProperty.call(frames, src.multi_output)) {
      selected = frames[src.multi_output];
    } else if (Object.prototype.hasOwnProperty.call(frames, 'result')) {
      selected = frames['result'];
    } else if (keys.length === 1) {
      selected = frames[keys[0]];
    } else {
      selected = [];
    }
    return Array.isArray(selected) ? selected : [];
  }
  return [];
}

export async function fetchSource(src, conditions, { baseUrl, token, maxFetchRows = DEFAULT_MAX_FETCH_ROWS }) {
  const cap = maxFetchRows ?? DEFAULT_MAX_FETCH_ROWS;
  // deriveConditions never emits `limit` (TASK-3770/TASK-3793); the lane re-applies request.limit bounded by the cap (S8/AC17)
  const body = { ...conditions, querylimit: Math.min(src.request.limit ?? cap, cap) };
  if (body.refresh !== true) delete body.refresh;
  const res = await fetch(queryUrl(baseUrl, src.slug, src.tenant ?? null, src.is_multiquery === true), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    if (res.status === 404) throw new SourceUnavailable(src.slug);
    throw new Error(`QuerySource ${res.status}`);
  }
  if (res.status === 204) return []; // QuerySource "Empty Result": zero rows, no body
  return selectFrame(await res.json(), src);
}

// Keys a lane adds at fetch time; deriveConditions never emits them.
const LANE_TIME_KEYS = new Set(['querylimit', 'refresh']);

export function deriveConditions(request, locked) {
  const out = {};

  // Rule 1: placeholders in request order, locked values overriding same-named keys
  // (locked-only keys appended after, as TS does)
  for (const [key, value] of Object.entries(request.placeholders ?? {})) {
    // Never emit lane-time keys
    if (!LANE_TIME_KEYS.has(key)) {
      out[key] = value;
    }
  }
  for (const [key, value] of Object.entries(locked ?? {})) {
    // Never emit lane-time keys
    if (!LANE_TIME_KEYS.has(key)) {
      out[key] = value;
    }
  }

  // Rule 2: filter entries verbatim
  if (request.filter && Object.keys(request.filter).length > 0) {
    out['filter'] = { ...request.filter };
  }

  // Rule 3: fields / ordering / grouping only when non-empty
  if (request.fields && request.fields.length > 0) {
    out['fields'] = [...request.fields];
  }
  if (request.ordering && request.ordering.length > 0) {
    out['ordering'] = [...request.ordering];
  }
  if (request.grouping && request.grouping.length > 0) {
    out['grouping'] = [...request.grouping];
  }

  // Rule 4: only the offset is a condition (`_offset`); `request.limit` becomes `querylimit` in fetchSource
  // (capped) — deriveConditions never emits `limit`, matching the Python reference and the shared fixtures.
  if (request.offset !== undefined && request.offset !== null) {
    out['_offset'] = request.offset;
  }

  return out;
}

/**
 * The sibling keys a source's own transform references via `join.with` / `union.sources`.
 */
function dependenciesOf(source) {
  const ops = source.transform?.ops;
  if (!ops) return [];
  const refs = [];
  for (const op of ops) {
    if (op.op === 'join') refs.push(op.with);
    else if (op.op === 'union') refs.push(...op.sources);
  }
  return refs;
}

/**
 * Topological order (join.with / union.sources first) + the set of sources that can never
 * succeed (a missing sibling, or part of a dependency cycle) — TS twin of the Python reference executor's `_execution_order`.
 * Used only to proactively surface a stable 'error' status for a structurally-broken descriptor; `runSource` itself resolves dependencies lazily.
 */
function executionOrder(sources, deps) {
  const keys = Object.keys(sources);
  const failed = new Set();
  for (const key of keys) {
    if (deps[key].some((ref) => !(ref in sources))) failed.add(key);
  }
  let changed = true;
  while (changed) {
    changed = false;
    for (const key of keys) {
      if (failed.has(key)) continue;
      if (deps[key].some((ref) => failed.has(ref))) {
        failed.add(key);
        changed = true;
      }
    }
  }
  const pending = keys.filter((key) => !failed.has(key));
  const indegree = {};
  const dependents = {};
  for (const key of pending) {
    indegree[key] = deps[key].filter((ref) => !failed.has(ref)).length;
    dependents[key] = [];
  }
  for (const key of pending) {
    for (const ref of deps[key]) {
      if (ref in dependents) dependents[ref].push(key);
    }
  }
  const order = [];
  let ready = pending.filter((key) => indegree[key] === 0);
  while (ready.length > 0) {
    ready.sort((a, b) => pending.indexOf(a) - pending.indexOf(b)); // stable: earliest-inserted first
    const key = ready.shift();
    order.push(key);
    for (const dependent of dependents[key]) {
      indegree[dependent] -= 1;
      if (indegree[dependent] === 0) ready.push(dependent);
    }
  }
  for (const key of pending) {
    if (!order.includes(key)) failed.add(key); // part of a cycle
  }
  return { order, failed };
}

/**
 * `{name: value}` for every locked name present in `source.conditions` — TS twin of the Python reference executor's `locked_values`/`_conditions_for`.
 */
function lockedValues(source) {
  const out = {};
  for (const name of source.locked ?? []) {
    if (name in source.conditions) out[name] = source.conditions[name];
  }
  return out;
}

export function createLane(sources, { baseUrl, token, onUpdate, pagedKeys = [] }) {
  // Server-paged sources (the grid) are fetched only through `fetchPage`: start / refreshAll / refreshSource skip them,
  // so the grid never costs a wasted bounded-frame fetch.
  const paged = new Set(pagedKeys);
  const deps = {};
  for (const key of Object.keys(sources)) deps[key] = dependenciesOf(sources[key]);
  const { failed } = executionOrder(sources, deps);

  const overrides = {};
  const frames = {};
  const schedulers = {};
  const inFlight = {};
  const refreshing = {};

  /**
   * Ensure `key`'s dependencies have a frame before it runs — cycle-safe via `resolving`.
   */
  async function ensureFrame(key, resolving) {
    if (frames[key] !== undefined) return;
    if (!(key in inFlight)) {
      inFlight[key] = runSource(key, false, resolving).finally(() => {
        delete inFlight[key];
      });
    }
    await inFlight[key];
  }

  async function runSource(key, forceRefresh, resolving = new Set()) {
    const src = sources[key];
    if (!src) return;
    if (resolving.has(key) || failed.has(key)) {
      // A real cycle, or a sibling reference that names nothing: never fetch, never blank the
      // snapshot — just report the error (TS twin of the Python executor's failed-source outcome).
      onUpdate({ key, rows: null, status: 'error', snapshotAt: null });
      return;
    }
    resolving.add(key);
    onUpdate({ key, rows: null, status: 'loading', snapshotAt: null });
    try {
      for (const ref of deps[key]) {
        if (ref in sources) await ensureFrame(ref, resolving);
      }
      const placeholders = { ...(src.request.placeholders ?? {}), ...(overrides[key] ?? {}) };
      const request = { ...src.request, placeholders };
      const conditions = deriveConditions(request, lockedValues(src));
      if (forceRefresh) conditions.refresh = true;
      const rawRows = await fetchSource(src, conditions, { baseUrl, token });
      let rows = rawRows;
      if (src.transform?.ops) {
        // Transform logic would go here; for the vanilla port we just pass through
        rows = rawRows;
      } else if (src.transform?.ref) {
        // Transform ref would go here; for the vanilla port we just pass through
        rows = rawRows;
      }
      frames[key] = rows;
      onUpdate({ key, rows, status: 'ready', snapshotAt: new Date().toISOString() });
    } catch (err) {
      // A 404 (SourceUnavailable) is the only outcome the UI must word differently ("unavailable",
      // never "denied" — AC10); every other failure (a network error, ...) reports the same generic 'error' status — the snapshot is never blanked either way (rows stays null).
      const status = err instanceof SourceUnavailable ? 'unavailable' : 'error';
      onUpdate({ key, rows: null, status, snapshotAt: null });
    } finally {
      resolving.delete(key);
    }
  }

  return {
    start() {
      for (const key of Object.keys(sources)) {
        if (paged.has(key)) continue;
        if (failed.has(key)) {
          onUpdate({ key, rows: null, status: 'error', snapshotAt: null });
          continue;
        }
        // For the vanilla port, we don't have RefreshScheduler; we just run once
        runSource(key, false);
      }
    },
    stop() {
      // No-op for vanilla port
    },
    async setParam(source, name, value) {
      const src = sources[source];
      if (!src || failed.has(source) || (src.locked ?? []).includes(name)) return;
      overrides[source] = { ...(overrides[source] ?? {}), [name]: value };
      delete frames[source]; // force a re-fetch even if a sibling already cached this frame
      await runSource(source, false);
    },
    async refreshAll() {
      // Sequential, in dependency order — a single deterministic pass, same shape as the Python
      // reference executor's `execute_sources` loop (siblings first).
      const { order } = executionOrder(sources, deps);
      for (const key of order) {
        if (paged.has(key)) continue;
        delete frames[key];
        await runSource(key, true);
      }
    },
    /**
     * Example-only server paging (spec S2): reuse the source's slug/tenant/locked conditions and override only
     * `querylimit`/`_offset`/`ordering` and the column `filter`; a parallel `count(*)` on the same filter gives `total`.
     * Never touches the lane's frames, so the paged grid stays outside the normal linked-frame path.
     */
    async fetchPage(key, { offset = 0, limit = 20, filter = {}, ordering, refresh = false } = {}) {
      const src = sources[key];
      if (!src || failed.has(key)) throw new Error(`unknown source '${key}'`);
      const placeholders = { ...(src.request.placeholders ?? {}), ...(overrides[key] ?? {}) };
      const base = deriveConditions({ ...src.request, placeholders }, lockedValues(src));
      const merged = { ...(base.filter ?? {}) };
      for (const [column, value] of Object.entries(filter ?? {})) {
        if (value !== '' && value !== null && value !== undefined) merged[column] = value;
      }
      const pageConditions = { ...base, _offset: offset };
      const order = ordering ?? base.ordering ?? [];
      if (order.length > 0) pageConditions.ordering = [...order];
      else delete pageConditions.ordering;
      const countConditions = { ...base };
      for (const dropped of ['fields', 'ordering', 'grouping', '_offset']) delete countConditions[dropped];
      countConditions.fields = ['count(*) as total'];
      for (const c of [pageConditions, countConditions]) {
        if (Object.keys(merged).length > 0) c.filter = { ...merged };
        else delete c.filter;
      }
      if (refresh) {
        pageConditions.refresh = true; // a manual refresh bypasses the server cache for both requests
        countConditions.refresh = true;
      }
      const opts = { baseUrl, token };
      const [rows, counted] = await Promise.all([
        fetchSource({ ...src, request: { ...src.request, limit } }, pageConditions, opts),
        fetchSource({ ...src, request: { ...src.request, limit: 1 } }, countConditions, opts),
      ]);
      const total = Number(counted[0]?.total);
      return { rows, total: Number.isFinite(total) ? total : rows.length };
    },
    refreshSource(key) {
      if (!(key in sources) || failed.has(key) || paged.has(key)) return Promise.resolve();
      if (refreshing[key]) return refreshing[key];

      refreshing[key] = (async () => {
        delete frames[key];
        await runSource(key, true);
        const { order } = executionOrder(sources, deps);
        for (const dependent of order) {
          if (dependent !== key && deps[dependent].includes(key)) {
            delete frames[dependent];
            await runSource(dependent, true);
          }
        }
      })().finally(() => {
        delete refreshing[key];
      });
      return refreshing[key];
    },
  };
}
