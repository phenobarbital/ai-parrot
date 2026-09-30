/**
 * Bundled-renderer executor lane (FEAT-598, spec §3 Module 11; linked dashboards).
 * Plain TS: per-source RefreshScheduler → deriveConditions → fetchSource → applyTransform|loadRef,
 * reporting through `onUpdate`; the Svelte surface owns the reactive state.
 *
 * Dependency order (derived `from`, join.with / union.sources) and per-source `locked` enforcement are TS
 * twins of the Python reference executor's `execution_order` / `_conditions_for`
 * (`parrot.outputs.a2ui.linked.executor`, spec §3 M5) — a source that depends on siblings is resolved
 * AFTER them, lazily: whichever source runs first (mount, interval tick, `setParam`, or `refreshAll`)
 * ensures its own dependencies have a frame before it runs, and every run is registered in `inFlight`, so
 * the dashboard fetches each query-slug source exactly once per pass however many widgets read it.
 *
 * A `derived` source is never fetched: it is computed from its parent's FULL frame with the DSL and
 * recomputed (cascade) whenever the parent produces a new frame. It has no scheduler, no params and no
 * refresh of its own — `refreshSource(<derived>)` refreshes its parent.
 */
import { deriveConditions } from './conditions';
import { applyTransform, TransformError } from './dsl';
import { fetchSource, SourceUnavailable } from './fetch';
import { RefreshScheduler } from './scheduler';
import { loadRef } from './ref';
import { isDerived, isQuerySlug } from './types';
import type { LinkedDataSource, LinkedSource, LinkedSources, Row } from './types';

export const LINKED_LANE_CONTEXT = Symbol('a2ui-linked-lane');

/**
 * A second, deliberately separate Svelte context (FEAT-598, TASK-3795, spec §7.4): a `FilterBar`
 * filter WITHOUT `parrot_param` never touches the lane above — it re-slices whatever rows are
 * already embedded in the surface's `dataModel`. A surface with no `parrot_data_sources` at all
 * (no lane, `LINKED_LANE_CONTEXT` unset) can still carry a FilterBar over its static snapshot, so
 * this must not be folded into `LinkedLane`. `values.length === 0` means "all" (unconstrained),
 * the same convention as the wire's `value: []`.
 */
export const FILTER_CONTEXT = Symbol('a2ui-local-filter');

export interface FilterController {
  setFilter(column: string, values: string[]): void;
  getFilter(column: string): string[];
}

export type SourceStatus = 'loading' | 'ready' | 'unavailable' | 'error';

export interface SourceUpdate {
  key: string;
  rows: Row[] | null; // null ⇒ keep the current rows (failure never blanks the snapshot)
  status: SourceStatus;
  snapshotAt: string | null;
}

export interface LinkedLaneOptions {
  baseUrl: string;
  headers: () => HeadersInit;
  transformsBase: string;
  onUpdate: (update: SourceUpdate) => void;
}

export interface LinkedLane {
  start(): void;
  stop(): void;
  /** Re-fetch `source` with `name` overridden (FilterBar parrot_param). Locked or undeclared (∉ src.params) names, and derived sources, are ignored. */
  setParam(source: string, name: string, value: unknown): Promise<void>;
  /** Manual refresh of every source (policy manual / user button). Derived views are recomputed through the cascade. */
  refreshAll(): Promise<void>;
  /** Current per-source param overrides (a copy), shaped for POST /refresh {params} (service.py:162-171). Never lists derived keys. */
  getParams(): Record<string, Record<string, unknown>>;
  /** Manual refresh of ONE source (per-widget refresh button). Unknown/failed keys are a no-op; a derived key refreshes its parent. */
  refreshSource(key: string): Promise<void>;
}

/** `{name: value}` for every locked name present in `source.conditions` — TS twin of the Python
 * reference executor's `locked_values`/`_conditions_for` (spec §3 M5, S5). */
function lockedValues(source: LinkedDataSource): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const name of source.locked ?? []) {
    if (name in source.conditions) out[name] = source.conditions[name];
  }
  return out;
}

/** The sibling keys a source needs first: `from` (derived) plus `join.with` / `union.sources` — TS twin of `dependencies_of`. */
export function dependenciesOf(source: LinkedSource): string[] {
  const refs: string[] = [];
  if (isDerived(source)) refs.push(source.from);
  const ops = source.transform?.ops;
  if (!ops) return refs;
  for (const op of ops) {
    if (op.op === 'join') refs.push((op as { with: string }).with);
    else if (op.op === 'union') refs.push(...((op as { sources: string[] }).sources));
  }
  return refs;
}

/**
 * Topological order (dependencies first) + the set of sources that can never
 * succeed (a missing sibling, or part of a dependency cycle) — TS twin of the Python reference
 * executor's `execution_order`. Used only to proactively surface a stable 'error' status for a
 * structurally-broken descriptor; `runSource` itself resolves dependencies lazily (see below).
 */
