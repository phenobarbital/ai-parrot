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
