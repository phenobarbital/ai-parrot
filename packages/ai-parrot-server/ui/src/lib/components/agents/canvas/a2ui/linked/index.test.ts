// FEAT-610 (TASK-3844): LinkedLane per-source refresh behaviour.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createLinkedLane } from './index';
import type { LinkedDataSource, LinkedSources, Row } from './types';

const { fetchSourceMock } = vi.hoisted(() => ({
  fetchSourceMock: vi.fn(),
}));

vi.mock('./fetch', async importOriginal => {
  const actual = await importOriginal<typeof import('./fetch')>();
  return { ...actual, fetchSource: fetchSourceMock };
});

afterEach(() => vi.resetAllMocks());

function source(slug: string, overrides: Partial<LinkedDataSource> = {}): LinkedDataSource {
  return {
    conditions: {},
    request: {},
    slug,
    tenant: null,
    ...overrides,
  } as LinkedDataSource;
}

function lane(sources: LinkedSources) {
  return createLinkedLane(sources, {
    baseUrl: '',
    headers: () => ({}),
    transformsBase: '',
    onUpdate: vi.fn(),
  });
}

describe('LinkedLane.refreshSource', () => {
  it('re-fetches only that key with refresh=true', async () => {
    fetchSourceMock.mockResolvedValue([] satisfies Row[]);
    const linkedLane = lane({ alpha: source('alpha'), beta: source('beta') } as LinkedSources);

    await linkedLane.refreshSource('alpha');

    expect(fetchSourceMock).toHaveBeenCalledTimes(1);
    expect(fetchSourceMock.mock.calls[0][0].slug).toBe('alpha');
    expect(fetchSourceMock.mock.calls[0][1]).toEqual({ refresh: true });
  });

  it('is a no-op for an unknown key', async () => {
    fetchSourceMock.mockResolvedValue([] satisfies Row[]);
    const linkedLane = lane({ alpha: source('alpha') } as LinkedSources);

    await linkedLane.refreshSource('unknown');

    expect(fetchSourceMock).not.toHaveBeenCalled();
  });

  it('re-runs transform dependents after the key', async () => {
    fetchSourceMock.mockResolvedValue([] satisfies Row[]);
    const linkedLane = lane({
      base: source('base'),
      derived: source('derived', { transform: { ops: [{ op: 'union', sources: ['base'] }] } }),
    } as LinkedSources);

    await linkedLane.refreshSource('base');

    expect(fetchSourceMock.mock.calls.map(([src]) => src.slug)).toEqual(['base', 'derived']);
    expect(fetchSourceMock.mock.calls.map(([, conditions]) => conditions)).toEqual([
      { refresh: true },
      { refresh: true },
    ]);
  });

  it('dedups concurrent calls for the same key', async () => {
    let resolveFetch: (rows: Row[]) => void;
    fetchSourceMock.mockImplementation(
      () =>
        new Promise<Row[]>(resolve => {
          resolveFetch = resolve;
        }),
    );
    const linkedLane = lane({ alpha: source('alpha') } as LinkedSources);

    const first = linkedLane.refreshSource('alpha');
    const second = linkedLane.refreshSource('alpha');
    expect(first).toBe(second);
    expect(fetchSourceMock).toHaveBeenCalledTimes(1);

    resolveFetch!([]);
    await Promise.all([first, second]);
  });

  it('refreshAll still fetches every source in order', async () => {
    fetchSourceMock.mockResolvedValue([] satisfies Row[]);
    const linkedLane = lane({ beta: source('beta'), alpha: source('alpha') } as LinkedSources);

    await linkedLane.refreshAll();

    expect(fetchSourceMock.mock.calls.map(([src]) => src.slug)).toEqual(['beta', 'alpha']);
    expect(fetchSourceMock.mock.calls.map(([, conditions]) => conditions)).toEqual([
      { refresh: true },
      { refresh: true },
    ]);
  });
});

// Linked dashboards: dashboard-owned sources shared by widgets + `kind: "derived"` views.
const ROWS: Row[] = [
  { program: 'epson', visits: 10 },
  { program: 'pokemon', visits: 20 },
  { program: 'epson', visits: 30 },
];

