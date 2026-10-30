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

  export type C4Level = 'context' | 'container' | 'component' | 'dynamic';
  export type C4ElementType = 'person' | 'person_ext' | 'system' | 'system_ext' | 'system_db' | 'system_db_ext'
    | 'system_queue' | 'system_queue_ext' | 'container' | 'container_ext' | 'container_db' | 'container_db_ext'
    | 'container_queue' | 'container_queue_ext' | 'component' | 'component_ext' | 'component_db'
    | 'component_db_ext' | 'component_queue' | 'component_queue_ext';
  export type C4BoundaryType = 'enterprise' | 'system' | 'container' | 'generic';
  export type RelHint = 'up' | 'down' | 'left' | 'right' | 'back';
  export interface BoundaryFrame { id: string; label: string; depth: number; x: number; y: number; w: number; h: number }

  export interface GraphNodeProps {
    id: string;
    label?: string;
    shape?: string;
    group?: string;
    state?: GraphNodeState;
    icon?: string;
    meta?: Record<string, unknown>;
    c4Type?: C4ElementType;
    technology?: string;
    description?: string;
  }

  export interface GraphEdgeProps {
    from: string;
    to: string;
    label?: string;
    kind?: 'solid' | 'dashed' | 'thick';
    condition?: string;
    technology?: string;
    hint?: RelHint;
    bidirectional?: boolean;
  }

  export interface GraphGroupProps {
    id: string;
    label?: string;
    nodes: string[];
    parent?: string;
    c4Type?: C4BoundaryType;
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
    shapeInRow?: number;
    boundaryInRow?: number;
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
    level?: C4Level;
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

  /** ECharts symbol + caption + external flag for a C4 element type (table in spec §3 M6). */
  export function c4SymbolFor(c4Type: C4ElementType | undefined): { symbol: string; caption: string; external: boolean } {
    const t = c4Type ?? '';
    const external = t.endsWith('_ext');
    if (t.startsWith('person')) return { symbol: 'circle', caption: 'Person', external };
    if (t.includes('_db')) return { symbol: 'roundRect', caption: '[DB]', external };
    if (t.includes('_queue')) return { symbol: 'rect', caption: '[Queue]', external };
    return { symbol: 'rect', caption: '', external };
  }

  const BOUNDARY_PADDING = 20;

  /** Nested boundary frames from member positions (mirror of the backend's `_group_boxes`), in abstract
   * layout coordinates; [] unless positions are complete. Each frame is the union of its member node
   * positions and its child frames, padded by 20 per side; parents are returned before children. */
  export function computeBoundaryFrames(properties: GraphProperties): BoundaryFrame[] {
    if (!hasCompletePositions(properties)) return [];
    const positions = properties.layout?.positions ?? {};
    const groups = properties.groups ?? [];
    const byId = new Map(groups.map((group) => [group.id, group]));

    const depthOf = (group: GraphGroupProps): number => {
      let depth = 0;
      const seen = new Set<string>([group.id]);
      let parent = group.parent ? byId.get(group.parent) : undefined;
      while (parent && !seen.has(parent.id)) {
        seen.add(parent.id);
        depth += 1;
        parent = parent.parent ? byId.get(parent.parent) : undefined;
      }
      return depth;
    };

    const boxes = new Map<string, { x0: number; y0: number; x1: number; y1: number } | null>();
    const boxFor = (group: GraphGroupProps, visiting: Set<string>) => {
      if (boxes.has(group.id)) return boxes.get(group.id) ?? null;
      visiting.add(group.id);
      const xs: number[] = [];
      const ys: number[] = [];
      for (const member of group.nodes) {
        const position = positions[member];
        if (position) {
          xs.push(position.x - BOUNDARY_PADDING, position.x + BOUNDARY_PADDING);
          ys.push(position.y - BOUNDARY_PADDING, position.y + BOUNDARY_PADDING);
        }
      }
      for (const child of groups) {
        if (child.parent !== group.id || visiting.has(child.id)) continue;
        const childBox = boxFor(child, visiting);
        if (childBox) {
          xs.push(childBox.x0 - BOUNDARY_PADDING, childBox.x1 + BOUNDARY_PADDING);
          ys.push(childBox.y0 - BOUNDARY_PADDING, childBox.y1 + BOUNDARY_PADDING);
        }
      }
      visiting.delete(group.id);
      const box = xs.length ? { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) } : null;
      boxes.set(group.id, box);
      return box;
    };

    const frames: BoundaryFrame[] = [];
    for (const group of groups) {
      const box = boxFor(group, new Set());
      if (!box) continue;
      const name = group.label ?? group.id;
      frames.push({
        id: group.id,
        label: group.c4Type ? `${name} [${group.c4Type} boundary]` : name,
        depth: depthOf(group),
        x: box.x0,
        y: box.y0,
        w: box.x1 - box.x0,
        h: box.y1 - box.y0,
      });
    }
    return frames.sort((a, b) => a.depth - b.depth);
  }

  function c4TooltipText(node: GraphNodeProps): string {
    const lines = [node.label ?? node.id];
    if (node.c4Type) lines.push(node.c4Type);
    if (node.technology) lines.push(node.technology);
    if (node.description) lines.push(node.description);
    const metaLines = tooltipText({ ...node, label: '' }).split('\n').slice(1);
    return [...lines, ...metaLines].join('\n');
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
    const isC4 = properties.kind === 'c4';
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
      if (isC4) {
        const { symbol, caption, external } = c4SymbolFor(node.c4Type);
        const name = node.label ?? node.id;
        entry.symbol = symbol;
        entry.tooltip = { formatter: () => c4TooltipText(node) };
        const lines = [caption ? `${caption}\n${name}` : name];
        if (node.technology) lines.push(`[${node.technology}]`);
        entry.label = { show: true, formatter: lines.join('\n') };
        if (external) {
          entry.itemStyle = { ...(entry.itemStyle as Record<string, unknown>), borderType: 'dashed', borderWidth: 2 };
        }
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
      if (isC4) {
        if (edge.bidirectional) link.symbol = ['arrow', 'arrow'];
        if (edge.technology) {
          link.label = { show: true, formatter: edge.label ? `${edge.label} [${edge.technology}]` : `[${edge.technology}]` };
        }
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
  export const C4_FRAME_ID_PREFIX = 'c4-frame-';

  /**
   * Project abstract boundary frames into viewport-pixel `graphic` elements.
   *
   * @param convert - Maps an abstract layout point to pixels (the live chart's `convertToPixel`).
   * @param frames - Frames from `computeBoundaryFrames`, in abstract layout coordinates.
   * @returns Silent, unfilled rect + text elements placed behind the graph; frames with
   *   non-finite projected corners are skipped.
   */
  export function projectFrames(
    convert: (pt: [number, number]) => number[] | undefined,
    frames: BoundaryFrame[],
  ): Record<string, unknown>[] {
    const elements: Record<string, unknown>[] = [];
    for (const frame of frames) {
      const a = convert([frame.x, frame.y]);
      const b = convert([frame.x + frame.w, frame.y + frame.h]);
      if (!a || !b || ![a[0], a[1], b[0], b[1]].every((v) => Number.isFinite(v))) continue;
      const x0 = Math.min(a[0], b[0]);
      const y0 = Math.min(a[1], b[1]);
      const x1 = Math.max(a[0], b[0]);
      const y1 = Math.max(a[1], b[1]);
      elements.push({
        id: `${C4_FRAME_ID_PREFIX}${frame.id}`,
        type: 'rect',
        silent: true,
        z: -10 + frame.depth,
        shape: { x: x0, y: y0, width: x1 - x0, height: y1 - y0 },
        style: { fill: 'none', stroke: '#888', lineWidth: 1, lineDash: [6, 4] },
      });
      elements.push({
        id: `${C4_FRAME_ID_PREFIX}${frame.id}-label`,
        type: 'text',
        silent: true,
        z: -10 + frame.depth,
        x: x0 + 4,
        y: y0 + 4,
        style: { text: frame.label, fill: '#666', fontSize: 11 },
      });
    }
    return elements;
  }

  /** Minimal chart surface the frame lifecycle needs (a subset of `echarts.EChartsType`). */
  export interface FrameChart {
    on(event: string, handler: () => void): void;
    off(event: string, handler: () => void): void;
    convertToPixel(finder: { seriesIndex: number }, value: [number, number]): number[] | undefined;
    setOption(option: Record<string, unknown>): void;
    getOption(): Record<string, unknown> | undefined;
  }

  function ownedGraphicIds(chart: FrameChart): Set<string> {
    const ids = new Set<string>();
    const graphic = chart.getOption()?.graphic;
    const list = Array.isArray(graphic) ? graphic : graphic ? [graphic] : [];
    for (const g of list as Record<string, unknown>[]) {
      const children = Array.isArray(g?.elements) ? (g.elements as Record<string, unknown>[]) : [g];
      for (const el of children) {
        const id = el?.id;
        if (typeof id === 'string' && id.startsWith(C4_FRAME_ID_PREFIX)) ids.add(id);
      }
    }
    return ids;
  }

  /**
   * Subscribe a live chart to boundary-frame reprojection on `rendered`/`graphRoam`.
   *
   * Updates are coalesced into one animation frame; `setOption` is issued only when the
   * projected geometry/labels change or owned ids went missing, so the `rendered` event the
   * write causes never loops.
   *
   * @param chart - The live chart instance.
   * @param getProperties - Returns the CURRENT graph properties (never a captured snapshot).
   * @param raf - Frame scheduler (defaults to `requestAnimationFrame`).
   * @param caf - Frame canceller (defaults to `cancelAnimationFrame`).
   * @returns Cleanup that unregisters both events and cancels any pending frame.
   */
  export function attachFrameProjection(
    chart: FrameChart,
    getProperties: () => GraphProperties,
    raf: (cb: () => void) => number = (cb) => requestAnimationFrame(cb),
    caf: (handle: number) => void = (handle) => cancelAnimationFrame(handle),
  ): () => void {
    let frame = 0;
    let lastKey = '';
    let written = new Set<string>();
    const update = () => {
      const properties = getProperties();
      const frames = properties.kind === 'c4' ? computeBoundaryFrames(properties) : [];
      const elements = projectFrames((p) => chart.convertToPixel({ seriesIndex: 0 }, p), frames);
      const key = JSON.stringify(elements);
      const present = ownedGraphicIds(chart);
      const ids = new Set(elements.map((el) => el.id as string));
      const missing = [...ids].some((id) => !present.has(id));
      const stale = [...new Set([...present, ...written])].filter((id) => !ids.has(id) && present.has(id));
      if (key === lastKey && !missing && stale.length === 0) return;
      const graphic = [...stale.map((id) => ({ id, $action: 'remove' })), ...elements];
      lastKey = key;
      written = ids;
      if (graphic.length) chart.setOption({ graphic });
    };
    const schedule = () => {
      if (frame) return;
      frame = raf(() => {
        frame = 0;
        update();
      });
    };
    chart.on('rendered', schedule);
    chart.on('graphRoam', schedule);
    schedule();
    return () => {
      chart.off('rendered', schedule);
      chart.off('graphRoam', schedule);
      if (frame) caf(frame);
      frame = 0;
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

  /** Mounted-chart hook: projects C4 boundary frames through the live viewport. */
  function handleChartReady(chart: unknown): () => void {
    return attachFrameProjection(chart as FrameChart, () => properties);
  }

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
  <ECharts options={option} onChartReady={handleChartReady} />
</div>
