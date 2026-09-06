// ai-parrot (FEAT-529): pure ECharts-option-building logic for the bundled
// Graph component — no rendering/canvas involved (`buildGraphOption` is
// exported from `A2UIGraph.svelte`'s `<script module>` block precisely so
// it is directly unit-testable this way).
import { describe, expect, it } from 'vitest';
import { buildGraphOption, hasCompletePositions, type GraphProperties } from './A2UIGraph.svelte';

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
});
