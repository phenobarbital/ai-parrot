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
});