function derived(from: string, ops: unknown[] = [{ op: 'group_by', by: ['program'], aggregate: { visits: 'sum' } }]) {
  return { kind: 'derived', from, transform: { ops }, target: `/${from}_view/rows` } as unknown as LinkedDataSource;
}

function dashboard() {
  const updates: Array<{ key: string; status: string; rows: Row[] | null }> = [];
  const sources = {
    by_program: derived('rows'),
    rows: source('rows', { kind: 'query_slug', refresh: { policy: 'on_mount' } } as Partial<LinkedDataSource>),
    top: derived('by_program', [{ op: 'limit', n: 1 }]),
  } as unknown as LinkedSources;
  const linkedLane = createLinkedLane(sources, {
    baseUrl: '',
    headers: () => ({}),
    transformsBase: '',
    onUpdate: (u) => updates.push({ key: u.key, status: u.status, rows: u.rows }),
  });
  return { linkedLane, updates };
}

const ready = (updates: Array<{ key: string; status: string; rows: Row[] | null }>) =>
  updates.filter((u) => u.status === 'ready');

describe('LinkedLane derived sources', () => {
  it('fetches the parent ONCE on mount and computes every derived view from its full frame', async () => {
    fetchSourceMock.mockResolvedValue(ROWS);
    const { linkedLane, updates } = dashboard();

    linkedLane.start();
    await vi.waitFor(() => expect(ready(updates).map((u) => u.key)).toEqual(['rows', 'by_program', 'top']));

    expect(fetchSourceMock).toHaveBeenCalledTimes(1);
    expect(ready(updates)[1].rows).toEqual([
      { program: 'epson', visits: 40 },
      { program: 'pokemon', visits: 20 },
    ]);
    expect(ready(updates)[2].rows).toEqual([{ program: 'epson', visits: 40 }]);
    linkedLane.stop();
  });

  it('refreshSource(parent) re-fetches once and recomputes the derived chain; refreshSource(derived) refreshes the parent', async () => {
    fetchSourceMock.mockResolvedValue(ROWS);
    const { linkedLane, updates } = dashboard();

    await linkedLane.refreshSource('rows');
    expect(fetchSourceMock).toHaveBeenCalledTimes(1);
    expect(fetchSourceMock.mock.calls[0][1]).toEqual({ refresh: true });
    expect(ready(updates).map((u) => u.key)).toEqual(['rows', 'by_program', 'top']);

    updates.length = 0;
    await linkedLane.refreshSource('top');
    expect(fetchSourceMock).toHaveBeenCalledTimes(2);
    expect(ready(updates).map((u) => u.key)).toEqual(['rows', 'by_program', 'top']);
  });

  it('refreshAll fetches only query-slug sources; derived views follow through the cascade', async () => {
    fetchSourceMock.mockResolvedValue(ROWS);
    const { linkedLane, updates } = dashboard();

    await linkedLane.refreshAll();

    expect(fetchSourceMock).toHaveBeenCalledTimes(1);
    expect(ready(updates).map((u) => u.key)).toEqual(['rows', 'by_program', 'top']);
  });

  it('setParam on a derived key is a no-op and getParams never lists derived keys', async () => {
    fetchSourceMock.mockResolvedValue(ROWS);
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { linkedLane } = dashboard();

    await linkedLane.setParam('by_program', 'firstdate', '2026-01-01');

    expect(fetchSourceMock).not.toHaveBeenCalled();
    expect(linkedLane.getParams()).toEqual({});
  });

  it('a parent failure leaves every derived view on its snapshot with status error', async () => {
    fetchSourceMock.mockRejectedValue(new Error('network'));
    const { linkedLane, updates } = dashboard();

    await linkedLane.refreshSource('rows');

    const errors = updates.filter((u) => u.status === 'error');
    expect(errors.map((u) => u.key).sort()).toEqual(['by_program', 'rows', 'top']);
    expect(errors.every((u) => u.rows === null)).toBe(true);
    expect(ready(updates)).toEqual([]);
  });

  it('a derived transform error is isolated: the parent stays ready', async () => {
    fetchSourceMock.mockResolvedValue(ROWS);
    const sources = {
      rows: source('rows'),
      bad: derived('rows', [{ op: 'select', columns: ['missing'] }]),
    } as unknown as LinkedSources;
    const updates: Array<{ key: string; status: string }> = [];
    const linkedLane = createLinkedLane(sources, {
      baseUrl: '',
      headers: () => ({}),
      transformsBase: '',
      onUpdate: (u) => updates.push({ key: u.key, status: u.status }),
    });

    await linkedLane.refreshSource('rows');

    expect(updates.filter((u) => u.status === 'ready').map((u) => u.key)).toEqual(['rows']);
    expect(updates.filter((u) => u.status === 'error').map((u) => u.key)).toEqual(['bad']);
  });

  it('a descriptor without `kind` is still a query-slug source', async () => {
    fetchSourceMock.mockResolvedValue(ROWS);
    const linkedLane = lane({ legacy: source('legacy') } as LinkedSources);

    await linkedLane.refreshSource('legacy');

    expect(fetchSourceMock).toHaveBeenCalledTimes(1);
  });
});

