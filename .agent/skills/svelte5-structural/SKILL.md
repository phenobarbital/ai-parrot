---
name: svelte5-structural
description: Svelte 5 + SvelteKit development with structural composition patterns. Use when building dashboards, widget systems, or component libraries where structural consistency matters. Emphasizes base components with behavior composition (strategies), OOP for state machines, and Svelte 5 runes. Triggers on Svelte/SvelteKit work requesting widgets, dashboards, reusable component systems, or when user prefers OOP patterns over pure functional composition.
---

# Svelte 5 Structural Composition

## Core Philosophy

**Structural Composition**: Base components encapsulate common structure (header, content, footer). Variations come through configuration and snippets, not component nesting.

**Behavior Composition**: Apply Strategy Pattern for what varies: data sources, renderers, validators. Not for structural elements.

**OOP Where It Fits**: Use classes for state machines, managers, and complex reactive state. Svelte 5 supports `$state` in classes.

```
┌─────────────────────────────────────────────────┐
│ AVOID: Over-composed structure                  │
│ <Widget><Header><Title/><Actions/></Header>...  │
│ → 10+ component instances per widget            │
├─────────────────────────────────────────────────┤
│ PREFER: Base + behavior composition             │
│ <Widget config={def} renderer={echarts}/>       │
│ → 1 component, strategies as params             │
└─────────────────────────────────────────────────┘
```

## Svelte 5 Syntax Requirements

**Always use Svelte 5 syntax:**
- `$state()`, `$derived()`, `$effect()` — never `$:` reactive statements
- `$props()` with destructuring — never `export let`
- `onclick` not `on:click` (no colon in event handlers)
- `{#snippet}` + `{@render}` — never `<slot>`
- `$app/state` not `$app/stores`

## File Naming

```
components/
├── widget-base.svelte       # lowercase-hyphen for files
├── chart-widget.svelte
└── widget-manager.svelte.ts # .svelte.ts for reactive classes
```

## Base Component Pattern

Create structural base components that accept snippets for variable content:

```svelte
<!-- widget-base.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';

  interface WidgetConfig {
    id: string;
    title: string;
    collapsible?: boolean;
    actions?: Array<{ icon: string; onclick: () => void }>;
  }

  interface Props {
    config: WidgetConfig;
    content: Snippet;
    footer?: Snippet;
    customActions?: Snippet;
  }

  let { config, content, footer, customActions }: Props = $props();

  // Internal state — common to ALL widgets
  let collapsed = $state(false);
  let loading = $state(false);
</script>

<article class="widget" class:collapsed>
  <header class="widget-header">
    <h3>{config.title}</h3>
    <div class="actions">
      {#if customActions}{@render customActions()}{/if}
      {#if config.collapsible}
        <button onclick={() => collapsed = !collapsed}>
          {collapsed ? '▼' : '▲'}
        </button>
      {/if}
    </div>
  </header>

  {#if !collapsed}
    <div class="widget-content">
      {#if loading}
        <div class="loading">Loading...</div>
      {:else}
        {@render content()}
      {/if}
    </div>
  {/if}

  {#if footer && !collapsed}
    <footer class="widget-footer">{@render footer()}</footer>
  {/if}
</article>
```

## Usage with Behavior Composition

```svelte
<!-- chart-widget.svelte -->
<script lang="ts">
  import WidgetBase from './widget-base.svelte';
  import type { DataSource, ChartRenderer } from '$lib/types';

  interface Props {
    id: string;
    title: string;
    dataSource: DataSource;
    renderer: ChartRenderer;
  }

  let { id, title, dataSource, renderer }: Props = $props();

  let data = $state<any>(null);

  $effect(() => {
    dataSource.fetch().then(d => data = d);
  });
</script>

<WidgetBase config={{ id, title, collapsible: true }}>
  {#snippet content()}
    {#if data}
      <div class="chart" use:renderer.bindings={data}></div>
    {/if}
  {/snippet}
</WidgetBase>
```

## State Machines with Classes

Use `.svelte.ts` files for reactive classes:

```typescript
// widget-manager.svelte.ts
export class WidgetManager {
  widgets = $state<WidgetConfig[]>([]);
  activeWidget = $state<string | null>(null);
  layout = $state<'grid' | 'masonry' | 'freeform'>('grid');

  private dragState = $state({ dragging: false, widgetId: null });

  add(config: WidgetConfig) {
    this.widgets = [...this.widgets, config];
  }

  remove(id: string) {
    this.widgets = this.widgets.filter(w => w.id !== id);
  }

  setActive(id: string | null) {
    this.activeWidget = id;
  }

  get visibleWidgets() {
    return this.widgets.filter(w => !w.hidden);
  }
}

// Singleton for app-wide state
export const widgetManager = new WidgetManager();
```

## Strategy Interfaces

Define clear interfaces for behavior composition:

```typescript
// $lib/types/strategies.ts
export interface DataSource<T = any> {
  fetch(): Promise<T>;
  subscribe?(callback: (data: T) => void): () => void;
}

export interface ChartRenderer {
  bindings: (node: HTMLElement, data: any) => { update?: (data: any) => void };
  destroy?: () => void;
}

// Implementations
export function createRestDataSource<T>(endpoint: string): DataSource<T> {
  return {
    async fetch() {
      const res = await fetch(endpoint);
      return res.json();
    }
  };
}

export function createEchartsRenderer(options: EChartsOption): ChartRenderer {
  let chart: ECharts | null = null;
  return {
    bindings(node, data) {
      chart = echarts.init(node);
      chart.setOption({ ...options, dataset: { source: data } });
      return {
        update(newData) {
          chart?.setOption({ dataset: { source: newData } });
        }
      };
    },
    destroy() {
      chart?.dispose();
    }
  };
}
```

## When to Use Each Pattern

| Scenario | Pattern | Example |
|----------|---------|---------|
| Common structure | Base component | Widget shell, Card, Modal |
| Variable content | Snippet | Chart area, form fields |
| Data fetching | Strategy | REST, GraphQL, WebSocket |
| Rendering logic | Strategy | ECharts, Vega, D3 |
| App-wide state | Class singleton | WidgetManager, AuthState |
| Component state | `$state` in component | collapsed, loading |
| Derived values | `$derived` | filteredList, total |

## Performance for Dashboards

For 30+ widgets:

```svelte
<!-- Lazy render with intersection observer -->
<script lang="ts">
  let visible = $state(false);

  function inViewport(node: HTMLElement) {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) visible = true;
    }, { threshold: 0.1 });
    observer.observe(node);
    return { destroy: () => observer.disconnect() };
  }
</script>

<div use:inViewport class="widget-slot">
  {#if visible}
    <ChartWidget {config} />
  {:else}
    <div class="widget-placeholder"></div>
  {/if}
</div>
```

## Reference Files

- **[references/patterns.md](references/patterns.md)**: Detailed structural patterns, snippet composition, action patterns
- **[references/state-machines.md](references/state-machines.md)**: Complex class patterns, stores integration, context usage
- **[references/widgets.md](references/widgets.md)**: Complete widget system implementation for dashboards

## Path Aliases

Use project aliases:
- `@components` → `./src/components`
- `@state` → `./src/lib/state`
- `@types` → `./src/types`
- `$lib` → `./src/lib` (SvelteKit default)
