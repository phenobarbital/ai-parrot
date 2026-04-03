# Structural Patterns Reference

## Table of Contents
1. [Base Component Hierarchy](#base-component-hierarchy)
2. [Snippet Composition](#snippet-composition)
3. [Action Patterns](#action-patterns)
4. [Conditional Rendering](#conditional-rendering)
5. [Event Handling](#event-handling)

---

## Base Component Hierarchy

### Multi-Level Base Components

For complex UIs, create a hierarchy of base components:

```
BaseContainer (padding, background, border-radius)
  └── BaseCard (shadow, header slot)
        └── BaseWidget (actions, collapse, loading)
              └── ChartWidget (specific implementation)
```

```svelte
<!-- base-container.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  
  interface Props {
    padding?: 'none' | 'sm' | 'md' | 'lg';
    children: Snippet;
  }
  
  let { padding = 'md', children }: Props = $props();
</script>

<div class="container p-{padding}">
  {@render children()}
</div>
```

```svelte
<!-- base-card.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import BaseContainer from './base-container.svelte';
  
  interface Props {
    elevated?: boolean;
    header?: Snippet;
    children: Snippet;
  }
  
  let { elevated = false, header, children }: Props = $props();
</script>

<BaseContainer>
  <div class="card" class:elevated>
    {#if header}
      <div class="card-header">{@render header()}</div>
    {/if}
    <div class="card-body">{@render children()}</div>
  </div>
</BaseContainer>
```

### Generic Base with Type Parameters

```svelte
<!-- data-list.svelte -->
<script lang="ts" generics="T">
  import type { Snippet } from 'svelte';
  
  interface Props {
    items: T[];
    item: Snippet<[T, number]>;
    empty?: Snippet;
  }
  
  let { items, item, empty }: Props = $props();
</script>

{#if items.length === 0}
  {#if empty}
    {@render empty()}
  {:else}
    <p>No items</p>
  {/if}
{:else}
  {#each items as data, index (data)}
    {@render item(data, index)}
  {/each}
{/if}
```

Usage:
```svelte
<DataList items={users}>
  {#snippet item(user, idx)}
    <div>{idx + 1}. {user.name}</div>
  {/snippet}
  {#snippet empty()}
    <p>No users found</p>
  {/snippet}
</DataList>
```

---

## Snippet Composition

### Named Snippets as Props

```svelte
<!-- modal.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  
  interface Props {
    open: boolean;
    onclose: () => void;
    title: Snippet;
    body: Snippet;
    actions?: Snippet;
  }
  
  let { open, onclose, title, body, actions }: Props = $props();
</script>

{#if open}
  <div class="modal-backdrop" onclick={onclose}>
    <div class="modal" onclick={(e) => e.stopPropagation()}>
      <header>{@render title()}</header>
      <main>{@render body()}</main>
      {#if actions}
        <footer>{@render actions()}</footer>
      {/if}
    </div>
  </div>
{/if}
```

### Snippets with Parameters

```svelte
<!-- table.svelte -->
<script lang="ts" generics="T">
  import type { Snippet } from 'svelte';
  
  interface Column<T> {
    key: keyof T;
    label: string;
    cell?: Snippet<[T[keyof T], T]>;
  }
  
  interface Props {
    data: T[];
    columns: Column<T>[];
  }
  
  let { data, columns }: Props = $props();
</script>

<table>
  <thead>
    <tr>
      {#each columns as col}
        <th>{col.label}</th>
      {/each}
    </tr>
  </thead>
  <tbody>
    {#each data as row}
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
```

---

## Action Patterns

### Reusable Actions

```typescript
// actions/click-outside.ts
export function clickOutside(node: HTMLElement, callback: () => void) {
  function handleClick(event: MouseEvent) {
    if (!node.contains(event.target as Node)) {
      callback();
    }
  }
  
  document.addEventListener('click', handleClick, true);
  
  return {
    destroy() {
      document.removeEventListener('click', handleClick, true);
    }
  };
}
```

```typescript
// actions/intersection.ts
export function inViewport(
  node: HTMLElement, 
  callback: (visible: boolean) => void
) {
  const observer = new IntersectionObserver(
    ([entry]) => callback(entry.isIntersecting),
    { threshold: 0.1 }
  );
  
  observer.observe(node);
  
  return {
    destroy() {
      observer.disconnect();
    }
  };
}
```

### Action with Parameters and Updates

```typescript
// actions/tooltip.ts
interface TooltipParams {
  text: string;
  position?: 'top' | 'bottom' | 'left' | 'right';
}

export function tooltip(node: HTMLElement, params: TooltipParams) {
  let tooltipEl: HTMLElement | null = null;
  
  function show() {
    tooltipEl = document.createElement('div');
    tooltipEl.className = `tooltip tooltip-${params.position ?? 'top'}`;
    tooltipEl.textContent = params.text;
    node.appendChild(tooltipEl);
  }
  
  function hide() {
    tooltipEl?.remove();
    tooltipEl = null;
  }
  
  node.addEventListener('mouseenter', show);
  node.addEventListener('mouseleave', hide);
  
  return {
    update(newParams: TooltipParams) {
      params = newParams;
      if (tooltipEl) {
        tooltipEl.textContent = params.text;
      }
    },
    destroy() {
      hide();
      node.removeEventListener('mouseenter', show);
      node.removeEventListener('mouseleave', hide);
    }
  };
}
```

Usage:
```svelte
<button use:tooltip={{ text: 'Click me', position: 'bottom' }}>
  Hover
</button>
```

---

## Conditional Rendering

### Efficient Conditional Patterns

```svelte
<!-- PREFER: Single condition with content -->
{#if user}
  <Dashboard {user} />
{:else}
  <Login />
{/if}

<!-- AVOID: Multiple separate conditions -->
{#if user}<Dashboard {user} />{/if}
{#if !user}<Login />{/if}
```

### Keyed Blocks for Re-initialization

```svelte
<!-- Force component recreation when id changes -->
{#key widgetId}
  <Widget id={widgetId} />
{/key}
```

### Show/Hide vs Mount/Unmount

```svelte
<!-- Mount/unmount: Use when component is expensive to keep alive -->
{#if visible}
  <HeavyChart data={data} />
{/if}

<!-- Show/hide: Use when toggle is frequent and state should persist -->
<div class:hidden={!visible}>
  <LightWidget />
</div>

<style>
  .hidden { display: none; }
</style>
```

---

## Event Handling

### Event Forwarding

```svelte
<!-- button.svelte -->
<script lang="ts">
  import type { HTMLButtonAttributes } from 'svelte/elements';
  
  interface Props extends HTMLButtonAttributes {
    variant?: 'primary' | 'secondary';
  }
  
  let { variant = 'primary', children, ...rest }: Props = $props();
</script>

<button class="btn btn-{variant}" {...rest}>
  {@render children()}
</button>
```

### Custom Events with Callbacks

```svelte
<!-- sortable-list.svelte -->
<script lang="ts">
  interface Props {
    items: string[];
    onreorder: (items: string[]) => void;
  }
  
  let { items, onreorder }: Props = $props();
  
  function handleDragEnd(fromIdx: number, toIdx: number) {
    const reordered = [...items];
    const [moved] = reordered.splice(fromIdx, 1);
    reordered.splice(toIdx, 0, moved);
    onreorder(reordered);
  }
</script>
```

### Bindable Props for Two-Way Binding

```svelte
<!-- search-input.svelte -->
<script lang="ts">
  interface Props {
    value?: string;
    placeholder?: string;
  }
  
  let { value = $bindable(''), placeholder = 'Search...' }: Props = $props();
</script>

<input 
  type="search" 
  bind:value 
  {placeholder}
/>
```

Usage:
```svelte
<SearchInput bind:value={searchTerm} />
```