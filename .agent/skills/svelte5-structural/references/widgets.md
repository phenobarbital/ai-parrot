# Widget System for Dashboards

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Base Widget Component](#base-widget-component)
3. [Widget Type Implementations](#widget-type-implementations)
4. [Data Source Strategies](#data-source-strategies)
5. [Renderer Strategies](#renderer-strategies)
6. [Dashboard Container](#dashboard-container)
7. [Performance Optimization](#performance-optimization)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Dashboard Container                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Widget    │  │   Widget    │  │   Widget    │         │
│  │  ┌───────┐  │  │  ┌───────┐  │  │  ┌───────┐  │         │
│  │  │ Base  │  │  │  │ Base  │  │  │  │ Base  │  │         │
│  │  │Widget │  │  │  │Widget │  │  │  │Widget │  │         │
│  │  └───────┘  │  │  └───────┘  │  │  └───────┘  │         │
│  │  ┌───────┐  │  │  ┌───────┐  │  │  ┌───────┐  │         │
│  │  │Content│  │  │  │Content│  │  │  │Content│  │         │
│  │  │(Chart)│  │  │  │(Table)│  │  │  │(KPI)  │  │         │
│  │  └───────┘  │  │  └───────┘  │  │  └───────┘  │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│        │                │                │                  │
│        ▼                ▼                ▼                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Data Source Layer (Strategies)           │  │
│  │   REST  │  GraphQL  │  WebSocket  │  QuerySource      │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Base Widget Component

```svelte
<!-- widget-base.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import { clickOutside } from '$lib/actions/click-outside';
  
  interface WidgetAction {
    icon: string;
    label: string;
    onclick: () => void;
    disabled?: boolean;
  }
  
  interface WidgetConfig {
    id: string;
    title: string;
    subtitle?: string;
    collapsible?: boolean;
    maximizable?: boolean;
    refreshable?: boolean;
    removable?: boolean;
    customActions?: WidgetAction[];
  }
  
  interface Props {
    config: WidgetConfig;
    content: Snippet;
    footer?: Snippet;
    headerExtra?: Snippet;
    onrefresh?: () => Promise<void>;
    onremove?: () => void;
    onmaximize?: (maximized: boolean) => void;
  }
  
  let { 
    config, 
    content, 
    footer, 
    headerExtra,
    onrefresh,
    onremove,
    onmaximize
  }: Props = $props();
  
  // Widget internal state
  let collapsed = $state(false);
  let maximized = $state(false);
  let loading = $state(false);
  let menuOpen = $state(false);
  
  // Computed
  let showContent = $derived(!collapsed && !loading);
  
  // Actions
  async function handleRefresh() {
    if (!onrefresh || loading) return;
    loading = true;
    try {
      await onrefresh();
    } finally {
      loading = false;
    }
  }
  
  function toggleMaximize() {
    maximized = !maximized;
    onmaximize?.(maximized);
  }
  
  function toggleCollapse() {
    if (config.collapsible) {
      collapsed = !collapsed;
    }
  }
</script>

<article 
  class="widget"
  class:collapsed
  class:maximized
  class:loading
  data-widget-id={config.id}
>
  <header class="widget-header">
    <div class="widget-title-area" onclick={toggleCollapse}>
      <h3 class="widget-title">{config.title}</h3>
      {#if config.subtitle}
        <span class="widget-subtitle">{config.subtitle}</span>
      {/if}
    </div>
    
    {#if headerExtra}
      <div class="widget-header-extra">
        {@render headerExtra()}
      </div>
    {/if}
    
    <div class="widget-actions">
      {#if config.customActions}
        {#each config.customActions as action}
          <button 
            class="widget-action"
            title={action.label}
            disabled={action.disabled}
            onclick={action.onclick}
          >
            {action.icon}
          </button>
        {/each}
      {/if}
      
      {#if config.refreshable && onrefresh}
        <button 
          class="widget-action" 
          title="Refresh"
          disabled={loading}
          onclick={handleRefresh}
        >
          ↻
        </button>
      {/if}
      
      {#if config.maximizable}
        <button 
          class="widget-action"
          title={maximized ? 'Restore' : 'Maximize'}
          onclick={toggleMaximize}
        >
          {maximized ? '⊙' : '⤢'}
        </button>
      {/if}
      
      {#if config.collapsible}
        <button 
          class="widget-action"
          title={collapsed ? 'Expand' : 'Collapse'}
          onclick={toggleCollapse}
        >
          {collapsed ? '▼' : '▲'}
        </button>
      {/if}
      
      {#if config.removable && onremove}
        <button 
          class="widget-action widget-action--danger"
          title="Remove"
          onclick={onremove}
        >
          ✕
        </button>
      {/if}
    </div>
  </header>
  
  {#if showContent}
    <div class="widget-content">
      {@render content()}
    </div>
  {:else if loading}
    <div class="widget-loading">
      <div class="spinner"></div>
    </div>
  {/if}
  
  {#if footer && showContent}
    <footer class="widget-footer">
      {@render footer()}
    </footer>
  {/if}
</article>

<style>
  .widget {
    display: flex;
    flex-direction: column;
    background: var(--widget-bg, white);
    border-radius: var(--widget-radius, 8px);
    box-shadow: var(--widget-shadow, 0 1px 3px rgba(0,0,0,0.1));
    overflow: hidden;
    transition: box-shadow 0.2s;
  }
  
  .widget:hover {
    box-shadow: var(--widget-shadow-hover, 0 4px 12px rgba(0,0,0,0.15));
  }
  
  .widget.maximized {
    position: fixed;
    inset: 1rem;
    z-index: 1000;
  }
  
  .widget-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--widget-border, #eee);
  }
  
  .widget-title-area {
    flex: 1;
    cursor: pointer;
  }
  
  .widget-title {
    margin: 0;
    font-size: 0.875rem;
    font-weight: 600;
  }
  
  .widget-subtitle {
    font-size: 0.75rem;
    color: var(--text-muted, #666);
  }
  
  .widget-actions {
    display: flex;
    gap: 0.25rem;
  }
  
  .widget-action {
    padding: 0.25rem 0.5rem;
    background: transparent;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    opacity: 0.6;
    transition: opacity 0.2s, background 0.2s;
  }
  
  .widget-action:hover:not(:disabled) {
    opacity: 1;
    background: var(--widget-action-hover, #f0f0f0);
  }
  
  .widget-action:disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }
  
  .widget-action--danger:hover {
    color: var(--color-danger, #dc3545);
  }
  
  .widget-content {
    flex: 1;
    padding: 1rem;
    overflow: auto;
  }
  
  .widget-loading {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 2rem;
  }
  
  .widget-footer {
    padding: 0.5rem 1rem;
    border-top: 1px solid var(--widget-border, #eee);
    font-size: 0.75rem;
    color: var(--text-muted, #666);
  }
  
  .collapsed .widget-content,
  .collapsed .widget-footer {
    display: none;
  }
</style>
```

---

## Widget Type Implementations

### Chart Widget

```svelte
<!-- chart-widget.svelte -->
<script lang="ts">
  import WidgetBase from './widget-base.svelte';
  import type { DataSource, ChartRenderer } from '$lib/types/strategies';
  
  interface Props {
    id: string;
    title: string;
    dataSource: DataSource;
    renderer: ChartRenderer;
    refreshInterval?: number;
    onremove?: () => void;
  }
  
  let { 
    id, 
    title, 
    dataSource, 
    renderer, 
    refreshInterval,
    onremove 
  }: Props = $props();
  
  let data = $state<any>(null);
  let error = $state<string | null>(null);
  let chartNode: HTMLElement;
  let chartBindings: ReturnType<ChartRenderer['bind']> | null = null;
  
  // Initial fetch
  $effect(() => {
    fetchData();
  });
  
  // Auto-refresh
  $effect(() => {
    if (!refreshInterval) return;
    
    const interval = setInterval(fetchData, refreshInterval);
    return () => clearInterval(interval);
  });
  
  // Bind renderer when data and node are ready
  $effect(() => {
    if (!chartNode || !data) return;
    
    if (chartBindings) {
      chartBindings.update?.(data);
    } else {
      chartBindings = renderer.bind(chartNode, data);
    }
    
    return () => {
      chartBindings?.destroy?.();
      chartBindings = null;
    };
  });
  
  async function fetchData() {
    try {
      error = null;
      data = await dataSource.fetch();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to fetch data';
    }
  }
</script>

<WidgetBase 
  config={{ 
    id, 
    title, 
    collapsible: true, 
    refreshable: true,
    maximizable: true,
    removable: !!onremove
  }}
  onrefresh={fetchData}
  {onremove}
>
  {#snippet content()}
    {#if error}
      <div class="widget-error">
        <p>{error}</p>
        <button onclick={fetchData}>Retry</button>
      </div>
    {:else if data}
      <div class="chart-container" bind:this={chartNode}></div>
    {:else}
      <div class="widget-placeholder">No data</div>
    {/if}
  {/snippet}
  
  {#snippet footer()}
    <span>Last updated: {new Date().toLocaleTimeString()}</span>
  {/snippet}
</WidgetBase>

<style>
  .chart-container {
    width: 100%;
    height: 300px;
  }
</style>
```

### KPI Widget

```svelte
<!-- kpi-widget.svelte -->
<script lang="ts">
  import WidgetBase from './widget-base.svelte';
  import type { DataSource } from '$lib/types/strategies';
  
  interface KPIData {
    value: number;
    previousValue?: number;
    target?: number;
    unit?: string;
  }
  
  interface Props {
    id: string;
    title: string;
    dataSource: DataSource<KPIData>;
    format?: (value: number) => string;
  }
  
  let { id, title, dataSource, format = (v) => v.toLocaleString() }: Props = $props();
  
  let data = $state<KPIData | null>(null);
  
  let change = $derived(() => {
    if (!data?.previousValue) return null;
    return ((data.value - data.previousValue) / data.previousValue) * 100;
  });
  
  let progress = $derived(() => {
    if (!data?.target) return null;
    return (data.value / data.target) * 100;
  });
  
  $effect(() => {
    dataSource.fetch().then(d => data = d);
  });
</script>

<WidgetBase config={{ id, title, collapsible: false }}>
  {#snippet content()}
    {#if data}
      <div class="kpi">
        <span class="kpi-value">
          {format(data.value)}{data.unit ?? ''}
        </span>
        
        {#if change !== null}
          <span class="kpi-change" class:positive={change >= 0} class:negative={change < 0}>
            {change >= 0 ? '↑' : '↓'} {Math.abs(change).toFixed(1)}%
          </span>
        {/if}
        
        {#if progress !== null}
          <div class="kpi-progress">
            <div class="kpi-progress-bar" style:width="{Math.min(progress, 100)}%"></div>
          </div>
          <span class="kpi-target">Target: {format(data.target!)}</span>
        {/if}
      </div>
    {/if}
  {/snippet}
</WidgetBase>
```

### Table Widget

```svelte
<!-- table-widget.svelte -->
<script lang="ts" generics="T extends Record<string, any>">
  import WidgetBase from './widget-base.svelte';
  import type { DataSource } from '$lib/types/strategies';
  import type { Snippet } from 'svelte';
  
  interface Column<T> {
    key: keyof T;
    label: string;
    sortable?: boolean;
    cell?: Snippet<[T[keyof T], T]>;
  }
  
  interface Props {
    id: string;
    title: string;
    dataSource: DataSource<T[]>;
    columns: Column<T>[];
    pageSize?: number;
  }
  
  let { id, title, dataSource, columns, pageSize = 10 }: Props = $props();
  
  let data = $state<T[]>([]);
  let sortKey = $state<keyof T | null>(null);
  let sortDir = $state<'asc' | 'desc'>('asc');
  let page = $state(0);
  
  let sorted = $derived(() => {
    if (!sortKey) return data;
    return [...data].sort((a, b) => {
      const aVal = a[sortKey!];
      const bVal = b[sortKey!];
      const cmp = aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
      return sortDir === 'asc' ? cmp : -cmp;
    });
  });
  
  let paginated = $derived(() => {
    const start = page * pageSize;
    return sorted.slice(start, start + pageSize);
  });
  
  let totalPages = $derived(Math.ceil(data.length / pageSize));
  
  $effect(() => {
    dataSource.fetch().then(d => data = d);
  });
  
  function toggleSort(key: keyof T) {
    if (sortKey === key) {
      sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      sortKey = key;
      sortDir = 'asc';
    }
  }
</script>

<WidgetBase config={{ id, title, refreshable: true, maximizable: true }}>
  {#snippet content()}
    <table class="data-table">
      <thead>
        <tr>
          {#each columns as col}
            <th 
              class:sortable={col.sortable}
              onclick={() => col.sortable && toggleSort(col.key)}
            >
              {col.label}
              {#if sortKey === col.key}
                {sortDir === 'asc' ? '↑' : '↓'}
              {/if}
            </th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each paginated as row}
          <tr>
            {#each columns as col}
              <td>
                {#if col.cell}
                  {@render col.cell(row[col.key], row)}
                {:else}
                  {row[col.key]}
                {/if}
              </td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>
  {/snippet}
  
  {#snippet footer()}
    <div class="pagination">
      <button disabled={page === 0} onclick={() => page--}>←</button>
      <span>Page {page + 1} of {totalPages}</span>
      <button disabled={page >= totalPages - 1} onclick={() => page++}>→</button>
    </div>
  {/snippet}
</WidgetBase>
```

---

## Data Source Strategies

```typescript
// $lib/strategies/data-sources.ts

export interface DataSource<T = any> {
  fetch(): Promise<T>;
  subscribe?(callback: (data: T) => void): () => void;
}

// REST Data Source
export function createRestDataSource<T>(
  endpoint: string,
  options?: RequestInit
): DataSource<T> {
  return {
    async fetch() {
      const res = await fetch(endpoint, options);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    }
  };
}

// GraphQL Data Source
export function createGraphQLDataSource<T>(
  endpoint: string,
  query: string,
  variables?: Record<string, any>
): DataSource<T> {
  return {
    async fetch() {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, variables })
      });
      const { data, errors } = await res.json();
      if (errors) throw new Error(errors[0].message);
      return data;
    }
  };
}

// WebSocket Data Source (real-time)
export function createWebSocketDataSource<T>(
  url: string,
  initialFetch?: () => Promise<T>
): DataSource<T> {
  let latestData: T;
  let subscribers = new Set<(data: T) => void>();
  let ws: WebSocket | null = null;
  
  function connect() {
    ws = new WebSocket(url);
    ws.onmessage = (event) => {
      latestData = JSON.parse(event.data);
      subscribers.forEach(cb => cb(latestData));
    };
    ws.onclose = () => setTimeout(connect, 3000);
  }
  
  return {
    async fetch() {
      if (initialFetch) {
        latestData = await initialFetch();
      }
      if (!ws) connect();
      return latestData;
    },
    subscribe(callback) {
      subscribers.add(callback);
      if (latestData) callback(latestData);
      return () => subscribers.delete(callback);
    }
  };
}

// Mock Data Source (testing)
export function createMockDataSource<T>(
  data: T,
  delay = 500
): DataSource<T> {
  return {
    async fetch() {
      await new Promise(r => setTimeout(r, delay));
      return structuredClone(data);
    }
  };
}

// Polling Data Source
export function createPollingDataSource<T>(
  source: DataSource<T>,
  interval: number
): DataSource<T> {
  let subscribers = new Set<(data: T) => void>();
  let timer: ReturnType<typeof setInterval> | null = null;
  
  async function poll() {
    const data = await source.fetch();
    subscribers.forEach(cb => cb(data));
  }
  
  return {
    fetch: () => source.fetch(),
    subscribe(callback) {
      subscribers.add(callback);
      if (subscribers.size === 1) {
        timer = setInterval(poll, interval);
      }
      return () => {
        subscribers.delete(callback);
        if (subscribers.size === 0 && timer) {
          clearInterval(timer);
          timer = null;
        }
      };
    }
  };
}
```

---

## Renderer Strategies

```typescript
// $lib/strategies/renderers.ts

export interface ChartRenderer {
  bind(node: HTMLElement, data: any): {
    update?: (data: any) => void;
    destroy?: () => void;
  };
}

// ECharts Renderer
export function createEchartsRenderer(
  baseOptions: Record<string, any> = {}
): ChartRenderer {
  return {
    bind(node, data) {
      const chart = echarts.init(node);
      
      const options = {
        ...baseOptions,
        dataset: { source: data }
      };
      chart.setOption(options);
      
      const resizeObserver = new ResizeObserver(() => chart.resize());
      resizeObserver.observe(node);
      
      return {
        update(newData) {
          chart.setOption({ dataset: { source: newData } });
        },
        destroy() {
          resizeObserver.disconnect();
          chart.dispose();
        }
      };
    }
  };
}

// Chart.js Renderer
export function createChartJsRenderer(
  type: 'line' | 'bar' | 'pie' | 'doughnut',
  options: Record<string, any> = {}
): ChartRenderer {
  return {
    bind(node, data) {
      const canvas = document.createElement('canvas');
      node.appendChild(canvas);
      
      const chart = new Chart(canvas, {
        type,
        data,
        options
      });
      
      return {
        update(newData) {
          chart.data = newData;
          chart.update();
        },
        destroy() {
          chart.destroy();
          canvas.remove();
        }
      };
    }
  };
}

// Simple SVG Renderer (no dependencies)
export function createSvgBarRenderer(): ChartRenderer {
  return {
    bind(node, data: { label: string; value: number }[]) {
      const max = Math.max(...data.map(d => d.value));
      
      function render(items: typeof data) {
        node.innerHTML = `
          <svg viewBox="0 0 400 200" class="bar-chart">
            ${items.map((d, i) => `
              <g transform="translate(${i * (400 / items.length)}, 0)">
                <rect 
                  x="10" 
                  y="${200 - (d.value / max) * 180}" 
                  width="${(400 / items.length) - 20}" 
                  height="${(d.value / max) * 180}"
                  fill="var(--chart-color, #4f46e5)"
                />
                <text 
                  x="${(400 / items.length) / 2}" 
                  y="195" 
                  text-anchor="middle"
                  font-size="12"
                >${d.label}</text>
              </g>
            `).join('')}
          </svg>
        `;
      }
      
      render(data);
      
      return {
        update: render,
        destroy() { node.innerHTML = ''; }
      };
    }
  };
}
```

---

## Dashboard Container

```svelte
<!-- dashboard.svelte -->
<script lang="ts">
  import { widgetManager } from '$lib/state/widget-manager.svelte';
  import ChartWidget from './chart-widget.svelte';
  import KpiWidget from './kpi-widget.svelte';
  import TableWidget from './table-widget.svelte';
  import { inViewport } from '$lib/actions/intersection';
  
  // Widget type registry
  const widgetComponents = {
    chart: ChartWidget,
    kpi: KpiWidget,
    table: TableWidget
  } as const;
  
  interface Props {
    layout?: 'grid' | 'masonry' | 'freeform';
    columns?: number;
  }
  
  let { layout = 'grid', columns = 3 }: Props = $props();
  
  // Track visible widgets for lazy loading
  let visibleWidgets = $state(new Set<string>());
  
  function handleVisibility(id: string, visible: boolean) {
    if (visible) {
      visibleWidgets.add(id);
    }
    visibleWidgets = visibleWidgets; // Trigger reactivity
  }
</script>

<div 
  class="dashboard dashboard--{layout}"
  style:--columns={columns}
>
  {#each widgetManager.visibleWidgets as widget (widget.id)}
    {@const Component = widgetComponents[widget.type]}
    
    <div 
      class="dashboard-cell"
      style:grid-column="span {widget.size.w}"
      style:grid-row="span {widget.size.h}"
      use:inViewport={(visible) => handleVisibility(widget.id, visible)}
    >
      {#if visibleWidgets.has(widget.id)}
        <Component
          id={widget.id}
          title={widget.title}
          {...widget.settings}
          onremove={() => widgetManager.remove(widget.id)}
        />
      {:else}
        <div class="widget-placeholder">
          <span>{widget.title}</span>
        </div>
      {/if}
    </div>
  {/each}
</div>

<style>
  .dashboard {
    padding: 1rem;
  }
  
  .dashboard--grid {
    display: grid;
    grid-template-columns: repeat(var(--columns, 3), 1fr);
    gap: 1rem;
  }
  
  .dashboard--masonry {
    columns: var(--columns, 3);
    column-gap: 1rem;
  }
  
  .dashboard--masonry .dashboard-cell {
    break-inside: avoid;
    margin-bottom: 1rem;
  }
  
  .dashboard--freeform {
    position: relative;
    min-height: 100vh;
  }
  
  .dashboard--freeform .dashboard-cell {
    position: absolute;
  }
  
  .widget-placeholder {
    background: var(--placeholder-bg, #f5f5f5);
    border-radius: 8px;
    padding: 2rem;
    text-align: center;
    min-height: 200px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  @media (max-width: 768px) {
    .dashboard--grid {
      grid-template-columns: 1fr;
    }
    
    .dashboard--masonry {
      columns: 1;
    }
  }
</style>
```

---

## Performance Optimization

### Intersection Observer Action

```typescript
// $lib/actions/intersection.ts
export function inViewport(
  node: HTMLElement, 
  callback: (visible: boolean) => void
) {
  const observer = new IntersectionObserver(
    ([entry]) => callback(entry.isIntersecting),
    { 
      threshold: 0,
      rootMargin: '100px' // Pre-load slightly before visible
    }
  );
  
  observer.observe(node);
  
  return {
    destroy() {
      observer.disconnect();
    }
  };
}
```

### Virtual Scrolling for Large Lists

```svelte
<!-- virtual-list.svelte -->
<script lang="ts" generics="T">
  import type { Snippet } from 'svelte';
  
  interface Props {
    items: T[];
    itemHeight: number;
    item: Snippet<[T, number]>;
  }
  
  let { items, itemHeight, item }: Props = $props();
  
  let container: HTMLElement;
  let scrollTop = $state(0);
  let containerHeight = $state(0);
  
  let visibleRange = $derived(() => {
    const start = Math.floor(scrollTop / itemHeight);
    const visible = Math.ceil(containerHeight / itemHeight);
    const overscan = 3;
    return {
      start: Math.max(0, start - overscan),
      end: Math.min(items.length, start + visible + overscan)
    };
  });
  
  let visibleItems = $derived(
    items.slice(visibleRange.start, visibleRange.end)
  );
  
  let totalHeight = $derived(items.length * itemHeight);
  let offsetY = $derived(visibleRange.start * itemHeight);
</script>

<div 
  class="virtual-container"
  bind:this={container}
  bind:clientHeight={containerHeight}
  onscroll={(e) => scrollTop = e.currentTarget.scrollTop}
>
  <div class="virtual-spacer" style:height="{totalHeight}px">
    <div class="virtual-content" style:transform="translateY({offsetY}px)">
      {#each visibleItems as data, i (visibleRange.start + i)}
        <div class="virtual-item" style:height="{itemHeight}px">
          {@render item(data, visibleRange.start + i)}
        </div>
      {/each}
    </div>
  </div>
</div>

<style>
  .virtual-container {
    overflow-y: auto;
    height: 100%;
  }
  
  .virtual-spacer {
    position: relative;
  }
  
  .virtual-content {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
  }
</style>
```

### Debounced Updates

```typescript
// $lib/utils/debounce.ts
export function debounce<T extends (...args: any[]) => any>(
  fn: T,
  delay: number
): T {
  let timeout: ReturnType<typeof setTimeout>;
  
  return ((...args: Parameters<T>) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => fn(...args), delay);
  }) as T;
}

// Usage in component
$effect(() => {
  const debouncedSave = debounce(() => {
    localStorage.setItem('dashboard', widgetManager.toJSON());
  }, 1000);
  
  // Auto-save on changes
  debouncedSave();
});
```