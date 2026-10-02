// examples/a2ui/static/linked.js
// FEAT-610 — vanilla port of the FEAT-598 linked lane (ui/.../a2ui/linked/{fetch,conditions,index}.ts), extended for
// linked dashboards: dashboard-owned sources shared by several widgets, and `kind: "derived"` views computed from a
// sibling's frame with the transform DSL (`./dsl.js`) — never fetched, recomputed whenever the parent runs.
import { applyTransform, TransformError } from './dsl.js';

export const DEFAULT_MAX_FETCH_ROWS = 5000;

export class SourceUnavailable extends Error {
  constructor(slug) {
    super(`source '${slug}' unavailable`);
    this.name = 'SourceUnavailable';
  }
}

/** A descriptor written before the `derived` kind existed carries no `kind`: it is a query-slug source. */
export const isQuerySlug = (src) => (src.kind ?? 'query_slug') === 'query_slug';
export const isDerived = (src) => src.kind === 'derived';

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
 * The sibling keys a source needs first: `from` (derived) plus `join.with` / `union.sources` — twin of the Python
 * executor's `dependencies_of`.
 */
export function dependenciesOf(source) {
  const refs = [];
  if (isDerived(source)) refs.push(source.from);
  const ops = source.transform?.ops;
  if (!ops) return refs;
  for (const op of ops) {
    if (op.op === 'join') refs.push(op.with);
    else if (op.op === 'union') refs.push(...op.sources);
  }
  return refs;
}

/**
 * Topological order (dependencies first) + the set of sources that can never
 * succeed (a missing sibling, or part of a dependency cycle) — TS twin of the Python reference executor's `execution_order`.
 * Used only to proactively surface a stable 'error' status for a structurally-broken descriptor; `runSource` itself resolves dependencies lazily.
 */