// Adversarial topologies: a dependent that joins a parent whose cascade waits on that dependent, derived views
// that join siblings, dependents declared before their parents, failing parents shared by several dependents.
function joinOps(withKey: string) {
  return { ops: [{ op: 'join', with: withKey, how: 'left', on: [{ left: 'k', right: 'k' }] }] };
}

function recorder() {
  const updates: Array<{ key: string; status: string; rows: Row[] | null }> = [];
  const opts = {
    baseUrl: '',
    headers: () => ({}),
    transformsBase: '',
    onUpdate: (u: { key: string; status: string; rows: Row[] | null }) => updates.push({ key: u.key, status: u.status, rows: u.rows }),
  };
  const readyKeys = () => updates.filter((u) => u.status === 'ready').map((u) => u.key);
  const latest = (key: string) => updates.filter((u) => u.status === 'ready' && u.key === key).at(-1)?.rows;
  return { updates, opts, readyKeys, latest };
}

const withTimeout = <T,>(p: Promise<T>, ms = 500) =>
  Promise.race([p, new Promise<never>((_, reject) => setTimeout(() => reject(new Error(`timed out after ${ms}ms`)), ms))]);

describe('LinkedLane dependency graphs', () => {
  it('never deadlocks when a query-slug source joins a derived view of a source whose cascade waits on it', async () => {
    // P (query) → D (derived from P); J (query) joins D. Mount: P and J are scheduled, D is computed by P's cascade.
    fetchSourceMock.mockImplementation(async (src: LinkedDataSource) => [{ k: 1, v: src.slug }]);
    const { opts, readyKeys, latest } = recorder();
    const sources = {
      P: source('P', { refresh: { policy: 'on_mount' } } as Partial<LinkedDataSource>),
      J: source('J', { refresh: { policy: 'on_mount' }, transform: joinOps('D') } as Partial<LinkedDataSource>),
      D: derived('P', [{ op: 'rename', mapping: { v: 'pv' } }]),
    } as unknown as LinkedSources;
    const linkedLane = createLinkedLane(sources, opts);

    linkedLane.start();
    await withTimeout(vi.waitFor(() => expect([...new Set(readyKeys())].sort()).toEqual(['D', 'J', 'P'])));

    expect(fetchSourceMock).toHaveBeenCalledTimes(2); // P once, J once
    expect(latest('J')).toEqual([{ k: 1, v: 'J', pv: 'P' }]);
    linkedLane.stop();
  });

  it('never deadlocks when a derived view joins a query-slug sibling that itself joins the parent', async () => {
    // P, Q (joins P), D (derived from P, joins Q)
    fetchSourceMock.mockImplementation(async (src: LinkedDataSource) => [{ k: 1, v: src.slug }]);
    const { opts, readyKeys } = recorder();
    const sources = {
      P: source('P', { refresh: { policy: 'on_mount' } } as Partial<LinkedDataSource>),
      Q: source('Q', { refresh: { policy: 'on_mount' }, transform: joinOps('P') } as Partial<LinkedDataSource>),
      D: derived('P', [{ op: 'join', with: 'Q', how: 'left', on: [{ left: 'k', right: 'k' }] }]),
    } as unknown as LinkedSources;
    const linkedLane = createLinkedLane(sources, opts);

    linkedLane.start();
    await withTimeout(vi.waitFor(() => expect([...new Set(readyKeys())].sort()).toEqual(['D', 'P', 'Q'])));

    expect(fetchSourceMock).toHaveBeenCalledTimes(2);
    linkedLane.stop();
  });

  it('recomputes a derived view when a sibling it joins changes, and never serves a stale joined frame', async () => {
    let qVersion = 0;
    fetchSourceMock.mockImplementation(async (src: LinkedDataSource) =>
      src.slug === 'Q' ? [{ k: 1, qv: ++qVersion }] : [{ k: 1, v: 'P' }],
    );
    const { opts, latest } = recorder();
    const sources = {
      P: source('P'),
      Q: source('Q'),
      D: derived('P', [{ op: 'join', with: 'Q', how: 'left', on: [{ left: 'k', right: 'k' }] }]),
    } as unknown as LinkedSources;
    const linkedLane = createLinkedLane(sources, opts);

    await linkedLane.refreshAll();
    expect(latest('D')).toEqual([{ k: 1, v: 'P', qv: 1 }]);
    await linkedLane.refreshSource('Q');
    expect(latest('D')).toEqual([{ k: 1, v: 'P', qv: 2 }]);
    await linkedLane.refreshAll();
    expect(latest('D')).toEqual([{ k: 1, v: 'P', qv: 3 }]);
    expect(fetchSourceMock).toHaveBeenCalledTimes(5); // P×2 (refreshAll×2) + Q×3
  });

  it('a derived view declared before the derived sibling it joins sees the fresh sibling after a parent refresh', async () => {
    let pVersion = 0;
    fetchSourceMock.mockImplementation(async () => [{ k: 1, pv: ++pVersion }]);
    const { opts, latest } = recorder();
    const sources = {
      P: source('P'),
      D: derived('P', [{ op: 'join', with: 'Q', how: 'left', on: [{ left: 'k', right: 'k' }] }]),
      Q: derived('P', [{ op: 'rename', mapping: { pv: 'qv' } }]),
    } as unknown as LinkedSources;
    const linkedLane = createLinkedLane(sources, opts);

    await linkedLane.refreshSource('P');
    expect(latest('D')).toEqual([{ k: 1, pv: 1, qv: 1 }]);
    await linkedLane.refreshSource('P');
    expect(latest('D')).toEqual([{ k: 1, pv: 2, qv: 2 }]);
    expect(fetchSourceMock).toHaveBeenCalledTimes(2);
  });

  it('fetches a parent once on mount even when its dependent is declared first', async () => {
    fetchSourceMock.mockImplementation(async (src: LinkedDataSource) => [{ k: 1, v: src.slug }]);
    const { opts, readyKeys } = recorder();
    const sources = {
      J: source('J', { refresh: { policy: 'on_mount' }, transform: joinOps('P') } as Partial<LinkedDataSource>),
      P: source('P', { refresh: { policy: 'on_mount' } } as Partial<LinkedDataSource>),
    } as unknown as LinkedSources;
    const linkedLane = createLinkedLane(sources, opts);

    linkedLane.start();
    await withTimeout(vi.waitFor(() => expect([...new Set(readyKeys())].sort()).toEqual(['J', 'P'])));

    expect(fetchSourceMock.mock.calls.map(([src]) => src.slug)).toEqual(['P', 'J']);
    linkedLane.stop();
  });

  it('a failing parent is fetched once per pass however many dependents join it', async () => {
    fetchSourceMock.mockImplementation(async (src: LinkedDataSource) => {
      if (src.slug === 'P') throw new Error('boom');
      return [{ k: 1 }];
    });
    const { opts, updates } = recorder();
    const sources = {
      P: source('P', { refresh: { policy: 'on_mount' } } as Partial<LinkedDataSource>),
      A: source('A', { refresh: { policy: 'on_mount' }, transform: joinOps('P') } as Partial<LinkedDataSource>),
      B: source('B', { refresh: { policy: 'on_mount' }, transform: joinOps('P') } as Partial<LinkedDataSource>),
      D: derived('P'),
    } as unknown as LinkedSources;
    const linkedLane = createLinkedLane(sources, opts);

    linkedLane.start();
    await withTimeout(
      vi.waitFor(() => expect(updates.filter((u) => u.status === 'error').map((u) => u.key).sort()).toEqual(['A', 'B', 'D', 'P'])),
    );

    expect(fetchSourceMock.mock.calls.filter(([src]) => src.slug === 'P')).toHaveLength(1);
    linkedLane.stop();
  });
});
