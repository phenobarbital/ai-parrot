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
