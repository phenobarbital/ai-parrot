import { describe, expect, it } from 'vitest';
import { toChartBlockData } from './a2ui-chart-adapter';

describe('toChartBlockData', () => {
  const dataModel = {
    charts: {
      'chart-0': [
        { label: 'Jan', '2026': 10, '2025': 8 },
        { label: 'Feb', '2026': 20, '2025': 15 },
      ],
    },
  };

  it('maps a bar chart with bound rows', () => {
    const result = toChartBlockData(
      { type: 'bar', x: 'label', y: ['2026', '2025'], data: { path: '/charts/chart-0' } },
      dataModel,
    );
    expect(result.chart_type).toBe('bar');
    expect(result.labels).toEqual(['Jan', 'Feb']);
    expect(result.series).toEqual([
      { name: '2026', values: [10, 20] },
      { name: '2025', values: [8, 15] },
    ]);
  });

  it('maps donut without collapsing to pie', () => {
    const result = toChartBlockData(
      { type: 'donut', x: 'label', y: ['2026'], data: { path: '/charts/chart-0' } },
      dataModel,
    );
    expect(result.chart_type).toBe('donut');
  });

  it('forwards colorBySign/positiveColor/negativeColor', () => {
    const result = toChartBlockData(
      {
        type: 'bar',
        x: 'label',
        y: ['2026'],
        data: { path: '/charts/chart-0' },
        colorBySign: true,
        positiveColor: '#0a0',
        negativeColor: '#a00',
      },
      dataModel,
    );
    expect(result.color_by_sign).toBe(true);
    expect(result.positive_color).toBe('#0a0');
    expect(result.negative_color).toBe('#a00');
  });

  it('honours the half layout hint', () => {
    const result = toChartBlockData(
      { type: 'bar', x: 'label', y: ['2026'], data: { path: '/charts/chart-0' }, layout: 'half' },
      dataModel,
    );
    expect(result.layout).toBe('half');
  });

  it('forwards per-series palette colors', () => {
    const result = toChartBlockData(
      {
        type: 'bar',
        x: 'label',
        y: ['2026', '2025'],
        data: { path: '/charts/chart-0' },
        palette: ['#111', '#222'],
      },
      dataModel,
    );
    expect(result.series[0].color).toBe('#111');
    expect(result.series[1].color).toBe('#222');
  });

  it('falls back to bar for an unknown/malformed type', () => {
    const result = toChartBlockData({ type: 'not-a-type', x: 'label', y: [] }, dataModel);
    expect(result.chart_type).toBe('bar');
  });

  it('handles an unresolved/missing data binding gracefully (empty rows)', () => {
    const result = toChartBlockData({ type: 'bar', x: 'label', y: ['2026'] }, dataModel);
    expect(result.labels).toEqual([]);
    expect(result.series).toEqual([{ name: '2026', values: [] }]);
  });
});
