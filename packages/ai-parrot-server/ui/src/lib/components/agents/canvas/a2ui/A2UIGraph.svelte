<script module lang="ts">
  // ai-parrot (FEAT-529): pure ECharts-option-building logic, exported from
  // this module block so it is directly unit-testable (no rendering, no
  // ECharts/canvas involved) — mirrors the backend's
  // `parrot.outputs.a2ui_renderers.echarts.EChartsRenderer._build_graph_option`
  // and shares its `STATE_TO_STATUS` role mapping
  // (`parrot.outputs.a2ui_renderers._graph_svg.STATE_TO_STATUS`), but this
  // app has no `--accent-green`/`--accent-amber`/`--accent-red`/
  // `--neutral-muted` CSS custom properties of its own (see
  // `src/lib/styles/themes/_schema.css`) — the closest existing shadcn/
  // Tailwind tokens are used instead (`--chart-2`, `--chart-3`,
  // `--destructive`, `--primary`, `--muted-foreground`).

  export type GraphNodeState =
    | 'pending'
    | 'running'
    | 'completed'
    | 'failed'
    | 'skipped'
    | 'waiting';

  export interface GraphNodeProps {
    id: string;
    label?: string;
    shape?: string;
    group?: string;
    state?: GraphNodeState;
    icon?: string;
    meta?: Record<string, unknown>;
  }

  export interface GraphEdgeProps {
    from: string;
    to: string;
    label?: string;
    kind?: 'solid' | 'dashed' | 'thick';
    condition?: string;
  }

  export interface GraphGroupProps {
    id: string;
    label?: string;
    nodes: string[];
  }

  export interface GraphPosition {
    x: number;
    y: number;
  }

  export interface GraphLayoutProps {
    engine?: 'layered' | 'force' | 'manual';
    rankSep?: number;
    nodeSep?: number;
    positions?: Record<string, GraphPosition>;
  }

  export interface GraphSelectionProps {
    selectable?: boolean;
    selected?: string;
  }

  /** The `Graph` component's own (already-resolved) top-level props — never
   * the wire envelope's `id`/`component`/`catalogId`. */
  export interface GraphProperties {
    kind?: string;
    direction?: string;
    title?: string;
    accessibleDescription?: string;
    size?: 'inline' | 'tile' | 'hero';
    nodes: GraphNodeProps[];
    edges: GraphEdgeProps[];
    groups?: GraphGroupProps[];
    layout?: GraphLayoutProps;
    selection?: GraphSelectionProps;
  }

  /** Node domain `state` -> viz-core semantic status role (spec §2 renderer
   * contract) — identical mapping to the backend's `STATE_TO_STATUS`. */
  export const STATE_TO_STATUS: Record<GraphNodeState, string> = {
    completed: 'good',
    waiting: 'warning',
    failed: 'critical',
    running: 'primary',
    pending: 'neutral',
    skipped: 'neutral',
  };

  const STATUS_ORDER = ['good', 'warning', 'critical', 'primary', 'neutral'] as const;

  /** Status role -> this app's own CSS custom-property NAME (never a
   * literal colour) — resolved to a concrete value at render time by the
   * caller (Canvas rendering cannot resolve `var()` itself; see
   * `resolveColor` below / `AppChart.svelte`'s identical precedent). */
  const STATUS_TO_TOKEN: Record<string, string> = {
    good: 'var(--chart-2)',
    warning: 'var(--chart-3)',
    critical: 'var(--destructive)',
    primary: 'var(--primary)',
    neutral: 'var(--muted-foreground)',
  };

  /** True when `properties.layout.positions` covers every node — the ONLY
   * condition under which `layout: "none"` (server-prepared positions) is
   * used; otherwise ECharts' own `"circular"` layout is the fallback. */
  export function hasCompletePositions(properties: GraphProperties): boolean {
    const positions = properties.layout?.positions;
    if (!positions) return false;
    return properties.nodes.every((node) => positions[node.id] !== undefined);
  }

  function statusForNode(node: GraphNodeProps): string {
    return node.state ? (STATE_TO_STATUS[node.state] ?? 'neutral') : 'neutral';
  }

  function tooltipText(node: GraphNodeProps): string {
    const label = node.label ?? node.id;
    if (!node.meta) return label;
    const metaLines = Object.entries(node.meta).map(([key, value]) => `${key}: ${String(value)}`);
    return [label, ...metaLines].join('\n');
  }

  /**
   * Build a native ECharts `graph` series option from `Graph` properties.
   *
   * @param properties - The (already-resolved) `Graph` component props.
   * @param resolveColor - Resolves a `var(--token)` string to a concrete
   *   colour usable by the Canvas renderer; identity by default (tests
   *   don't need a live DOM to assert on the token names themselves).
   */
  export function buildGraphOption(
    properties: GraphProperties,
    resolveColor: (token: string) => string = (token) => token,
  ): Record<string, unknown> {
    const usePositions = hasCompletePositions(properties);
    const positions = properties.layout?.positions ?? {};

    const data = properties.nodes.map((node) => {
      const status = statusForNode(node);
      const entry: Record<string, unknown> = {
        id: node.id,
        name: node.label ?? node.id,
        category: STATUS_ORDER.indexOf(status as (typeof STATUS_ORDER)[number]),
        tooltip: { formatter: () => tooltipText(node) },
        itemStyle: { color: resolveColor(STATUS_TO_TOKEN[status] ?? STATUS_TO_TOKEN.neutral) },
      };
      if (node.group) {
        entry.value = node.group; // groups are represented on the node's own data (spec: "groups ... represented")
      }
      if (properties.selection?.selected === node.id) {
        entry.itemStyle = {
          ...(entry.itemStyle as Record<string, unknown>),
          borderColor: resolveColor('var(--ring)'),
          borderWidth: 3,
        };
        entry.symbolSize = 14; // slightly larger — visually distinguishes the selection
      }
      if (usePositions) {
        const position = positions[node.id];
        entry.x = position.x;
        entry.y = position.y;
      }
      return entry;
    });

    const links = properties.edges.map((edge) => {
      const lineStyle: Record<string, unknown> = {};
      if (edge.kind === 'dashed') lineStyle.type = 'dashed';
      if (edge.kind === 'thick') lineStyle.width = 3;
      const link: Record<string, unknown> = { source: edge.from, target: edge.to, lineStyle };
      if (edge.label) {
        link.label = { show: true, formatter: edge.label };
      }
      return link;
    });

    return {
      title: { text: properties.title ?? '' },
      tooltip: { show: true },
      series: [
        {
          type: 'graph',
          layout: usePositions ? 'none' : 'circular',
          roam: true,
          label: { show: true },
          edgeSymbol: ['none', 'arrow'],
          categories: STATUS_ORDER.map((name) => ({ name })),
          data,
          links,
        },
      ],
    };
  }
