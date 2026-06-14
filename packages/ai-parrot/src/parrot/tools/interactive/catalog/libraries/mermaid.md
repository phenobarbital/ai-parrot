---
name: mermaid
description: Render flowcharts, sequence, gantt, class, state and ER diagrams from plain text.
category: diagram
scope: cdn
url: https://cdn.jsdelivr.net/npm/mermaid@10.9.3/dist/mermaid.min.js
sri_hash: sha384-REGENERATEMEREGENERATEMEREGENERATEMEREGENERATEMEREGENERATEME
global_var: mermaid
---

## Usage
```html
<pre class="mermaid">
flowchart TD
  A[Start] --> B{Decision}
  B -- Yes --> C[Do thing]
  B -- No  --> D[Skip]
</pre>
<script>
  mermaid.initialize({ startOnLoad: true, theme: 'default' });
</script>
```

## Types
```ts
declare const mermaid: {
  initialize(config: { startOnLoad?: boolean; theme?: string }): void;
  run(opts?: { querySelector?: string }): Promise<void>;
};
```
