// FEAT-598 (TASK-3795): the bundled lane — on_mount fetch with bearer, 404 keeps snapshot + "unavailable",
// loading while snapshot_at is null, manual never fetches, baked surfaces never fetch (AC10/AC11/AC16).
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

const { features } = vi.hoisted(() => ({
  features: {
    voice: false,
    avatar: false,
    maps: false,
    charts: true,
    canvas: true,
    infographic: true,
    datasets: false,
    richEditor: false,
    a2ui: true,
  },
}));
vi.mock('$lib/features', () => ({ features }));

import A2UISurface from './A2UISurface.svelte';
import type { A2UIEnvelope } from './a2ui-types';

/** One linked surface, one `sales` source bound at `/sales` (spec §2 Data Models). */
function envelopeWithSource(sourceOverrides: Record<string, unknown> = {}): A2UIEnvelope {
  return {
    version: 'v1.0',
    createSurface: {
      surfaceId: 's1',
      components: [{ id: 'root', component: 'Text', text: 'hi' }],
      dataModel: {},
      metadata: {
        extensions: {
          parrot_data_sources: {
            sales: {
              kind: 'query_slug',
              slug: 'sales_by_region',
              tenant: null,
              is_multiquery: false,
              conditions: {},
              request: {},
              params: {},
              locked: [],
              target: '/sales',
              refresh: { policy: 'on_mount' },
              ...sourceOverrides,
            },
          },
        },
      },
    },
  };
}

/** Root = Column[FilterBar(region → sales.region), DataTable(/sales/rows)] over one `sales` source. */
function filterTableEnvelope(
  sourceOverrides: Record<string, unknown> = {},
  dataModel: Record<string, unknown> = {},
): A2UIEnvelope {
  return {
    version: 'v1.0',
    createSurface: {
      surfaceId: 'ft-1',
      components: [
        {
          id: 'root',
          component: 'Column',
          // Inline child descriptors (A2UINode renders them); the wire type only declares id refs.
          children: [
            {
              component: 'FilterBar',
              properties: {
                filters: [
                  {
                    column: 'region',
                    label: 'Region',
                    options: [
                      { label: 'East', value: 'east' },
                      { label: 'West', value: 'west' },
                    ],
                    param: { source: 'sales', name: 'region' },
                  },
                ],
              },
            },
            {
              component: 'DataTable',
              properties: { columns: [{ name: 'region', title: 'Region' }], data: { path: '/sales/rows' } },
            },
          ] as unknown as string[],
        },
      ],
      dataModel,
      metadata: {
        extensions: {
          parrot_data_sources: {
            sales: {
              kind: 'query_slug',
              slug: 'sales_by_region',
              tenant: null,
              is_multiquery: false,
              conditions: {},
              request: {},
              params: { region: {} },
              locked: [],
              target: '/sales',
              refresh: { policy: 'on_mount' },
              ...sourceOverrides,
            },
          },
        },
      },
    },
  };
}

/** A fetch mock routed by URL: `/refresh` → `refresh()`, anything else (QuerySource) → `qs()`; fresh Responses. */
function routeFetch(qs: () => Response, refresh: () => Response = () => new Response('{}')) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    return url.includes('/refresh') ? refresh() : qs();
  });
}

