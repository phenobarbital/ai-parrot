// ai-parrot (FEAT-527): InfographicCanvas's a2ui-mode Rendered/HTML toggle.
import { render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it, vi } from 'vitest';

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

import * as tabManager from './canvas-tab-manager.svelte.js';
import InfographicCanvas from './InfographicCanvas.svelte';

const envelope = {
  version: 'v1.0' as const,
  createSurface: {
    surfaceId: 'infographic-a',
    components: [{ id: 'root', component: 'Infographic', title: 'Q1 Report', sections: [] }],
  },
};

function openA2uiTab(overrides: Record<string, unknown> = {}) {
  tabManager.resetCanvas();
  tabManager.initCanvas();
  const id = tabManager.addTab('infographic', 'Infographic (basic)', {
    mode: 'a2ui',
    envelope,
    url: 'https://x/a.html',
    template: 'basic',
    theme: 'light',
    ...overrides,
  });
  tabManager.setActiveTab(id);
}

describe('InfographicCanvas — a2ui mode', () => {
  it('renders A2UISurface by default (Rendered view)', async () => {
    openA2uiTab();
    render(InfographicCanvas, { data: null });
    expect(await screen.findByText('Q1 Report', {}, { timeout: 3000 })).toBeInTheDocument();
  });

  it('toggles to the HTML iframe view', async () => {
    openA2uiTab({ html: '<html><body>hi</body></html>' });
    render(InfographicCanvas, { data: null });
    await screen.findByText('Q1 Report', {}, { timeout: 3000 });

    const htmlButton = screen.getByRole('button', { name: 'HTML' });
    expect(htmlButton).not.toBeDisabled();
    htmlButton.click();
    await tick();

    const iframe = document.querySelector('iframe') as HTMLIFrameElement;
    expect(iframe).toBeTruthy();
    expect(iframe.getAttribute('srcdoc')).toBe('<html><body>hi</body></html>');
    // Code-review regression guard: srcdoc content must NOT carry
    // allow-same-origin — combined with allow-scripts that would let the
    // framed (agent/LLM-produced) HTML inherit this page's own origin.
    expect(iframe.getAttribute('sandbox')).toBe('allow-scripts allow-modals allow-popups');
  });

  it('falls back to the url iframe when no inline html is present', async () => {
    openA2uiTab({ html: undefined, url: 'https://x/a.html' });
    render(InfographicCanvas, { data: null });
    await screen.findByText('Q1 Report', {}, { timeout: 3000 });

    screen.getByRole('button', { name: 'HTML' }).click();
    await tick();
    const iframe = document.querySelector('iframe') as HTMLIFrameElement;
    expect(iframe.getAttribute('src')).toBe('https://x/a.html');
  });

  it('disables the HTML button when neither html nor url are present', async () => {
    openA2uiTab({ html: undefined, url: undefined });
    render(InfographicCanvas, { data: null });
    await screen.findByText('Q1 Report', {}, { timeout: 3000 });
    expect(screen.getByRole('button', { name: 'HTML' })).toBeDisabled();
  });

  it('passes persistedSurfaceId to A2UISurface (server-lane Refresh shown only then)', async () => {
    // Linked surface (one `sales` source, manual refresh — the lane never calls fetch).
    const linked = {
      version: 'v1.0' as const,
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
                refresh: { policy: 'manual' },
              },
            },
          },
        },
      },
    };

    openA2uiTab({ envelope: linked, persistedSurfaceId: 'srf-1' });
    const first = render(InfographicCanvas, { data: null });
    expect(await screen.findByRole('button', { name: 'Refresh' }, { timeout: 3000 })).toBeInTheDocument();
    first.unmount();

    openA2uiTab({ envelope: linked });
    render(InfographicCanvas, { data: null });
    await screen.findByText('hi', {}, { timeout: 3000 });
    expect(screen.queryByRole('button', { name: 'Refresh' })).toBeNull();
  });

  it('still falls back to the url iframe when html is an empty string', async () => {
    // Code-review regression guard: the previous ternary short-circuited to
    // `false` whenever `html === ''` (as opposed to `undefined`), dropping
    // the `url` fallback entirely even though a valid url was present.
    openA2uiTab({ html: '', url: 'https://x/a.html' });
    render(InfographicCanvas, { data: null });
    await screen.findByText('Q1 Report', {}, { timeout: 3000 });

    const htmlButton = screen.getByRole('button', { name: 'HTML' });
    expect(htmlButton).not.toBeDisabled();
    htmlButton.click();
    await tick();
    const iframe = document.querySelector('iframe') as HTMLIFrameElement;
    expect(iframe.getAttribute('src')).toBe('https://x/a.html');
  });
});
