---
name: gridjs
description: Lightweight, dependency-free interactive data grid with sorting, search and pagination.
category: grid
scope: cdn
url: https://cdn.jsdelivr.net/npm/gridjs@6.2.0/dist/gridjs.umd.js
sri_hash: sha384-REGENERATEMEREGENERATEMEREGENERATEMEREGENERATEMEREGENERATEME
css_url: https://cdn.jsdelivr.net/npm/gridjs@6.2.0/dist/theme/mermaid.min.css
css_sri_hash: sha384-REGENERATEMEREGENERATEMEREGENERATEMEREGENERATEMEREGENERATEME
global_var: gridjs
---

## Usage
```html
<div id="grid"></div>
<script>
  new gridjs.Grid({
    columns: ['Name', 'Region', 'Revenue'],
    data: [
      ['Acme', 'EMEA', 1200],
      ['Globex', 'APAC', 980],
    ],
    search: true,
    sort: true,
    pagination: { limit: 10 },
  }).render(document.getElementById('grid'));
</script>
```

## Types
```ts
declare namespace gridjs {
  class Grid {
    constructor(config: {
      columns: Array<string | { name: string; formatter?: (cell: unknown) => unknown }>;
      data: unknown[][] | (() => Promise<unknown[][]>);
      search?: boolean;
      sort?: boolean;
      pagination?: { limit: number };
    });
    render(container: HTMLElement): Grid;
  }
}
```