</script>

<script lang="ts">
  import { browser } from '$app/environment';
  import ECharts from '$lib/components/visualizations/ECharts.svelte';

  interface Props {
    properties: GraphProperties;
    dataModel?: Record<string, unknown>;
    /** Node click hook — NOT wired to any action-dispatch transport yet
     * (spec §7: that is `a2ui-live-workflow-surface`'s job). Declared so
     * callers have a stable extension point; a no-op if never invoked. */
    onNodeClick?: (nodeId: string, nodeLabel?: string) => void;
  }

  // `dataModel`/`onNodeClick` are accepted for a stable prop surface but
  // deliberately unused today: `Graph.data` (live overlay) resolution and
  // node-click action dispatch are both out of scope here (see the Props
  // doc above and this module's top comment).
  let { properties }: Props = $props();

  /** Resolve a `var(--token)` string to a concrete rgb value via a probe
   * element — the Canvas layer's fillStyle cannot resolve CSS variables
   * (identical precedent: `AppChart.svelte`'s own `resolveColor`). */
  function resolveColor(color: string): string {
    if (!browser || !color.includes('var(')) return color;
    const probe = document.createElement('span');
    probe.style.color = color;
    probe.style.display = 'none';
    document.body.appendChild(probe);
    const resolved = getComputedStyle(probe).color;
    probe.remove();
    return resolved || color;
  }

  let option = $derived(buildGraphOption(properties, resolveColor));

  let sizeClass = $derived(
    properties.size === 'inline'
      ? 'a2ui-graph-inline'
      : properties.size === 'hero'
        ? 'a2ui-graph-hero'
        : 'a2ui-graph-tile',
  );
</script>

<div
  class={`a2ui-graph ${sizeClass}`}
  role="img"
  aria-label={properties.accessibleDescription ?? `Graph of ${properties.nodes.length} nodes`}
>
  <ECharts options={option} />
</div>