export function executionOrder(
  sources: LinkedSources,
  deps: Record<string, string[]>,
): { order: string[]; failed: Set<string> } {
  const keys = Object.keys(sources);
  const failed = new Set<string>();
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
  const indegree: Record<string, number> = {};
  const dependents: Record<string, string[]> = {};
  for (const key of pending) {
    indegree[key] = deps[key].filter((ref) => !failed.has(ref)).length;
    dependents[key] = [];
  }
  for (const key of pending) {
    for (const ref of deps[key]) {
      if (ref in dependents) dependents[ref].push(key);
    }
  }
  const order: string[] = [];
  let ready = pending.filter((key) => indegree[key] === 0);
  while (ready.length > 0) {
    ready.sort((a, b) => pending.indexOf(a) - pending.indexOf(b)); // stable: earliest-inserted first
    const key = ready.shift() as string;
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

/** Overrides to send with a server-side refresh, `{<sourceKey>: {name: value}}` — never the stored placeholders. */
export function currentParams(lane: LinkedLane): Record<string, Record<string, unknown>> {
  return lane.getParams();
}

export function createLinkedLane(sources: LinkedSources, opts: LinkedLaneOptions): LinkedLane {
  const deps: Record<string, string[]> = {};
  for (const key of Object.keys(sources)) deps[key] = dependenciesOf(sources[key]);
  const { failed } = executionOrder(sources, deps);
  /** Derived keys computed from `key`, in descriptor order — recomputed after every successful run of `key`. */
  const derivedOf = (key: string): string[] =>
    Object.keys(sources).filter((d) => isDerived(sources[d]) && sources[d].from === key && !failed.has(d));

  const overrides: Record<string, Record<string, unknown>> = {};
  // Last known snapshot per source: seeded from the descriptor, advanced on every 'ready' update, and reported
  // with every error/unavailable update so the notice says "data as of <snapshot>", not "never".
  const lastSnapshotAt: Record<string, string | null> = {};
  for (const key of Object.keys(sources)) lastSnapshotAt[key] = sources[key].snapshot_at ?? null;
  const frames: Record<string, Row[]> = {};
  const schedulers: Record<string, RefreshScheduler> = {};
  const inFlight: Record<string, Promise<void> | undefined> = {};
  const refreshing: Record<string, Promise<void> | undefined> = {};

  /**
   * Ensure `key` has a frame before a dependent runs — cycle-safe via `resolving`. A run already in flight for
   * `key` (its own mount-time scheduler, typically) is JOINED, never duplicated: a parent shared by N derived
   * views / joins is fetched once per pass.
   */
  async function ensureFrame(key: string, resolving: Set<string>): Promise<void> {
    if (frames[key] !== undefined) return;
    const active = inFlight[key];
    if (active) {
      await active;
      if (frames[key] !== undefined) return;
    }
    await runSource(key, false, resolving);
  }

  /**
   * Run `key` (always a fresh execution — an explicit refresh or a param change must hit QuerySource again),
   * serialised after any run of the same key still in flight and registered so `ensureFrame` can join it.
   */
  function runSource(key: string, forceRefresh: boolean, resolving: Set<string> = new Set()): Promise<void> {
    const previous = inFlight[key];
    // No run in flight → start synchronously (the fetch is issued before this returns, as before).
    const started = previous ? previous.then(() => execute(key, forceRefresh, resolving)) : execute(key, forceRefresh, resolving);
    const run: Promise<void> = started.finally(() => {
      if (inFlight[key] === run) delete inFlight[key];
    });
    inFlight[key] = run;
    return run;
  }

  /** A source that produced no frame takes its derived views down with it (Python: `data_stage` propagation). */
  function reportDerivedFailed(key: string, resolving: Set<string>): void {
    for (const d of derivedOf(key)) {
      if (resolving.has(d)) continue;
      opts.onUpdate({ key: d, rows: null, status: 'error', snapshotAt: lastSnapshotAt[d] });
      reportDerivedFailed(d, resolving);
    }
  }

  async function execute(key: string, forceRefresh: boolean, resolving: Set<string>): Promise<void> {
    const src = sources[key];
    if (!src) return;
    if (resolving.has(key) || failed.has(key)) {
      // A real cycle, or a sibling reference that names nothing: never fetch, never blank the
      // snapshot — just report the error (TS twin of the Python executor's failed-source outcome).
      opts.onUpdate({ key, rows: null, status: 'error', snapshotAt: lastSnapshotAt[key] });
      return;
    }
    resolving.add(key);
    opts.onUpdate({ key, rows: null, status: 'loading', snapshotAt: null });
    let ready = false;
    try {
      for (const ref of deps[key]) {
        if (ref in sources) await ensureFrame(ref, resolving);
      }
      let rows: Row[];
      if (isQuerySlug(src)) {
        const placeholders = { ...(src.request.placeholders ?? {}), ...(overrides[key] ?? {}) };
        const request = { ...src.request, placeholders };
        const conditions: Record<string, unknown> = deriveConditions(request, lockedValues(src));
        if (forceRefresh) conditions.refresh = true;
        const rawRows = await fetchSource(src, conditions, { baseUrl: opts.baseUrl, headers: opts.headers() });
        rows = rawRows;
        if (src.transform?.ops) {
          rows = applyTransform(rawRows, src.transform, frames);
        } else if (src.transform?.ref) {
          const transformFn = await loadRef(src.transform.ref, { transformsBase: opts.transformsBase });
          // AC9: an SRI mismatch / unknown ref never executes — the raw fetched snapshot stands.
          rows = transformFn ? transformFn(rawRows) : rawRows;
        }
      } else {
        // Derived: the parent's FULL frame (never its ≤500-row snapshot) through the DSL; a parent that failed
        // to produce a frame leaves this view on its last snapshot with an 'error' status (Python: data_stage).
        const base = frames[src.from];
        if (base === undefined) throw new TransformError(`parent source '${src.from}' has no frame`, key, 0);
        rows = applyTransform(base, src.transform, frames);
      }
      frames[key] = rows;
      const stamp = new Date().toISOString();
      lastSnapshotAt[key] = stamp;
      opts.onUpdate({ key, rows, status: 'ready', snapshotAt: stamp });
      ready = true;
    } catch (err) {
      // A 404 (SourceUnavailable) is the only outcome the UI must word differently ("unavailable",
      // never "denied" — AC10); every other failure (a TransformError from `applyTransform`, a
      // FrameSelectionError from `fetchSource` (missing/ambiguous MultiQuery frame, §9 S7), a
      // network error, …) reports the same generic 'error' status — the snapshot is never blanked
      // either way (rows stays null).
      const status: SourceStatus = err instanceof SourceUnavailable ? 'unavailable' : 'error';
      opts.onUpdate({ key, rows: null, status, snapshotAt: lastSnapshotAt[key] });
    } finally {
      resolving.delete(key);
    }
    if (!ready) {
      reportDerivedFailed(key, resolving);
      return;
    }
    // Cascade: every derived view of this key is recomputed from the fresh frame (sequential, descriptor order).
    for (const d of derivedOf(key)) {
      if (resolving.has(d)) continue; // `d` is the one that asked for this frame (ensureFrame) — it continues itself
      delete frames[d];
      await runSource(d, false, resolving);
    }
  }

  return {
    start() {
      for (const key of Object.keys(sources)) {
        if (failed.has(key)) {
          opts.onUpdate({ key, rows: null, status: 'error', snapshotAt: lastSnapshotAt[key] });
          continue;
        }
        const src = sources[key];
        if (!isQuerySlug(src)) continue; // derived: computed by the parent's cascade, never scheduled
        const scheduler = new RefreshScheduler(src.refresh ?? {}, () => runSource(key, false));
        schedulers[key] = scheduler;
        scheduler.start();
      }
    },
    stop() {
      for (const scheduler of Object.values(schedulers)) scheduler.stop();
    },
    async setParam(source, name, value) {
      const src = sources[source];
      if (!src || failed.has(source)) return;
      if (!isQuerySlug(src)) {
        // Same rule as service.refresh / executor: a derived view takes no params.
        console.warn(`a2ui linked lane: ignoring param '${name}' for derived source '${source}'`);
        return;
      }
      if ((src.locked ?? []).includes(name) || !Object.prototype.hasOwnProperty.call(src.params ?? {}, name)) {
        // Same rule as executor._conditions_for (executor.py:153-177): locked or undeclared → ignored, no fetch.
        console.warn(`a2ui linked lane: ignoring param '${name}' for source '${source}' (locked or undeclared)`);
        return;
      }
      overrides[source] = { ...(overrides[source] ?? {}), [name]: value };
      delete frames[source]; // force a re-fetch even if a sibling already cached this frame
      await runSource(source, false);
    },
    async refreshAll() {
      // Sequential, in dependency order — a single deterministic pass, same shape as the Python
      // reference executor's `execute_sources` loop (dependencies first). Derived views are recomputed by
      // their parent's cascade, so they are skipped here.
      const { order } = executionOrder(sources, deps);
      for (const key of order) {
        if (isDerived(sources[key])) continue;
        delete frames[key];
        await runSource(key, true);
      }
    },
    getParams() {
      // A deep copy: callers (the /refresh body) must never be able to mutate lane state. Values are
      // JSON-serialisable FilterBar selections (string | string[] | null), so structuredClone is safe.
      return structuredClone(overrides);
    },
    refreshSource(key) {
      if (!(key in sources) || failed.has(key)) return Promise.resolve();
      const src = sources[key];
      if (isDerived(src)) return this.refreshSource(src.from); // a derived view refreshes through its parent
      if (refreshing[key]) return refreshing[key];

      refreshing[key] = (async () => {
        delete frames[key];
        await runSource(key, true); // the cascade recomputes this key's derived views
        const { order } = executionOrder(sources, deps);
        for (const dependent of order) {
          if (dependent !== key && !isDerived(sources[dependent]) && deps[dependent].includes(key)) {
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
