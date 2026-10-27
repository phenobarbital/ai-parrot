// ai-parrot (FEAT-529): pure ECharts-option-building logic for the bundled
// Graph component — no rendering/canvas involved (`buildGraphOption` is
// exported from `A2UIGraph.svelte`'s `<script module>` block precisely so
// it is directly unit-testable this way).
import { describe, expect, it } from 'vitest';
import {
  buildGraphOption,
  c4SymbolFor,
  computeBoundaryFrames,
  hasCompletePositions,
  type GraphProperties,
} from './A2UIGraph.svelte';

const identity = (token: string) => token;

describe('A2UIGraph option building', () => {
  it('builds echarts option from positions', () => {
    const properties: GraphProperties = {
      kind: 'flowchart',
      direction: 'TB',
      title: 'Demo',
      nodes: [
        { id: 'a', label: 'Start', state: 'completed' },
        { id: 'b', label: 'End', state: 'failed' },
      ],
      edges: [{ from: 'a', to: 'b', label: 'go', kind: 'dashed' }],
      layout: {
        engine: 'layered',
        positions: { a: { x: 0, y: 0 }, b: { x: 100, y: 0 } },
      },
    };

    expect(hasCompletePositions(properties)).toBe(true);

    const option = buildGraphOption(properties, identity);
    const series = (option.series as Record<string, unknown>[])[0];
    expect(series.type).toBe('graph');
    expect(series.layout).toBe('none');

    const data = series.data as Record<string, unknown>[];
    expect(data).toHaveLength(2);
    const byId = Object.fromEntries(data.map((entry) => [entry.id, entry]));
    expect(byId.a.x).toBe(0);
    expect(byId.a.y).toBe(0);
    expect(byId.b.x).toBe(100);
    expect(byId.b.y).toBe(0);

    const links = series.links as Record<string, unknown>[];
    expect(links).toHaveLength(1);
    expect(links[0].source).toBe('a');
    expect(links[0].target).toBe('b');
    expect((links[0].lineStyle as Record<string, unknown>).type).toBe('dashed');

    // State -> status role -> resolved token (identity resolver here).
    expect((byId.a.itemStyle as Record<string, unknown>).color).toBe('var(--chart-2)'); // completed -> good
    expect((byId.b.itemStyle as Record<string, unknown>).color).toBe('var(--destructive)'); // failed -> critical
  });

  it('falls back to circular without positions', () => {
    const properties: GraphProperties = {
      nodes: [{ id: 'a' }, { id: 'b' }],
      edges: [{ from: 'a', to: 'b' }],
    };

    expect(hasCompletePositions(properties)).toBe(false);

    const option = buildGraphOption(properties, identity);
    const series = (option.series as Record<string, unknown>[])[0];
    expect(series.layout).toBe('circular');

    const data = series.data as Record<string, unknown>[];
    expect(data.every((entry) => entry.x === undefined && entry.y === undefined)).toBe(true);
  });

  it('falls back to circular when positions are incomplete', () => {
    const properties: GraphProperties = {
      nodes: [{ id: 'a' }, { id: 'b' }],
      edges: [{ from: 'a', to: 'b' }],
      layout: { engine: 'layered', positions: { a: { x: 0, y: 0 } } }, // missing 'b'
    };

    expect(hasCompletePositions(properties)).toBe(false);
    const option = buildGraphOption(properties, identity);
    expect((option.series as Record<string, unknown>[])[0].layout).toBe('circular');
  });

  it('marks the selected node distinctly', () => {
    const properties: GraphProperties = {
      nodes: [{ id: 'a' }, { id: 'b' }],
      edges: [],
      selection: { selectable: true, selected: 'b' },
    };
    const option = buildGraphOption(properties, identity);
    const data = (option.series as Record<string, unknown>[])[0].data as Record<string, unknown>[];
    const selected = data.find((entry) => entry.id === 'b')!;
    expect((selected.itemStyle as Record<string, unknown>).borderColor).toBe('var(--ring)');
  });

  it('represents node group membership', () => {
    const properties: GraphProperties = {
      nodes: [{ id: 'a', group: 'g1' }, { id: 'b' }],
      edges: [],
      groups: [{ id: 'g1', label: 'Group A', nodes: ['a'] }],
    };
    const option = buildGraphOption(properties, identity);
    const data = (option.series as Record<string, unknown>[])[0].data as Record<string, unknown>[];
    const a = data.find((entry) => entry.id === 'a')!;
    expect(a.value).toBe('g1');
  });

  const c4Props = (withPositions: boolean): GraphProperties => ({
    kind: 'c4',
    level: 'container',
    nodes: [
      { id: 'customer', label: 'Customer', c4Type: 'person', description: 'Buys things' },
      { id: 'web', label: 'Web App', c4Type: 'container', technology: 'SvelteKit', group: 'shop' },
      { id: 'db', label: 'Orders DB', c4Type: 'container_db', technology: 'PostgreSQL', group: 'core' },
      { id: 'pay', label: 'Payments', c4Type: 'system_ext' },
    ],
    edges: [
      { from: 'customer', to: 'web', label: 'Uses', technology: 'HTTPS', hint: 'down' },
      { from: 'web', to: 'db', label: 'Reads', technology: 'asyncpg', bidirectional: true },
    ],
    groups: [
      { id: 'shop', label: 'Shop', nodes: ['web'], c4Type: 'system' },
      { id: 'core', label: 'Core', nodes: ['db'], parent: 'shop', c4Type: 'container' },
    ],
    layout: withPositions
      ? {
          positions: {
            customer: { x: 0, y: 0 },
            web: { x: 100, y: 100 },
            db: { x: 200, y: 200 },
            pay: { x: 300, y: 0 },
          },
        }
      : undefined,
  });

  const seriesOf = (option: Record<string, unknown>) => (option.series as Record<string, unknown>[])[0];

  it('renders c4 boundary frames from complete positions', () => {
    const frames = computeBoundaryFrames(c4Props(true));
    const core = frames.find((f) => f.id === 'core')!;
    expect(core).toEqual({ id: 'core', label: 'Core [container boundary]', depth: 1, x: 180, y: 180, w: 40, h: 40 });
    expect(buildGraphOption(c4Props(true), identity).graphic).toBeUndefined();
  });

  it('nests child boundary frames inside their parent', () => {
    const frames = computeBoundaryFrames(c4Props(true));
    expect(frames.map((f) => f.id)).toEqual(['shop', 'core']);
    const [shop, core] = frames;
    expect(shop.depth).toBe(0);
    expect(shop.x).toBeLessThan(core.x);
    expect(shop.y).toBeLessThan(core.y);
    expect(shop.x + shop.w).toBeGreaterThan(core.x + core.w);
    expect(shop.y + shop.h).toBeGreaterThan(core.y + core.h);
    expect(shop).toMatchObject({ x: 80, y: 80, w: 160, h: 160 });
  });

  it('maps c4 element types to symbols and captions', () => {
    expect(c4SymbolFor('person')).toEqual({ symbol: 'circle', caption: 'Person', external: false });
    expect(c4SymbolFor('container_db')).toEqual({ symbol: 'roundRect', caption: '[DB]', external: false });
    expect(c4SymbolFor('system_queue_ext')).toEqual({ symbol: 'rect', caption: '[Queue]', external: true });
    expect(c4SymbolFor('component')).toEqual({ symbol: 'rect', caption: '', external: false });
    expect(c4SymbolFor(undefined)).toEqual({ symbol: 'rect', caption: '', external: false });
    const data = seriesOf(buildGraphOption(c4Props(true), identity)).data as Record<string, unknown>[];
    expect(data.find((d) => d.id === 'customer')!.symbol).toBe('circle');
    expect(data.find((d) => d.id === 'db')!.symbol).toBe('roundRect');
  });

  it('dashes external elements', () => {
    const data = seriesOf(buildGraphOption(c4Props(true), identity)).data as Record<string, unknown>[];
    expect((data.find((d) => d.id === 'pay')!.itemStyle as Record<string, unknown>).borderType).toBe('dashed');
    expect((data.find((d) => d.id === 'web')!.itemStyle as Record<string, unknown>).borderType).toBeUndefined();
  });

  it('adds technology as a second label line', () => {
    const data = seriesOf(buildGraphOption(c4Props(true), identity)).data as Record<string, unknown>[];
    const web = data.find((d) => d.id === 'web')!;
    expect((web.label as Record<string, unknown>).formatter).toBe('Web App\n[SvelteKit]');
    const customer = data.find((d) => d.id === 'customer')!;
    const tooltip = (customer.tooltip as { formatter: () => string }).formatter();
    expect(tooltip).toBe('Customer\nperson\nBuys things');
  });

  it('draws bidirectional edges with two arrowheads', () => {
    const links = seriesOf(buildGraphOption(c4Props(true), identity)).links as Record<string, unknown>[];
    expect(links[1].symbol).toEqual(['arrow', 'arrow']);
    expect((links[1].label as Record<string, unknown>).formatter).toBe('Reads [asyncpg]');
    expect(links[0].symbol).toBeUndefined();
    expect((links[0].label as Record<string, unknown>).formatter).toBe('Uses [HTTPS]');
  });

  it('c4 without positions falls back to circular with no frames', () => {
    const props = c4Props(false);
    expect(computeBoundaryFrames(props)).toEqual([]);
    const option = buildGraphOption(props, identity);
    expect(seriesOf(option).layout).toBe('circular');
    expect(option.graphic).toBeUndefined();
  });

  it('non-c4 option is unchanged by the c4 path', () => {
    const props: GraphProperties = {
      kind: 'flowchart',
      nodes: [{ id: 'a', label: 'A', technology: 'X' }, { id: 'b' }],
      edges: [{ from: 'a', to: 'b', label: 'go', technology: 'T', bidirectional: true }],
    };
    const series = seriesOf(buildGraphOption(props, identity));
    const a = (series.data as Record<string, unknown>[])[0];
    expect(Object.keys(a)).toEqual(['id', 'name', 'category', 'tooltip', 'itemStyle']);
    const link = (series.links as Record<string, unknown>[])[0];
    expect(link).toEqual({ source: 'a', target: 'b', lineStyle: {}, label: { show: true, formatter: 'go' } });
  });
});