export function executionOrder(sources, deps) {
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
  // Server-paged sources (a grid's own key) are fetched only through `fetchPage`: start / refreshAll / refreshSource
  // skip them, so the grid never costs a wasted bounded-frame fetch. `renderer.js` never pages a key that another
  // widget or a derived view also reads.
  const paged = new Set(pagedKeys);
  const deps = {};
  for (const key of Object.keys(sources)) deps[key] = dependenciesOf(sources[key]);
  const { order: topological, failed } = executionOrder(sources, deps);

  /**
   * Every derived key that (transitively, through derived keys only) depends on `key` — via `from`, `join.with` or
   * `union.sources` — in topological order. Recomputed after every run of `key` (the cascade); a query-slug dependent
   * is re-fetched only by an explicit refresh, exactly like the Python executor.
   */
  function derivedDependents(key) {
    const affected = new Set();
    let changed = true;
    while (changed) {
      changed = false;
      for (const d of Object.keys(sources)) {
        if (affected.has(d) || failed.has(d) || !isDerived(sources[d])) continue;
        if (deps[d].some((ref) => ref === key || affected.has(ref))) {
          affected.add(d);
          changed = true;
        }
      }
    }
    return topological.filter((d) => affected.has(d));
  }

  const overrides = {};
  const frames = {};
  const inFlight = {}; // the frame phase of the run in flight per key — NEVER its cascade
  const lastFailed = new Set(); // keys whose last frame phase failed: dependents never retry them on their own
  const refreshing = {};

  /**
   * Ensure `key` has a frame before a dependent runs — cycle-safe via `resolving`. A frame phase already in flight
   * for `key` is JOINED, never duplicated, and a key that just failed is not retried by each dependent.
   */
  async function ensureFrame(key, resolving) {
    const active = inFlight[key];
    if (active) await active; // a refresh in flight: wait for the fresh frame rather than reading the stale one
    if (frames[key] !== undefined || lastFailed.has(key)) return;
    await framePhase(key, false, resolving);
  }

  /** The joinable part of a run: produce `frames[key]` (always a fresh execution), serialised per key. */
  function framePhase(key, forceRefresh, resolving) {
    const previous = inFlight[key];
    let outcome = false;
    const started = previous ? previous.then(() => execute(key, forceRefresh, resolving)) : execute(key, forceRefresh, resolving);
    const run = started
      .then((ready) => {
        outcome = ready;
      })
      .finally(() => {
        if (inFlight[key] === run) delete inFlight[key];
      });
    inFlight[key] = run;
    return run.then(() => outcome);
  }

  /** Run `key`, then its derived dependents (the cascade) — OUTSIDE the joinable frame phase, so no deadlock. */
  async function runSource(key, forceRefresh, resolving = new Set()) {
    const ready = await framePhase(key, forceRefresh, resolving);
    const dependents = derivedDependents(key).filter((d) => !resolving.has(d));
    if (!ready) {
      for (const d of dependents) onUpdate({ key: d, rows: null, status: 'error', snapshotAt: null });
      return;
    }
    // Recompute (overwrite) each view in topological order; a consumer joining a view mid-cascade waits in ensureFrame.
    for (const d of dependents) await framePhase(d, false, resolving);
  }

  /** Fetch/transform (query_slug) or compute (derived) `frames[key]`; reports through onUpdate; never throws. */
  async function execute(key, forceRefresh, resolving) {
    const src = sources[key];
    if (!src) return false;
    if (resolving.has(key) || failed.has(key)) {
      // A real cycle, or a sibling reference that names nothing: never fetch, never blank the
      // snapshot — just report the error (TS twin of the Python executor's failed-source outcome).
      onUpdate({ key, rows: null, status: 'error', snapshotAt: null });
      return false;
    }
    resolving.add(key);
    onUpdate({ key, rows: null, status: 'loading', snapshotAt: null });
    try {
      for (const ref of deps[key]) {
        if (ref in sources) await ensureFrame(ref, resolving);
      }
      let rows;
      if (isQuerySlug(src)) {
        const placeholders = { ...(src.request.placeholders ?? {}), ...(overrides[key] ?? {}) };
        const request = { ...src.request, placeholders };
        const conditions = deriveConditions(request, lockedValues(src));
        if (forceRefresh) conditions.refresh = true;
        rows = await fetchSource(src, conditions, { baseUrl, token });
        if (src.transform?.ops) {
          rows = applyTransform(rows, src.transform, frames);
        }
        // A `transform.ref` (catalogued renderer module) is not supported by this example lane: the raw rows stand.
      } else {
        // Derived: the parent's FULL frame (never its ≤500-row snapshot) through the DSL.
        const base = frames[src.from];
        if (base === undefined) throw new TransformError(`parent source '${src.from}' has no frame`, key, 0);
        rows = applyTransform(base, src.transform, frames);
      }
      frames[key] = rows;
      lastFailed.delete(key);
      onUpdate({ key, rows, status: 'ready', snapshotAt: new Date().toISOString() });
      return true;
    } catch (err) {
      // A 404 (SourceUnavailable) is the only outcome the UI must word differently ("unavailable",
      // never "denied" — AC10); every other failure (a network error, a TransformError, ...) reports the same generic
      // 'error' status — the snapshot is never blanked either way (rows stays null).
      lastFailed.add(key);
      const status = err instanceof SourceUnavailable ? 'unavailable' : 'error';
      onUpdate({ key, rows: null, status, snapshotAt: null });
      return false;
    } finally {
      resolving.delete(key);
    }
  }

  function refreshSource(key) {
    if (!(key in sources) || failed.has(key) || paged.has(key)) return Promise.resolve();
    const src = sources[key];
    if (isDerived(src)) return refreshSource(src.from); // a derived view refreshes through its parent
    if (refreshing[key]) return refreshing[key];

    refreshing[key] = (async () => {
      lastFailed.delete(key);
      await runSource(key, true); // the cascade recomputes this key's derived views
      // Then every query-slug source that (transitively, through any kind) depends on `key`, dependencies first.
      const affected = new Set([key]);
      let changed = true;
      while (changed) {
        changed = false;
        for (const k of topological) {
          if (!affected.has(k) && deps[k].some((ref) => affected.has(ref))) {
            affected.add(k);
            changed = true;
          }
        }
      }
      for (const dependent of topological) {
        if (dependent !== key && affected.has(dependent) && isQuerySlug(sources[dependent]) && !paged.has(dependent)) {
          lastFailed.delete(dependent);
          await runSource(dependent, true);
        }
      }
    })().finally(() => {
      delete refreshing[key];
    });
    return refreshing[key];
  }

  return {
    start() {
      // Dependencies first, so a dependent declared before its parent joins that one fetch instead of issuing its own.
      for (const key of [...topological, ...Object.keys(sources).filter((k) => failed.has(k))]) {
        if (paged.has(key)) continue;
        if (failed.has(key)) {
          onUpdate({ key, rows: null, status: 'error', snapshotAt: null });
          continue;
        }
        if (isDerived(sources[key])) continue; // computed by the parent's cascade, never scheduled
        // For the vanilla port, we don't have RefreshScheduler; we just run once
        runSource(key, false);
      }
    },
    stop() {
      // No-op for vanilla port
    },
    async setParam(source, name, value) {
      const src = sources[source];
      if (!src || failed.has(source) || !isQuerySlug(src) || (src.locked ?? []).includes(name)) return;
      overrides[source] = { ...(overrides[source] ?? {}), [name]: value };
      lastFailed.delete(source);
      delete frames[source]; // force a re-fetch even if a sibling already cached this frame
      await runSource(source, false);
    },
    async refreshAll() {
      // Sequential, in dependency order — a single deterministic pass, same shape as the Python
      // reference executor's `execute_sources` loop (dependencies first). Derived views follow through the cascade.
      // Every query-slug source is fetched exactly once (dependencies first, no cascade yet), then every derived
      // view is recomputed once in topological order — one fetch per source per pass.
      for (const key of topological) {
        if (paged.has(key) || isDerived(sources[key]) || failed.has(key)) continue;
        lastFailed.delete(key);
        await framePhase(key, true, new Set());
      }
      for (const key of topological) {
        if (!isDerived(sources[key]) || failed.has(key)) continue;
        if (frames[sources[key].from] === undefined) {
          onUpdate({ key, rows: null, status: 'error', snapshotAt: null });
          continue;
        }
        await framePhase(key, false, new Set());
      }
    },
    /**
     * Example-only server paging (spec S2): reuse the source's slug/tenant/locked conditions and override only
     * `querylimit`/`_offset`/`ordering` and the column `filter`; a parallel `count(*)` on the same filter gives `total`.
     * Never touches the lane's frames, so the paged grid stays outside the normal linked-frame path.
     */
    async fetchPage(key, { offset = 0, limit = 20, filter = {}, ordering, refresh = false } = {}) {
      const src = sources[key];
      if (!src || failed.has(key) || !isQuerySlug(src)) throw new Error(`unknown source '${key}'`);
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
    refreshSource,
  };
}
