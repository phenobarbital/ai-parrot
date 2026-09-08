// ai-parrot (FEAT-527): A2UISurface / A2UIInfographic / A2UINode dispatch
// — an Infographic-rooted envelope renders title/sections-as-tabs and its
// nested KPICard/Chart/DataTable/HtmlDocument/Text/Divider components;
// unsupported/action-bearing components degrade to a visible placeholder,
// never throw.
import { render, screen } from '@testing-library/svelte';
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

import A2UISurface from './A2UISurface.svelte';
import type { A2UIEnvelope } from './a2ui-types';

const twoSectionEnvelope: A2UIEnvelope = {
  version: 'v1.0',
  createSurface: {
    surfaceId: 'infographic-abc',
    components: [
      {
        id: 'root',
        component: 'Infographic',
        title: 'Q1',
        subtitle: 'Fin',
        sections: [
          {
            heading: 'Hero',
            components: [
              { component: 'KPICard', properties: { label: 'Revenue', value: '$1.2M', trend: 'up' } },
            ],
          },
          {
            heading: 'Detail',
            text: 'Revenue grew.',
            components: [
              { component: 'HtmlDocument', properties: { title: 'Doc', srcUrl: 'https://x/doc.html' } },
            ],
          },
        ],
      },
    ],
    dataModel: {},
  },
};

describe('A2UISurface — Infographic root', () => {
  it('renders title, two tabs, a KPI and a sandboxed iframe', () => {
    render(A2UISurface, { envelope: twoSectionEnvelope });
    expect(screen.getByText('Q1')).toBeInTheDocument();
    expect(screen.getAllByRole('tab')).toHaveLength(2);
    expect(screen.getByText('Revenue')).toBeInTheDocument();
    const iframe = document.querySelector('iframe')!;
    expect(iframe.getAttribute('sandbox')).toBe('allow-scripts');
    expect(iframe.getAttribute('src')).toBe('https://x/doc.html');
  });

  it('single-section Infographic stacks without tabs', () => {
    const env: A2UIEnvelope = {
      version: 'v1.0',
      createSurface: {
        surfaceId: 'infographic-one',
        components: [
          {
            id: 'root',
            component: 'Infographic',
            title: 'T',
            sections: [{ heading: 'H', components: [{ component: 'Divider' }] }],
          },
        ],
        dataModel: {},
      },
    };
    render(A2UISurface, { envelope: env });
    expect(screen.getByText('T')).toBeInTheDocument();
    expect(screen.queryAllByRole('tab')).toHaveLength(0);
  });

  it('shows a placeholder for unsupported components', () => {
    render(A2UISurface, {
      envelope: {
        version: 'v1.0',
        createSurface: { surfaceId: 'w', components: [{ id: 'root', component: 'FilterBar' }] },
      },
    });
    expect(screen.getByText(/not supported/i)).toBeInTheDocument();
  });

  it('shows "Unsupported surface" when there is no root component', () => {
    render(A2UISurface, {
      envelope: {
        version: 'v1.0',
        createSurface: { surfaceId: 'empty', components: [] },
      },
    });
    expect(screen.getByText(/unsupported surface/i)).toBeInTheDocument();
  });

  it('a bare Chart root (widget) renders via A2UINode directly (not the Infographic path)', () => {
    const { container } = render(A2UISurface, {
      envelope: {
        version: 'v1.0',
        createSurface: {
          surfaceId: 'chart-only',
          components: [
            {
              id: 'root',
              component: 'Chart',
              type: 'bar',
              x: 'label',
              y: ['v'],
              data: [{ label: 'a', v: 1 }],
            },
          ],
        },
      },
    });
    // No Infographic title/sections chrome — the chart's own AppChart wrapper renders instead.
    expect(container.querySelector('.a2ui-infographic')).toBeNull();
    expect(container.querySelector('.h-80')).toBeTruthy();
  });
});
