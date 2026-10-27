<script module lang="ts">
  /** The MermaidDiagram component's own (already-resolved) top-level props. Mirrors MERMAIDDIAGRAM_SCHEMA. */
  export interface MermaidDiagramProperties {
    source: string;
    diagramType?: string;
    title?: string;
    caption?: string;
    theme?: 'default' | 'neutral' | 'dark' | 'forest' | 'base';
    accessibleDescription?: string;
  }

  type MermaidTheme = 'default' | 'neutral' | 'dark' | 'forest' | 'base';
  const THEMES: readonly MermaidTheme[] = ['default', 'neutral', 'dark', 'forest', 'base'];

  /** Pure: the wire `theme` hint wins, else 'dark' on a dark host, else 'default'. */
  export function resolveMermaidTheme(hint: string | undefined, hostIsDark: boolean): MermaidTheme {
    if (hint && (THEMES as readonly string[]).includes(hint)) return hint as MermaidTheme;
    return hostIsDark ? 'dark' : 'default';
  }

  let renderCounter = 0;
  let mermaidPromise: Promise<typeof import('mermaid').default> | undefined;
  function loadMermaid() {
    mermaidPromise ??= import('mermaid').then((m) => m.default);
    return mermaidPromise;
  }
</script>

<script lang="ts">
  import DOMPurify from 'dompurify';
  import { themeStore } from '$lib/stores/theme.svelte';

  let { properties }: { properties: MermaidDiagramProperties } = $props();
  let status = $state<'loading' | 'ready' | 'error'>('loading');
  let svgHtml = $state('');

  $effect(() => {
    const source = properties.source;
    const theme = resolveMermaidTheme(properties.theme, themeStore.isDark);
    let cancelled = false;
    (async () => {
      try {
        const mermaid = await loadMermaid();
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme,
          htmlLabels: false,
          flowchart: { htmlLabels: false },
          class: { htmlLabels: false },
        });
        await mermaid.parse(source);
        const { svg } = await mermaid.render(`a2ui-mermaid-${++renderCounter}`, source);
        if (cancelled) return;
        svgHtml = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } });
        status = 'ready';
      } catch {
        if (!cancelled) status = 'error';
      }
    })();
    return () => {
      cancelled = true;
    };
  });
</script>

{#if status === 'ready'}
  {#if properties.title}
    <h3 class="text-sm font-semibold mb-1">{properties.title}</h3>
  {/if}
  <figure role="img" aria-label={properties.accessibleDescription ?? 'Mermaid diagram'}>
    {@html svgHtml}
    {#if properties.caption}
      <figcaption class="text-xs text-muted-foreground mt-2">{properties.caption}</figcaption>
    {/if}
  </figure>
{:else if status === 'error'}
  <div class="text-sm text-destructive">
    <p>Diagram could not be rendered</p>
    <pre class="text-xs mt-2"><code>{properties.source}</code></pre>
  </div>
{:else}
  <div class="text-sm text-muted-foreground">Loading diagram...</div>
{/if}

<details class="mt-2">
  <summary class="text-xs text-muted-foreground cursor-pointer select-none">Mermaid source</summary>
  <pre class="text-xs mt-1"><code>{properties.source}</code></pre>
</details>