function callsTo(spy: ReturnType<typeof routeFetch>, fragment: string): [string, RequestInit][] {
  return (spy.mock.calls as [string, RequestInit][]).filter(([url]) => String(url).includes(fragment));
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('A2UISurface linked lane', () => {
  it('never fetches for a baked surface', () => {
    const spy = vi.spyOn(globalThis, 'fetch');
    render(A2UISurface, {
      envelope: { version: 'v1.0', createSurface: { surfaceId: 's', components: [{ id: 'root', component: 'Text', text: 'hi' }] } },
    });
    expect(spy).not.toHaveBeenCalled();
  });

  it('fetches once on mount with the viewer bearer (Authorization header)', async () => {
    localStorage.setItem('ai_parrot_token', 'tok-abc');
    const spy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify([{ region: 'east', total: 1 }])));
    render(A2UISurface, { envelope: envelopeWithSource() });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    const [, init] = spy.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok-abc');
  });

  it('a 404 keeps the snapshot and shows "unavailable", never "denied"', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('not found', { status: 404 }));
    render(A2UISurface, { envelope: envelopeWithSource() });
    await waitFor(() => expect(screen.getByText(/unavailable/i)).toBeInTheDocument());
    expect(screen.queryByText(/denied/i)).not.toBeInTheDocument();
  });

  it('shows a loading notice while snapshot_at is null', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => new Promise(() => {})); // never resolves
    render(A2UISurface, { envelope: envelopeWithSource() });
    await waitFor(() => expect(screen.getByText(/loading/i)).toBeInTheDocument());
  });

  it('a manual refresh policy never auto-fetches', async () => {
    const spy = vi.spyOn(globalThis, 'fetch');
    render(A2UISurface, { envelope: envelopeWithSource({ refresh: { policy: 'manual' } }) });
    // Give any (incorrect) auto-fetch a tick to happen before asserting it never did.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(spy).not.toHaveBeenCalled();
  });

  it('per-source refresh button calls refreshSource(key) once', async () => {
    const spy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify([{ region: 'east', total: 1 }])));
    render(A2UISurface, { envelope: envelopeWithSource() });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));

    await fireEvent.click(screen.getByTestId('refresh-sales'));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
  });

  it('Refresh all re-fetches every source', async () => {
    const spy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify([{ region: 'east', total: 1 }])));
    const envelope = envelopeWithSource();
    const sources = envelope.createSurface.metadata!.extensions!.parrot_data_sources!;
    sources.inventory = {
      kind: 'query_slug',
      slug: 'inventory_by_region',
      tenant: null,
      is_multiquery: false,
      conditions: {},
      request: {},
      params: {},
      locked: [],
      target: '/inventory',
      refresh: { policy: 'on_mount' },
    };
    render(A2UISurface, { envelope });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));

    await fireEvent.click(screen.getByTestId('refresh-all'));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(4));
  });

  it('a FilterBar filter with parrot_param re-fetches only that source', async () => {
    const spy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify([{ region: 'east', total: 1 }])));
    const envelope: A2UIEnvelope = {
      version: 'v1.0',
      createSurface: {
        surfaceId: 'filter-1',
        components: [
          {
            id: 'root',
            component: 'Column',
            children: [
              {
                component: 'FilterBar',
                properties: {
                  filters: [
                    {
                      column: 'region',
                      label: 'Region',
                      options: [
                        { label: 'East', value: 'east' },
                        { label: 'West', value: 'west' },
                      ],
                      param: { source: 'sales', name: 'region' },
                    },
                  ],
                },
              },
            ],
          },
        ],
        dataModel: {},
        metadata: {
          extensions: {
            parrot_data_sources: {
              sales: {
                kind: 'query_slug',
                slug: 'sales_by_region',
                tenant: null,
                is_multiquery: false,
                conditions: {},
                request: {},
                params: { region: {} },
                locked: [],
                target: '/sales',
                refresh: { policy: 'on_mount' },
              },
            },
          },
        },
      },
    };
    render(A2UISurface, { envelope });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    const checkbox = screen.getByLabelText('East') as HTMLInputElement;
    await fireEvent.click(checkbox);
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    const [, init] = spy.mock.calls[1] as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body.region).toBe('east');
  });

  it('setParam ignores undeclared and locked names (no fetch, console.warn)', async () => {
    for (const overrides of [{ params: {} }, { params: { region: {} }, locked: ['region'] }]) {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const spy = routeFetch(() => new Response(JSON.stringify([{ region: 'east' }])));
      const { unmount } = render(A2UISurface, { envelope: filterTableEnvelope(overrides) });
      await waitFor(() => expect(spy).toHaveBeenCalledTimes(1)); // the mount fetch only
      await fireEvent.click(screen.getByLabelText('East'));
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(spy).toHaveBeenCalledTimes(1);
      expect(warn).toHaveBeenCalledWith(expect.stringContaining("ignoring param 'region'"));
      unmount();
      vi.restoreAllMocks();
    }
  });

  it('error/unavailable notices fall back to the descriptor snapshot_at, not "never"', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('not found', { status: 404 }));
    render(A2UISurface, { envelope: envelopeWithSource({ snapshot_at: '2026-01-02T03:04:05Z' }) });
    await waitFor(() =>
      expect(screen.getByTestId('notice-unavailable-sales').textContent).toContain('2026-01-02T03:04:05Z'),
    );
    expect(screen.queryByText(/never/)).not.toBeInTheDocument();
  });

  it('serverRefresh posts the live params and applies the returned dataModel', async () => {
    const spy = routeFetch(
      () => new Response(JSON.stringify([{ region: 'east' }])),
      () =>
        new Response(
          JSON.stringify({
            status: 'success',
            envelope: { surfaceId: 's1', components: [], dataModel: { sales: { rows: [{ region: 'west-refreshed' }] } } },
            metadata: {},
          }),
        ),
    );
    render(A2UISurface, { envelope: filterTableEnvelope(), persistedSurfaceId: 'surf-9' });
    await waitFor(() => expect(screen.getByText('east')).toBeInTheDocument());
    await fireEvent.click(screen.getByLabelText('East'));
    await waitFor(() => expect(callsTo(spy, '/queries/')).toHaveLength(2));
    await fireEvent.click(screen.getByText('Refresh'));
    await waitFor(() => expect(screen.getByText('west-refreshed')).toBeInTheDocument());
    const refreshCalls = callsTo(spy, '/api/v1/ui/surfaces/surf-9/refresh');
    expect(refreshCalls).toHaveLength(1);
    expect(JSON.parse(refreshCalls[0][1].body as string)).toEqual({ params: { sales: { region: 'east' } } });
  });

  it('serverRefresh shows X-Parrot-Refresh-Warnings as notices', async () => {
    routeFetch(
      () => new Response(JSON.stringify([{ region: 'east' }])),
      () =>
        new Response(JSON.stringify({ status: 'success', envelope: { dataModel: {} } }), {
          headers: { 'X-Parrot-Refresh-Warnings': JSON.stringify(['source sales: ignored params ["x"]']) },
        }),
    );
    render(A2UISurface, { envelope: filterTableEnvelope(), persistedSurfaceId: 'surf-9' });
    await waitFor(() => expect(screen.getByText('east')).toBeInTheDocument());
    await fireEvent.click(screen.getByText('Refresh'));
    await waitFor(() =>
      expect(screen.getByTestId('notice-refresh-0').textContent).toBe('source sales: ignored params ["x"]'),
    );
  });

  it('a failed serverRefresh shows a notice and keeps the rows', async () => {
    routeFetch(
      () => new Response(JSON.stringify([{ region: 'east' }])),
      () =>
        new Response(JSON.stringify({ status: 'error', error: 'stale refresh', snapshot_at: 'x' }), { status: 409 }),
    );
    render(A2UISurface, { envelope: filterTableEnvelope(), persistedSurfaceId: 'surf-9' });
    await waitFor(() => expect(screen.getByText('east')).toBeInTheDocument());
    await fireEvent.click(screen.getByText('Refresh'));
    await waitFor(() => expect(screen.getByTestId('notice-refresh-0').textContent).toContain('stale refresh'));
    expect(screen.getByText('east')).toBeInTheDocument();
  });

  it('a missing multi_output frame reports error and keeps rows', async () => {
    routeFetch(() => new Response(JSON.stringify({ a: [{ region: 'from-a' }], b: [{ region: 'from-b' }] })));
    render(A2UISurface, {
      envelope: filterTableEnvelope({ multi_output: 'zzz' }, { sales: { rows: [{ region: 'seeded' }] } }),
    });
    await waitFor(() => expect(screen.getByTestId('notice-error-sales')).toBeInTheDocument());
    expect(screen.getByText('seeded')).toBeInTheDocument();
    expect(screen.queryByText('from-a')).not.toBeInTheDocument();
  });
});
