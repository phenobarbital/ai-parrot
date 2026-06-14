---
name: echarts
description: Powerful charting library (bar, line, pie, scatter, gauge, heatmap, treemap, radar).
category: chart
scope: cdn
url: https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js
sri_hash: sha384-BQKzmHvQLMCAnL3UtDBA1Al5tFjsCz1wrMlIUA1wkzo14DYkRWjywW+p9pCj0cwd
global_var: echarts
---

## Usage
```html
<div id="chart" style="width:100%;height:360px;"></div>
<script>
  const chart = echarts.init(document.getElementById('chart'));
  chart.setOption({
    xAxis: { type: 'category', data: ['Mon', 'Tue', 'Wed'] },
    yAxis: { type: 'value' },
    series: [{ type: 'bar', data: [120, 200, 150] }],
  });
  window.addEventListener('resize', () => chart.resize());
</script>
```

## Types
```ts
declare const echarts: {
  init(dom: HTMLElement, theme?: string, opts?: { renderer?: 'canvas' | 'svg' }): ECharts;
};
interface ECharts {
  setOption(option: Record<string, unknown>): void;
  resize(): void;
}
```
