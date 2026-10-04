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

describe('A2UISurface — v1.0 flat components with id-referenced children (FEAT-611)', () => {
  const flatEnvelope: A2UIEnvelope = {
    version: 'v1.0',
    createSurface: {
      surfaceId: 'linked-flat',
      components: [
        { id: 'root', component: 'Column', children: ['kpi_row', 'note'] },
        { id: 'kpi_row', component: 'Row', children: ['kpi_a', 'kpi_b'] },
        { id: 'kpi_a', component: 'KPICard', label: 'Total visits', value: { path: '/kpis/rows/0/visits' } },
        { id: 'kpi_b', component: 'KPICard', label: 'Stores', value: 5 },
        { id: 'note', component: 'Text', text: 'flat tree' },
      ],
      dataModel: { kpis: { rows: [{ visits: 22 }] } },
    },
  };

  it('resolves string children through the surface index instead of rendering "Unknown component"', () => {
    render(A2UISurface, { envelope: flatEnvelope });
    expect(screen.getByText('Total visits')).toBeTruthy();
    expect(screen.getByText('Stores')).toBeTruthy();
    expect(screen.getByText('22')).toBeTruthy();
    expect(screen.getByText('flat tree')).toBeTruthy();
    expect(screen.queryByText(/is not supported in this view/)).toBeNull();
  });
});

describe('A2UISurface — FilterBar with two filters on one column (FEAT-611 live S4)', () => {
  it('renders a From/To pair over the same column without a duplicate-key crash', () => {
    const envelope: A2UIEnvelope = {
      version: 'v1.0',
      createSurface: {
        surfaceId: 'dup-column-filters',
        components: [
          { id: 'root', component: 'Column', children: ['dates'] },
          {
            id: 'dates',
            component: 'FilterBar',
            filters: [
              { column: 'day', label: 'From', options: [{ label: 'Mar 1', value: '2025-03-01' }] },
              { column: 'day', label: 'To', options: [{ label: 'Mar 7', value: '2025-03-07' }] },
            ],
          },
        ],
        dataModel: {},
      },
    };
    render(A2UISurface, { envelope });
    expect(screen.getByText('From')).toBeTruthy();
    expect(screen.getByText('To')).toBeTruthy();
  });
});
