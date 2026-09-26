// FEAT-598 (TASK-3794): fetchSource URL rule, 404 → SourceUnavailable, refresh boolean, querylimit (AC4/AC10/AC17).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchSource, SourceUnavailable } from './fetch';
import type { LinkedDataSource } from './types';

afterEach(() => vi.restoreAllMocks());

function makeSource(overrides: Partial<LinkedDataSource> = {}): LinkedDataSource {
  return {
    conditions: {},
    request: {},
    slug: 'sales_by_region',
    tenant: null,
    ...overrides,
  } as LinkedDataSource;
}

describe('fetchSource', () => {
  it('posts to /api/v3/queries/{slug} with querylimit when tenant is null', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([{ a: 1 }])));
    const src = makeSource();
    const rows = await fetchSource(src, { region: 'east' }, {
      baseUrl: '',
      headers: { Authorization: 'Bearer tok123' },
    });
    expect(spy).toHaveBeenCalledTimes(1);
    const [url, init] = spy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v3/queries/sales_by_region');
    expect(init.method).toBe('POST');
    expect(init.headers).toEqual({ Authorization: 'Bearer tok123' });
    const body = JSON.parse(init.body as string);
    expect(body.querylimit).toBe(5000);
    expect(body.region).toBe('east');
    expect(rows).toEqual([{ a: 1 }]);
  });

  it('routes to /api/v1/{tenant}/queries/{slug} when source.tenant is set', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([])));
    const src = makeSource({ tenant: 'acme' });
    await fetchSource(src, {}, { baseUrl: '', headers: {} });
    const [url] = spy.mock.calls[0] as [string];
    expect(url).toBe('/api/v1/acme/queries/sales_by_region');
  });

  it('maps a 404 to SourceUnavailable, never "denied"', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('not found', { status: 404 }));
    const src = makeSource();
    await expect(fetchSource(src, {}, { baseUrl: '', headers: {} })).rejects.toBeInstanceOf(SourceUnavailable);
  });

  it('propagates non-404 HTTP errors unchanged', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('boom', { status: 500 }));
    const src = makeSource();
    await expect(fetchSource(src, {}, { baseUrl: '', headers: {} })).rejects.not.toBeInstanceOf(SourceUnavailable);
  });

  it('drops refresh unless it is exactly boolean true', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify([])));
    const src = makeSource();
    await fetchSource(src, { refresh: 'true' }, { baseUrl: '', headers: {} });
    let body = JSON.parse((spy.mock.calls[0] as [string, RequestInit])[1].body as string);
    expect(body).not.toHaveProperty('refresh');

    spy.mockClear();
    await fetchSource(src, { refresh: 1 }, { baseUrl: '', headers: {} });
    body = JSON.parse((spy.mock.calls[0] as [string, RequestInit])[1].body as string);
    expect(body).not.toHaveProperty('refresh');

    spy.mockClear();
    await fetchSource(src, { refresh: true }, { baseUrl: '', headers: {} });
    body = JSON.parse((spy.mock.calls[0] as [string, RequestInit])[1].body as string);
    expect(body.refresh).toBe(true);
  });

  it('caps querylimit at maxFetchRows even when request.limit is larger', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([])));
    const src = makeSource({ request: { limit: 9000 } as never });
    await fetchSource(src, {}, { baseUrl: '', headers: {}, maxFetchRows: 100 });
    const body = JSON.parse((spy.mock.calls[0] as [string, RequestInit])[1].body as string);
    expect(body.querylimit).toBe(100);
  });

  it('selects the multi_output frame from a keyed MultiQuery payload', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ totals: [{ n: 1 }], detail: [{ n: 2 }] })),
    );
    const src = makeSource({ multi_output: 'detail' } as never);
    const rows = await fetchSource(src, {}, { baseUrl: '', headers: {} });
    expect(rows).toEqual([{ n: 2 }]);
  });

  it("falls back to the 'result' key when multi_output is unset", async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ result: [{ n: 3 }], other: [{ n: 4 }] })),
    );
    const src = makeSource();
    const rows = await fetchSource(src, {}, { baseUrl: '', headers: {} });
    expect(rows).toEqual([{ n: 3 }]);
  });

  it('falls back to the sole frame when there is exactly one and no result/multi_output key', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ only_frame: [{ n: 5 }] })));
    const src = makeSource();
    const rows = await fetchSource(src, {}, { baseUrl: '', headers: {} });
    expect(rows).toEqual([{ n: 5 }]);
  });

  it('exports SourceUnavailable', () => expect(new SourceUnavailable('x').name).toBe('SourceUnavailable'));
});
