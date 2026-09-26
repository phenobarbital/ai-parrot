/**
 * Bundled-renderer executor lane (FEAT-598, spec §3 Module 11).
 * Plain TS: per-source RefreshScheduler → deriveConditions → fetchSource → applyTransform|loadRef,
 * reporting through `onUpdate`; the Svelte surface owns the reactive state.
 *
 * Dependency order (join.with / union.sources) and per-source `locked` enforcement are TS twins of
 * the Python reference executor's `_execution_order` / `_conditions_for`
 * (`parrot.outputs.a2ui.linked.executor`, spec §3 M5) — a source whose transform joins/unions
 * siblings is resolved AFTER them, lazily: whichever source runs first (mount, interval tick,
 * `setParam`, or `refreshAll`) ensures its own dependencies have a frame before it fetches, so
 * per-source `RefreshScheduler`s stay independent (no double-fetch on mount) while joins/unions
 * still see fresh sibling data.
 */
import { deriveConditions } from './conditions';
import { applyTransform, TransformError } from './dsl';
import { fetchSource, SourceUnavailable } from './fetch';
import { RefreshScheduler } from './scheduler';
import { loadRef } from './ref';
import type { LinkedDataSource, LinkedSources, Row } from './types';

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
  /** Re-fetch `source` with `name` overridden (FilterBar parrot_param). Locked names are ignored. */
  setParam(source: string, name: string, value: unknown): Promise<void>;
  /** Manual refresh of every source (policy manual / user button). */
  refreshAll(): Promise<void>;
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

/** The sibling keys a source's own transform references via `join.with` / `union.sources`. */
function dependenciesOf(source: LinkedDataSource): string[] {
  const ops = source.transform?.ops;
  if (!ops) return [];
  const refs: string[] = [];
  for (const op of ops) {
    if (op.op === 'join') refs.push((op as { with: string }).with);
    else if (op.op === 'union') refs.push(...((op as { sources: string[] }).sources));
  }
  return refs;
}

/**
 * Topological order (join.with / union.sources first) + the set of sources that can never
 * succeed (a missing sibling, or part of a dependency cycle) — TS twin of the Python reference
 * executor's `_execution_order`. Used only to proactively surface a stable 'error' status for a
 * structurally-broken descriptor; `runSource` itself resolves dependencies lazily (see below).
 */
function executionOrder(
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

export function createLinkedLane(sources: LinkedSources, opts: LinkedLaneOptions): LinkedLane {
  const deps: Record<string, string[]> = {};
  for (const key of Object.keys(sources)) deps[key] = dependenciesOf(sources[key]);
  const { failed } = executionOrder(sources, deps);

  const overrides: Record<string, Record<string, unknown>> = {};
  const frames: Record<string, Row[]> = {};
  const schedulers: Record<string, RefreshScheduler> = {};
  const inFlight: Record<string, Promise<void> | undefined> = {};

  /** Ensure `key`'s dependencies have a frame before it runs — cycle-safe via `resolving`. */
  async function ensureFrame(key: string, resolving: Set<string>): Promise<void> {
    if (frames[key] !== undefined) return;
    if (!(key in inFlight)) {
      inFlight[key] = runSource(key, false, resolving).finally(() => {
        delete inFlight[key];
      });
    }
    await inFlight[key];
  }

  async function runSource(key: string, forceRefresh: boolean, resolving: Set<string> = new Set()): Promise<void> {
    const src = sources[key];
    if (!src) return;
    if (resolving.has(key) || failed.has(key)) {
      // A real cycle, or a sibling reference that names nothing: never fetch, never blank the
      // snapshot — just report the error (TS twin of the Python executor's failed-source outcome).
      opts.onUpdate({ key, rows: null, status: 'error', snapshotAt: null });
      return;
    }
    resolving.add(key);
    opts.onUpdate({ key, rows: null, status: 'loading', snapshotAt: null });
    try {
      for (const ref of deps[key]) {
        if (ref in sources) await ensureFrame(ref, resolving);
      }
      const placeholders = { ...(src.request.placeholders ?? {}), ...(overrides[key] ?? {}) };
      const request = { ...src.request, placeholders };
      const conditions: Record<string, unknown> = deriveConditions(request, lockedValues(src));
      if (forceRefresh) conditions.refresh = true;
      const rawRows = await fetchSource(src, conditions, { baseUrl: opts.baseUrl, headers: opts.headers() });
      let rows = rawRows;
      if (src.transform?.ops) {
        rows = applyTransform(rawRows, src.transform, frames);
      } else if (src.transform?.ref) {
        const transformFn = await loadRef(src.transform.ref, { transformsBase: opts.transformsBase });
        // AC9: an SRI mismatch / unknown ref never executes — the raw fetched snapshot stands.
        rows = transformFn ? transformFn(rawRows) : rawRows;
      }
      frames[key] = rows;
      opts.onUpdate({ key, rows, status: 'ready', snapshotAt: new Date().toISOString() });
    } catch (err) {
      // A 404 (SourceUnavailable) is the only outcome the UI must word differently ("unavailable",
      // never "denied" — AC10); every other failure (a TransformError from `applyTransform`, a
      // network error, …) reports the same generic 'error' status — the snapshot is never blanked
      // either way (rows stays null).
      const status: SourceStatus = err instanceof SourceUnavailable ? 'unavailable' : 'error';
      opts.onUpdate({ key, rows: null, status, snapshotAt: null });
    } finally {
      resolving.delete(key);
    }
  }

  return {
    start() {
      for (const key of Object.keys(sources)) {
        if (failed.has(key)) {
          opts.onUpdate({ key, rows: null, status: 'error', snapshotAt: null });
          continue;
        }
        const scheduler = new RefreshScheduler(sources[key].refresh ?? {}, () => runSource(key, false));
        schedulers[key] = scheduler;
        scheduler.start();
      }
    },
    stop() {
      for (const scheduler of Object.values(schedulers)) scheduler.stop();
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
        delete frames[key];
        await runSource(key, true);
      }
    },
  };
}
