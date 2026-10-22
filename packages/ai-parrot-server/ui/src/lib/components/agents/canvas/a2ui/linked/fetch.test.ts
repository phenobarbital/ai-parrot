// FEAT-598 (TASK-3794): fetchSource URL rule (v2 QS by default, v3 MultiQS only for is_multiquery, v1 tenant),
// 404 → SourceUnavailable, 204 → [], refresh boolean, querylimit (AC4/AC10/AC17).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FrameSelectionError, fetchSource, fetchSourceData, SourceUnavailable } from './fetch';
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
  it('posts to /api/v2/services/queries/{slug} (plain QS, never MultiQS) with querylimit when tenant is null', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([{ a: 1 }])));
    const src = makeSource();
    const rows = await fetchSource(src, { region: 'east' }, {
      baseUrl: '',
      headers: { Authorization: 'Bearer tok123' },
    });
    expect(spy).toHaveBeenCalledTimes(1);
    const [url, init] = spy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v2/services/queries/sales_by_region');
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

  it('routes to /api/v3/queries/{slug} (MultiQS) only when is_multiquery is true', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify([])));
    await fetchSource(makeSource({ is_multiquery: true } as never), {}, { baseUrl: '', headers: {} });
    expect((spy.mock.calls[0] as [string])[0]).toBe('/api/v3/queries/sales_by_region');

    spy.mockClear();
    await fetchSource(makeSource({ is_multiquery: false } as never), {}, { baseUrl: '', headers: {} });
    expect((spy.mock.calls[0] as [string])[0]).toBe('/api/v2/services/queries/sales_by_region');
  });

  it('the tenant route wins over is_multiquery (kind-aware tenant handler)', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([])));
    await fetchSource(makeSource({ tenant: 'acme', is_multiquery: true } as never), {}, { baseUrl: '', headers: {} });
    expect((spy.mock.calls[0] as [string])[0]).toBe('/api/v1/acme/queries/sales_by_region');
  });

  it('treats a 204 Empty Result as zero rows, not an error', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }));
    const rows = await fetchSource(makeSource(), {}, { baseUrl: '', headers: {} });
    expect(rows).toEqual([]);
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

  it('throws FrameSelectionError when multi_output names a missing frame', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ totals: [{ n: 1 }], detail: [{ n: 2 }] })),
    );
    const src = makeSource({ multi_output: 'zzz' } as never);
    const err = await fetchSource(src, {}, { baseUrl: '', headers: {} }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(FrameSelectionError);
    expect((err as FrameSelectionError).name).toBe('FrameSelectionError');
    expect((err as FrameSelectionError).message).toContain("no output named 'zzz' (available: detail, totals)");
  });

  it('throws FrameSelectionError when multi_output is not result against a bare-array payload', async () => {
    // A bare array is the single `result` frame (Python wraps a bare DataFrame the same way).
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([{ n: 1 }])));
    const src = makeSource({ multi_output: 'detail' } as never);
    await expect(fetchSource(src, {}, { baseUrl: '', headers: {} })).rejects.toBeInstanceOf(FrameSelectionError);
  });

  it('throws FrameSelectionError on several frames with no result/multi_output', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ b: [{ n: 1 }], a: [{ n: 2 }] })));
    const src = makeSource();
    await expect(fetchSource(src, {}, { baseUrl: '', headers: {} })).rejects.toThrow(
      /returned multiple outputs \(a, b\); specify multi_output/,
    );
  });

  it('an empty keyed payload or null yields [] (no error)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({})));
    expect(await fetchSource(makeSource({ multi_output: 'x' } as never), {}, { baseUrl: '', headers: {} })).toEqual([]);
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response('null'));
    expect(await fetchSource(makeSource(), {}, { baseUrl: '', headers: {} })).toEqual([]);
  });

  it('exports SourceUnavailable', () => expect(new SourceUnavailable('x').name).toBe('SourceUnavailable'));
});

describe('fetchSourceData', () => {
  it('POSTs {params} to the surface source endpoint, appends ?share=, returns body.rows', async () => {
    const spy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify({ status: 'success', rows: [{ a: 1 }] })));
    const rows = await fetchSourceData(makeSource(), 'sales', { region: 'e' }, {
      surfaceBaseUrl: 'http://h',
      surfaceId: 's1',
      shareToken: 'tok',
      headers: { Authorization: 'Bearer x' },
    });
    expect(rows).toEqual([{ a: 1 }]);
    const [url, init] = spy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://h/api/v1/ui/surfaces/s1/sources/sales/data?share=tok');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ params: { region: 'e' } });
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer x');
  });

  it('omits ?share= when no token and maps 404 to SourceUnavailable', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('nf', { status: 404 }));
    await expect(
      fetchSourceData(makeSource(), 'sales', {}, { surfaceBaseUrl: '', surfaceId: 's1', headers: {} }),
    ).rejects.toBeInstanceOf(SourceUnavailable);
    expect((spy.mock.calls[0] as [string])[0]).toBe('/api/v1/ui/surfaces/s1/sources/sales/data');
  });

  it('other failures throw with the body code; missing rows yield []', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify({ status: 'error', code: 'boom' }), { status: 500 }),
    );
    await expect(
      fetchSourceData(makeSource(), 'sales', {}, { surfaceBaseUrl: '', surfaceId: 's1', headers: {} }),
    ).rejects.toThrow(/boom/);
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ status: 'success' })));
    expect(
      await fetchSourceData(makeSource(), 'sales', {}, { surfaceBaseUrl: '', surfaceId: 's1', headers: {} }),
    ).toEqual([]);
  });
});
