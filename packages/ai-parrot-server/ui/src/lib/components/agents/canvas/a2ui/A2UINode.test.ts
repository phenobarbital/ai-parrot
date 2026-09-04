// ai-parrot (FEAT-527): A2UINode dispatch for the non-Chart/KPICard node
// types — DataTable/Timeline/InfoCard/Text/Image/Divider/CheckBox/List/
// Row/Column/Tabs, and the unsupported/action-bearing placeholder.
import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

const { features } = vi.hoisted(() => ({
  features: {
    voice: false,
    avatar: false,
    maps: false,
    charts: false,
    canvas: true,
    infographic: true,
    datasets: false,
    richEditor: false,
    a2ui: true,
  },
}));
vi.mock('$lib/features', () => ({ features }));

import A2UINode from './A2UINode.svelte';

describe('A2UINode', () => {
  it('DataTable resolves bound rows into positional cells', () => {
    render(A2UINode, {
      descriptor: {
        component: 'DataTable',
        properties: {
          title: 'Sales',
          columns: [{ name: 'region', title: 'Region' }, { name: 'total' }],
          data: { path: '/tables/t0' },
        },
      },
      dataModel: { tables: { t0: [{ region: 'North', total: 10 }] } },
    });
    expect(screen.getByText('Sales')).toBeInTheDocument();
    expect(screen.getByText('Region')).toBeInTheDocument();
    expect(screen.getByText('North')).toBeInTheDocument();
    expect(screen.getByText('10')).toBeInTheDocument();
  });

  it('Timeline maps events to items', () => {
    render(A2UINode, {
      descriptor: {
        component: 'Timeline',
        properties: {
          title: 'Roadmap',
          events: [{ timestamp: '2026-01', title: 'Kickoff', description: 'start' }],
        },
      },
      dataModel: {},
    });
    expect(screen.getByText('Roadmap')).toBeInTheDocument();
    expect(screen.getByText('Kickoff')).toBeInTheDocument();
    expect(screen.getByText('start')).toBeInTheDocument();
  });

  it('InfoCard renders title/subtitle/body/badge/footer', () => {
    render(A2UINode, {
      descriptor: {
        component: 'InfoCard',
        properties: { title: 'T', subtitle: 'S', body: 'B', badge: 'New', footer: 'F' },
      },
      dataModel: {},
    });
    expect(screen.getByText('T')).toBeInTheDocument();
    expect(screen.getByText('S')).toBeInTheDocument();
    expect(screen.getByText('B')).toBeInTheDocument();
    expect(screen.getByText('New')).toBeInTheDocument();
    expect(screen.getByText('F')).toBeInTheDocument();
  });

  it('Text renders resolved bound text', () => {
    render(A2UINode, {
      descriptor: { component: 'Text', properties: { text: { path: '/greeting' } } },
      dataModel: { greeting: 'Hello' },
    });
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });

  it('Image renders url/alt', () => {
    render(A2UINode, {
      descriptor: { component: 'Image', properties: { url: 'https://x/y.png', description: 'desc' } },
      dataModel: {},
    });
    const img = screen.getByAltText('desc') as HTMLImageElement;
    expect(img.src).toBe('https://x/y.png');
  });

  it('CheckBox renders a disabled, read-only checkbox with its label', () => {
    render(A2UINode, {
      descriptor: { component: 'CheckBox', properties: { label: 'Agree', value: true } },
      dataModel: {},
    });
    const checkbox = screen.getByRole('checkbox') as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
    expect(checkbox.disabled).toBe(true);
    expect(screen.getByText('Agree')).toBeInTheDocument();
  });

  it('List renders each child via nested A2UINode dispatch', () => {
    render(A2UINode, {
      descriptor: {
        component: 'List',
        properties: {
          children: [
            { component: 'Text', properties: { text: 'one' } },
            { component: 'Text', properties: { text: 'two' } },
          ],
        },
      },
      dataModel: {},
    });
    expect(screen.getByText('one')).toBeInTheDocument();
    expect(screen.getByText('two')).toBeInTheDocument();
  });

  it('Tabs renders each nested tab child', () => {
    render(A2UINode, {
      descriptor: {
        component: 'Tabs',
        properties: {
          tabs: [
            { title: 'Tab A', child: { component: 'Text', properties: { text: 'content A' } } },
          ],
        },
      },
      dataModel: {},
    });
    expect(screen.getByText('Tab A')).toBeInTheDocument();
    expect(screen.getByText('content A')).toBeInTheDocument();
  });

  it.each(['Button', 'TextField', 'FilterBar', 'Map', 'NotARealComponent'])(
    'action-bearing/unknown component %s degrades to a visible placeholder, never throws',
    (component) => {
      expect(() =>
        render(A2UINode, { descriptor: { component, properties: {} }, dataModel: {} }),
      ).not.toThrow();
      expect(screen.getByText(/not supported/i)).toBeInTheDocument();
    },
  );

  it('Chart with features.charts off shows a disabled placeholder, not the real chart', () => {
    render(A2UINode, {
      descriptor: { component: 'Chart', properties: { type: 'bar', x: 'label', y: ['v'] } },
      dataModel: {},
    });
    expect(screen.getByText(/chart feature disabled/i)).toBeInTheDocument();
  });
});
