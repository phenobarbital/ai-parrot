<script lang="ts">
  import { browser } from '$app/environment';
  import '$lib/styles/revogrid-theme.css';
  import Icon from '@iconify/svelte';
  import type { ColumnRegular, ColumnGrouping, CellTemplate } from '@revolist/svelte-datagrid';
  import { GridState } from './grid-state.svelte';
  import { buildRollUpRow, type AggregationType } from './formulas';
  import { stringifyCellValue } from './cell-format';

  interface Props {
    data?: Record<string, unknown>[];
    columns?: string[];
    persistKey: string;
    tenantPrefix?: string;
    /**
     * When true, column headers show the raw column name exactly as returned
     * (e.g. `column_name`) instead of the prettified "Title Case" version.
     * Used by querysource (executor/slug) and pipelines.
     */
    rawHeaders?: boolean;
    onExport?: (format: 'csv' | 'json' | 'xlsx', blob: Blob, filename: string) => void;
    onCreateChart?: (rows: Record<string, unknown>[], config: { selectedColumn?: string }) => void;
    onCellEdited?: (event: { rowIndex: number; prop: string; value: unknown }) => void;
    onColumnSelect?: (prop: string | null) => void;
  }

  let {
    data,
    columns,
    persistKey,
    tenantPrefix,
    rawHeaders = false,
    onExport,
    onCreateChart,
    onCellEdited,
    onColumnSelect,
  }: Props = $props();

  const gridState = new GridState({ persistKey, tenantPrefix });
  let RevoGrid = $state<any>(null);
  let exportDropdownOpen = $state(false);
  let groupBtnEl = $state<HTMLButtonElement | null>(null);
  let sigmaBtnEl = $state<HTMLButtonElement | null>(null);
  let exportBtnEl = $state<HTMLButtonElement | null>(null);
  let gridWrapperEl = $state<HTMLDivElement | null>(null);

  /** Right-click copy menu — resolved from the DOM cell/header under the cursor. */
  interface CopyTarget {
    x: number;
    y: number;
    kind: 'cell' | 'header';
    prop: string;
    label: string;
    value: string;
    row: Record<string, unknown> | null;
  }
  let copyMenu = $state<CopyTarget | null>(null);
  let copyFeedback = $state<string | null>(null);

  /**
   * Per-column width overrides in px, keyed by column prop. Set by the "expand
   * to fit" action and by manual drag-resizes, so neither is undone the next
   * time the column defs are re-derived.
   */
  let columnWidthOverrides = $state<Record<string, number>>({});

  $effect(() => {
    if (browser && !RevoGrid) {
      import('@revolist/svelte-datagrid').then((mod) => {
        RevoGrid = mod.RevoGrid;
      });
    }
  });

  $effect(() => {
    gridState.resetRows(Array.isArray(data) ? [...data] : []);
  });

  // Column fonts can only be read once RevoGrid has painted its first cells.
  // Flipping this re-derives the columns, so the expand buttons settle on real
  // measurements instead of the character-count estimate used for first paint.
  $effect(() => {
    if (!browser || metricsReady || !RevoGrid || !gridState.hasData) return;
    let frame = 0;
    let attempts = 0;
    const poll = () => {
      if (ensureMetrics()) {
        metricsReady = true;
        return;
      }
      if (attempts++ < 60) frame = requestAnimationFrame(poll);
    };
    frame = requestAnimationFrame(poll);
    return () => cancelAnimationFrame(frame);
  });

  $effect(() => {
    if (browser) {
      document.addEventListener('click', handleClickOutside);
      document.addEventListener('keydown', handleKeydown);
      return () => {
        document.removeEventListener('click', handleClickOutside);
        document.removeEventListener('keydown', handleKeydown);
      };
    }
  });

  // RevoGrid's own copy/sorting events — both cancelable, both need to yield to
  // a manual text selection. Listeners go on the wrapper in the CAPTURE phase:
  // `beforesorting` is emitted by the sorting plugin with `bubbles: false`, so a
  // bubble-phase listener on an ancestor would never see it. The context menu is
  // wired here too (rather than as an attribute) since the wrapper is a plain div.
  $effect(() => {
    const el = gridWrapperEl;
    if (!el) return;
    el.addEventListener('beforecopy', handleBeforeCopy, true);
    el.addEventListener('beforesorting', handleBeforeSorting, true);
    el.addEventListener('aftercolumnresize', handleColumnResize, true);
    el.addEventListener('contextmenu', handleGridContextMenu);
    return () => {
      el.removeEventListener('beforecopy', handleBeforeCopy, true);
      el.removeEventListener('beforesorting', handleBeforeSorting, true);
      el.removeEventListener('aftercolumnresize', handleColumnResize, true);
      el.removeEventListener('contextmenu', handleGridContextMenu);
    };
  });

  let flatColumns = $derived<ColumnRegular[]>(deriveFlatColumns(gridState.localRows, gridState.dragEnabled));

  let computedColumnDefs = $derived<ColumnRegular[]>(
    gridState.computedColumns.map((cc) => ({
      prop: cc.prop,
      name: cc.label,
      sortable: true,
      size: columnWidthOverrides[cc.prop] ?? DEFAULT_COL_WIDTH,
      readonly: true,
    })),
  );

  let rollUpPinnedRows = $derived<Record<string, unknown>[]>(
    gridState.rollUpRows.length > 0
      ? [buildRollUpRow(gridState.localRows, gridState.rollUpRows, gridState.columnKeys)]
      : [],
  );

  // What the grid export will actually contain — shown in the export dropdown
  // so the difference vs. the raw-results Export menu is self-evident.
  let exportSummary = $derived.by(() => {
    const rows = gridState.displayRows.length;
    const cols = gridState.columnKeys.length;
    const computed = gridState.computedColumns.length;
    const rollUps = gridState.rollUpRows.length;
    let s = `${rows} rows · ${cols} cols`;
    if (computed) s += ` + ${computed} computed`;
    if (rollUps) s += ` · ${rollUps} roll-up${rollUps > 1 ? 's' : ''}`;
    return s;
  });

  let gridColumns = $derived<(ColumnGrouping | ColumnRegular)[]>([
    ...(gridState.groupingEnabled && gridState.groupParentCol && gridState.groupChildCols.size > 0
      ? buildGroupedColumns(flatColumns, gridState.groupParentCol, gridState.groupChildCols)
      : flatColumns),
    ...computedColumnDefs,
  ]);

  // Leaf column order as RevoGrid renders it — `data-rgCol` on a cell/header is
  // an index into this list, which is how the copy menu maps a DOM element back
  // to its column (grouped columns render their children first).
  let leafColumns = $derived<ColumnRegular[]>(
    gridColumns.flatMap((col) =>
      'children' in col && Array.isArray(col.children)
        ? (col.children as ColumnRegular[])
        : [col as ColumnRegular],
    ),
  );

  const AGG_TYPES: AggregationType[] = ['sum', 'average', 'min', 'max', 'count', 'distinct_count'];
  const AGG_LABELS: Record<AggregationType, string> = {
    sum: 'Sum',
    average: 'Average',
    min: 'Min',
    max: 'Max',
    count: 'Count',
    distinct_count: 'Distinct Count',
  };

  // Render every value through the shared serializer so objects show compact
  // JSON instead of "[object Object]". Must return strings — returning a bare
  // `false` from a template renders an empty cell.
  const objectAwareCellTemplate: CellTemplate = (_h, { value }) => stringifyCellValue(value);

  // Content-aware column widths (Redash-like): size each column to its longest
  // sampled value, clamped so one huge JSON blob can't take over the viewport.
  // Uses the same serializer the cells render with, so jsonb columns measure
  // their JSON text — not "[object Object]" (which is why RevoGrid's own
  // autoSizeColumn plugin can't be used here).
  const CHAR_PX = 8;
  const CELL_PADDING_PX = 24;
  const MIN_COL_WIDTH = 90;
  const MAX_COL_WIDTH = 420;
  const DEFAULT_COL_WIDTH = 150;
  const SIZE_SAMPLE_ROWS = 50;
  // "Expand to fit" scans further than the initial sizing pass — it runs for a
  // single column on demand, so a wider sample is affordable.
  const FIT_SAMPLE_ROWS = 5000;
  const FIT_FALLBACK_MAX_WIDTH = 1200;
  // Extra room for the expand button that sits next to a truncated header label
  const FIT_BUTTON_PX = 36;
  const FIT_SLACK_PX = 8;

  /** Width the content wants, unclamped. */
  function measuredWidth(
    source: Record<string, unknown>[],
    key: string,
    sampleRows: number,
  ): number {
    let maxChars = formatHeader(key).length;
    const n = Math.min(source.length, sampleRows);
    for (let i = 0; i < n; i++) {
      const len = stringifyCellValue(source[i][key]).length;
      if (len > maxChars) maxChars = len;
    }
    return Math.max(MIN_COL_WIDTH, maxChars * CHAR_PX + CELL_PADDING_PX);
  }

  function contentAwareWidth(source: Record<string, unknown>[], key: string): number {
    return Math.min(MAX_COL_WIDTH, measuredWidth(source, key, SIZE_SAMPLE_ROWS));
  }

  // Full text as a native tooltip on the cell div, only when it can't fit the
  // column — truncated JSON, emails and long strings alike.
  const truncationTooltipProps: ColumnRegular['cellProperties'] = ({ value, column }) => {
    const text = stringifyCellValue(value);
    const size = typeof column?.size === 'number' ? column.size : DEFAULT_COL_WIDTH;
    return text.length * CHAR_PX + CELL_PADDING_PX > size ? { title: text } : {};
  };

  // ---------------------------------------------------------------------------
  // Column width — "expand to fit"
  //
  // Columns start clamped at MAX_COL_WIDTH so one long JSON blob can't take over
  // the viewport, which leaves wide values rendered as "…". Every column in that
  // state grows an expand button in its header that widens it to the full value
  // (capped at the visible grid width), and back again.
  // ---------------------------------------------------------------------------

  /**
   * Text measurement against the fonts the grid actually renders with.
   *
   * The character-count heuristic above overestimates a proportional font by
   * roughly a quarter. That is harmless while the width is clamped, but once a
   * column is expanded to fit it shows up as dead space after the value — so
   * "expand" measures the real text on a canvas instead. Metrics are read from
   * rendered cells, hence only available after the grid has painted.
   */
  interface TextMetrics2d {
    font: string;
    letterSpacing: number;
    uppercase: boolean;
  }
  let measureCtx: CanvasRenderingContext2D | null = null;
  let cellMetrics: TextMetrics2d | null = null;
  let headerMetrics: TextMetrics2d | null = null;
  /** Flips once the grid has painted and the real fonts can be read. */
  let metricsReady = $state(false);

  function readMetrics(el: HTMLElement): TextMetrics2d {
    const style = getComputedStyle(el);
    const letterSpacing = parseFloat(style.letterSpacing);
    return {
      font: `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`,
      letterSpacing: Number.isFinite(letterSpacing) ? letterSpacing : 0,
      uppercase: style.textTransform === 'uppercase',
    };
  }

  function ensureMetrics(): boolean {
    if (cellMetrics && headerMetrics) return true;
    const cell = gridWrapperEl?.querySelector('.rgCell') as HTMLElement | null;
    const header = gridWrapperEl?.querySelector('.rgHeaderCell') as HTMLElement | null;
    if (!cell || !header) return false;
    cellMetrics = readMetrics(cell);
    headerMetrics = readMetrics(header);
    return true;
  }

  function textWidth(text: string, metrics: TextMetrics2d): number {
    if (!measureCtx) measureCtx = document.createElement('canvas').getContext('2d');
    if (!measureCtx) return text.length * CHAR_PX;
    const value = metrics.uppercase ? text.toUpperCase() : text;
    measureCtx.font = metrics.font;
    return measureCtx.measureText(value).width + value.length * metrics.letterSpacing;
  }

  /** Widest rendered value in the column, padding included. */
  function preciseContentWidth(
    source: Record<string, unknown>[],
    key: string,
    sampleRows: number,
  ): number | null {
    if (!metricsReady || !cellMetrics) return null;
    const n = Math.min(source.length, sampleRows);
    let widest = 0;
    for (let i = 0; i < n; i++) {
      const w = textWidth(stringifyCellValue(source[i][key]), cellMetrics);
      if (w > widest) widest = w;
    }
    return Math.ceil(widest) + CELL_PADDING_PX;
  }

  /**
   * Does the column actually clip its content at the given width?
   *
   * Measured for real whenever possible: the character-count heuristic reports
   * roughly a quarter more than the text occupies, which would flag columns that
   * fit perfectly well and hand them a pointless expand button.
   */
  function contentOverflows(
    source: Record<string, unknown>[],
    key: string,
    width: number,
  ): boolean {
    const precise = preciseContentWidth(source, key, SIZE_SAMPLE_ROWS);
    return (precise ?? measuredWidth(source, key, SIZE_SAMPLE_ROWS)) > width;
  }

  /** Exact width the column needs, or null while the grid has not painted yet. */
  function preciseFitWidth(key: string): number | null {
    const content = preciseContentWidth(gridState.displayRows, key, FIT_SAMPLE_ROWS);
    if (content == null || !headerMetrics) return null;
    // The header has to fit its label plus the expand button next to it
    const header = textWidth(formatHeader(key), headerMetrics) + FIT_BUTTON_PX + CELL_PADDING_PX;
    // FIT_SLACK_PX covers the cell border and subpixel rounding — landing exactly
    // on the text width still renders an ellipsis.
    return Math.ceil(Math.max(content, header)) + FIT_SLACK_PX;
  }

  /** Width the column is currently rendered at. */
  function columnWidth(key: string): number {
    return columnWidthOverrides[key] ?? contentAwareWidth(gridState.localRows, key);
  }

  function isColumnTruncated(key: string): boolean {
    return contentOverflows(gridState.localRows, key, columnWidth(key));
  }

  /** Full width for a column, capped so it never overflows the visible grid. */
  function fitWidthFor(key: string): number {
    const needed =
      preciseFitWidth(key) ??
      measuredWidth(gridState.displayRows, key, FIT_SAMPLE_ROWS) + FIT_BUTTON_PX;
    const viewport = gridWrapperEl?.clientWidth ?? 0;
    const cap = Math.max(MAX_COL_WIDTH, viewport > 0 ? viewport - 24 : FIT_FALLBACK_MAX_WIDTH);
    return Math.max(MIN_COL_WIDTH, Math.min(needed, cap));
  }

  let truncatedColumns = $derived<string[]>(
    gridState.hasData ? gridState.columnKeys.filter((key) => isColumnTruncated(key)) : [],
  );
  let hasWidthOverrides = $derived(Object.keys(columnWidthOverrides).length > 0);

  function fitColumn(key: string) {
    columnWidthOverrides = { ...columnWidthOverrides, [key]: fitWidthFor(key) };
    copyMenu = null;
  }

  function resetColumnWidth(key: string) {
    const { [key]: _removed, ...rest } = columnWidthOverrides;
    columnWidthOverrides = rest;
    copyMenu = null;
  }

  function fitAllTruncatedColumns() {
    const next = { ...columnWidthOverrides };
    for (const key of truncatedColumns) next[key] = fitWidthFor(key);
    columnWidthOverrides = next;
  }

  function resetAllColumnWidths() {
    columnWidthOverrides = {};
  }

  function handleColumnResize(e: Event) {
    // Remember drag-resized widths so re-deriving the column defs doesn't snap
    // them back to the content-aware default.
    const detail = (e as CustomEvent<Record<number, ColumnRegular>>).detail;
    if (!detail) return;
    const next = { ...columnWidthOverrides };
    for (const column of Object.values(detail)) {
      if (column?.prop != null && typeof column.size === 'number') {
        next[String(column.prop)] = column.size;
      }
    }
    columnWidthOverrides = next;
  }

  /** Header renderer for columns that are (or were) too narrow for their content. */
  function fitHeaderTemplate(key: string, label: string): ColumnRegular['columnTemplate'] {
    return (createElement) => {
      const expanded = columnWidthOverrides[key] != null;
      // Arrows point outward to expand and inward to collapse — the state reads
      // from the glyph, so the button itself can stay in the grid's neutral tones.
      const icon = createElement(
        'svg',
        { viewBox: '0 0 24 24', width: '15', height: '15', 'aria-hidden': 'true' },
        [
          createElement('path', {
            fill: 'currentColor',
            d: expanded
              ? 'M11 5h2v14h-2z M3 7.5L8 12l-5 4.5z M21 7.5L16 12l5 4.5z'
              : 'M11 5h2v14h-2z M3 12l5-4.5v9z M21 12l-5-4.5v9z',
          }),
        ],
      );
      const button = createElement(
        'button',
        {
          type: 'button',
          class: `rg-fit-btn${expanded ? ' is-active' : ''}`,
          title: expanded ? 'Reset column width' : 'Expand column to fit content',
          // preventDefault stops the header click from sorting and the mousedown
          // from starting a column drag — both bail out on it.
          onMouseDown: (e: MouseEvent) => {
            e.preventDefault();
            e.stopPropagation();
          },
          onClick: (e: MouseEvent) => {
            e.preventDefault();
            e.stopPropagation();
            if (expanded) resetColumnWidth(key);
            else fitColumn(key);
          },
        },
        [icon],
      );
      return createElement('span', { class: 'rg-header-fit' }, [
        createElement('span', { class: 'rg-header-label' }, label),
        button,
      ]);
    };
  }

  function deriveFlatColumns(
    source: Record<string, unknown>[],
    drag: boolean,
  ): ColumnRegular[] {
    if (!source.length) return [];
    const keys = Object.keys(source[0]);
    return keys.map((key, i) => {
      const label = formatHeader(key);
      const size = columnWidthOverrides[key] ?? contentAwareWidth(source, key);
      const needsFitButton =
        columnWidthOverrides[key] != null || contentOverflows(source, key, size);
      return {
        prop: key,
        name: label,
        sortable: true,
        size,
        cellTemplate: objectAwareCellTemplate,
        cellProperties: truncationTooltipProps,
        ...(needsFitButton ? { columnTemplate: fitHeaderTemplate(key, label) } : {}),
        ...(drag && i === 0 ? { rowDrag: true } : {}),
      };
    });
  }

  function buildGroupedColumns(
    flat: ColumnRegular[],
    parentCol: string,
    childCols: Set<string>,
  ): (ColumnGrouping | ColumnRegular)[] {
    const children: ColumnRegular[] = [];
    const ungrouped: ColumnRegular[] = [];
    for (const col of flat) {
      if (col.prop === parentCol || childCols.has(col.prop as string)) {
        children.push(col);
      } else {
        ungrouped.push(col);
      }
    }
    if (children.length === 0) return flat;
    const group: ColumnGrouping = { name: formatHeader(parentCol), children };
    return [group, ...ungrouped];
  }

  function formatHeader(key: string): string {
    if (rawHeaders) return key;
    return key
      .replace(/_/g, ' ')
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }

  function handleGroupToggle() {
    gridState.groupingEnabled = !gridState.groupingEnabled;
    if (!gridState.groupingEnabled) {
      gridState.groupDropdownOpen = false;
      gridState.clearGrouping();
    } else {
      gridState.groupDropdownOpen = true;
    }
  }

  function handleAfterEdit(e: CustomEvent) {
    const detail = e.detail;
    if (!detail) return;
    if ('prop' in detail && 'val' in detail && 'rowIndex' in detail) {
      const { prop, rowIndex, val } = detail;
      if (rowIndex >= 0 && rowIndex < gridState.localRows.length) {
        gridState.localRows[rowIndex] = { ...gridState.localRows[rowIndex], [prop]: val };
      }
      onCellEdited?.({ rowIndex, prop, value: val });
    } else if ('data' in detail && detail.data) {
      const edits = detail.data as Record<number, Record<string, unknown>>;
      for (const [idx, values] of Object.entries(edits)) {
        const rowIdx = Number(idx);
        if (rowIdx >= 0 && rowIdx < gridState.localRows.length) {
          gridState.localRows[rowIdx] = { ...gridState.localRows[rowIdx], ...values };
        }
      }
    }
  }

  function handleRowOrderChanged(e: CustomEvent) {
    const detail = e.detail;
    if (!detail) return;
    if ('from' in detail && 'to' in detail) {
      const from = detail.from as number;
      const to = detail.to as number;
      if (
        from >= 0 &&
        from < gridState.localRows.length &&
        to >= 0 &&
        to <= gridState.localRows.length
      ) {
        const updated = [...gridState.localRows];
        const [moved] = updated.splice(from, 1);
        updated.splice(to > from ? to - 1 : to, 0, moved);
        gridState.localRows = updated;
      }
    }
  }

  function handleAfterFocus(e: CustomEvent) {
    const detail = e.detail;
    if (!detail) return;
    const rowIndex = 'rowIndex' in detail ? (detail.rowIndex as number) : -1;
    const prop = 'prop' in detail ? (detail.prop as string) : '';
    const colIndex = 'colIndex' in detail ? (detail.colIndex as number) : -1;
    gridState.handleAfterFocus(rowIndex, prop, colIndex);
    onColumnSelect?.(prop ?? null);
  }

  function handleFormulaKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault();
      gridState.submitFormula();
    }
  }

  function handleClickOutside(e: MouseEvent) {
    const target = e.target as HTMLElement;
    if (!target.isConnected) return;

    if (copyMenu && !target.closest('#grid-copy-menu')) {
      copyMenu = null;
    }

    if (gridState.groupDropdownOpen) {
      const dropdown = document.getElementById('grouping-dropdown');
      if (
        dropdown &&
        !dropdown.contains(target) &&
        groupBtnEl &&
        !groupBtnEl.contains(target)
      ) {
        gridState.groupDropdownOpen = false;
      }
    }

    if (gridState.sigmaDropdownOpen) {
      const dropdown = document.getElementById('sigma-dropdown');
      if (
        dropdown &&
        !dropdown.contains(target) &&
        sigmaBtnEl &&
        !sigmaBtnEl.contains(target)
      ) {
        gridState.sigmaDropdownOpen = false;
        gridState.sigmaStep = 'menu';
        gridState.sigmaAction = null;
        gridState.sigmaAggType = null;
      }
    }

    if (exportDropdownOpen) {
      const dropdown = document.getElementById('export-dropdown');
      if (
        dropdown &&
        !dropdown.contains(target) &&
        exportBtnEl &&
        !exportBtnEl.contains(target)
      ) {
        exportDropdownOpen = false;
      }
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      if (copyMenu) copyMenu = null;
      if (gridState.groupDropdownOpen) gridState.groupDropdownOpen = false;
      if (gridState.sigmaDropdownOpen) {
        if (gridState.sigmaStep === 'column-select') {
          gridState.cancelSigma();
        } else {
          gridState.sigmaDropdownOpen = false;
        }
      }
      if (exportDropdownOpen) exportDropdownOpen = false;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
      e.preventDefault();
      gridState.toggleFormulaBar();
    }
  }

  // ---------------------------------------------------------------------------
  // Copy & text selection
  //
  // Two independent paths, because neither covers everything on its own:
  //   1. Native selection — the theme re-enables `user-select` so the user can
  //      highlight part of a value (or a column name) with the mouse. Ctrl+C is
  //      intercepted by RevoGrid's clipboard plugin, so `beforecopy` is
  //      cancelled whenever a hand-made selection exists (see handleBeforeCopy).
  //   2. Right-click menu — whole cell / row / column / table, tab-separated so
  //      it pastes straight into Excel or Sheets. Reads from the data model, not
  //      the DOM, so virtualized (off-screen) rows and columns are included.
  // ---------------------------------------------------------------------------

  const COL_SEP = '\t';
  const COPY_MENU_ITEM =
    'flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-accent/50 disabled:cursor-not-allowed disabled:opacity-50';
  const COPY_MENU_WIDTH = 224;
  const COPY_MENU_HEIGHT = 344;

  // Keep the menu inside the viewport when right-clicking near an edge.
  let copyMenuPos = $derived.by(() => {
    if (!copyMenu || !browser) return { left: 0, top: 0 };
    return {
      left: Math.max(8, Math.min(copyMenu.x, window.innerWidth - COPY_MENU_WIDTH - 8)),
      top: Math.max(8, Math.min(copyMenu.y, window.innerHeight - COPY_MENU_HEIGHT - 8)),
    };
  });

  function copyColumnDefs(): { prop: string; label: string }[] {
    return [
      ...gridState.columnKeys.map((key) => ({ prop: key, label: formatHeader(key) })),
      ...gridState.computedColumns.map((cc) => ({ prop: cc.prop, label: cc.label })),
    ];
  }

  function hasManualSelection(): boolean {
    if (!browser) return false;
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.anchorNode) return false;
    return !!gridWrapperEl?.contains(selection.anchorNode);
  }

  function handleBeforeCopy(e: Event) {
    // RevoGrid's clipboard plugin swallows every document copy and replaces the
    // payload with the focused cell. When the user highlighted text by hand,
    // cancel it so the browser copies exactly what is selected.
    if (hasManualSelection()) e.preventDefault();
  }

  function handleBeforeSorting(e: Event) {
    // A drag that selects header text ends with a click on the header, which
    // would otherwise re-sort the grid behind the user's back.
    if (hasManualSelection()) e.preventDefault();
  }

  function showCopyFeedback(message: string) {
    copyFeedback = message;
    setTimeout(() => {
      if (copyFeedback === message) copyFeedback = null;
    }, 1600);
  }

  async function copyToClipboard(text: string, message: string) {
    copyMenu = null;
    try {
      await navigator.clipboard.writeText(text);
      showCopyFeedback(message);
    } catch {
      // Clipboard API is unavailable on insecure origins — fall back to the
      // legacy execCommand path before giving up.
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      const ok = document.execCommand('copy');
      textarea.remove();
      showCopyFeedback(ok ? message : 'Copy failed');
    }
  }

  function resolveCopyTarget(e: MouseEvent): CopyTarget | null {
    const origin = e.target as HTMLElement | null;
    if (!origin) return null;
    const headerEl = origin.closest('.rgHeaderCell');
    const cellEl = headerEl ? null : origin.closest('.rgCell');
    const anchor = (headerEl ?? cellEl) as HTMLElement | null;
    if (!anchor) return null;

    const colIndex = Number(anchor.getAttribute('data-rgCol'));
    const column = Number.isInteger(colIndex) ? leafColumns[colIndex] : undefined;
    if (!column?.prop) return null;
    const prop = String(column.prop);
    const label = String(column.name ?? prop);

    if (headerEl) {
      return { x: e.clientX, y: e.clientY, kind: 'header', prop, label, value: label, row: null };
    }

    const rowIndex = Number(anchor.getAttribute('data-rgRow'));
    const source =
      anchor.closest('revogr-data')?.getAttribute('type') === 'rowPinEnd'
        ? rollUpPinnedRows
        : gridState.displayRows;
    const row = (Number.isInteger(rowIndex) ? source[rowIndex] : null) ?? null;
    return {
      x: e.clientX,
      y: e.clientY,
      kind: 'cell',
      prop,
      label,
      value: row ? stringifyCellValue(row[prop]) : '',
      row,
    };
  }

  function handleGridContextMenu(e: MouseEvent) {
    const target = resolveCopyTarget(e);
    if (!target) return;
    e.preventDefault();
    copyMenu = target;
  }

  function copyColumnValues(prop: string, label: string, withHeader: boolean) {
    const values = gridState.displayRows.map((row) => stringifyCellValue(row[prop]));
    const lines = withHeader ? [label, ...values] : values;
    copyToClipboard(lines.join('\n'), `Copied ${values.length} value${values.length !== 1 ? 's' : ''}`);
  }

  function copyRow(row: Record<string, unknown>, withHeaders: boolean) {
    const defs = copyColumnDefs();
    const values = defs.map((def) => stringifyCellValue(row[def.prop])).join(COL_SEP);
    const text = withHeaders
      ? `${defs.map((def) => def.label).join(COL_SEP)}\n${values}`
      : values;
    copyToClipboard(text, 'Row copied');
  }

  function copyTable() {
    const defs = copyColumnDefs();
    const lines = [defs.map((def) => def.label).join(COL_SEP)];
    for (const row of [...gridState.displayRows, ...rollUpPinnedRows]) {
      lines.push(defs.map((def) => stringifyCellValue(row[def.prop])).join(COL_SEP));
    }
    copyToClipboard(lines.join('\n'), `Copied ${lines.length - 1} rows`);
  }

  function handleCreateChart() {
    const selectedColumn =
      gridState.selectedCol >= 0 ? gridState.columnKeys[gridState.selectedCol] : undefined;
    onCreateChart?.(gridState.displayRows, { selectedColumn });
  }

  function triggerDownload(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  function exportCsv() {
    if (!gridState.localRows.length) return;
    const origKeys = gridState.columnKeys;
    const computedProps = gridState.computedColumns.map((cc) => cc.prop);
    const allProps = [...origKeys, ...computedProps];
    const origHeaders = origKeys.map(formatHeader);
    const computedHeaders = gridState.computedColumns.map((cc) => cc.label);
    const header = [...origHeaders, ...computedHeaders].join(',');

    function escapeCell(val: unknown): string {
      const s = stringifyCellValue(val);
      return s.includes(',') || s.includes('"') ? `"${s.replace(/"/g, '""')}"` : s;
    }

    const csvRows = gridState.displayRows.map((row) =>
      allProps.map((k) => escapeCell(row[k])).join(','),
    );
    for (const ru of rollUpPinnedRows) {
      csvRows.push(allProps.map((k) => escapeCell(ru[k])).join(','));
    }
    const csv = [header, ...csvRows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const filename = `results-${new Date().toISOString()}.csv`;
    onExport?.('csv', blob, filename);
    triggerDownload(blob, filename);
  }

  function exportJson() {
    const blob = new Blob([JSON.stringify(gridState.displayRows, null, 2)], {
      type: 'application/json',
    });
    const filename = `results-${new Date().toISOString()}.json`;
    onExport?.('json', blob, filename);
    triggerDownload(blob, filename);
  }

  async function exportXlsx() {
    const mod = await import('exceljs');
    const ExcelJS = (mod as any).default ?? mod;
    const wb = new ExcelJS.Workbook();
    const ws = wb.addWorksheet('Results');
    const allKeys = [
      ...gridState.columnKeys,
      ...gridState.computedColumns.map((c) => c.prop),
    ];
    ws.columns = allKeys.map((key) => ({
      header: formatHeader(key),
      key,
      width: 18,
    }));
    gridState.displayRows.forEach((row) => {
      const flat: Record<string, unknown> = {};
      for (const key of allKeys) {
        const v = row[key];
        flat[key] = v != null && typeof v === 'object' ? stringifyCellValue(v) : v;
      }
      ws.addRow(flat);
    });
    const buffer = await wb.xlsx.writeBuffer();
    const blob = new Blob([buffer], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    const filename = `results-${new Date().toISOString()}.xlsx`;
    onExport?.('xlsx', blob, filename);
    triggerDownload(blob, filename);
  }
</script>

<div class="relative flex h-full min-h-0 flex-col overflow-hidden">
  <!-- Toolbar -->
  <div
    class="flex shrink-0 items-center gap-1 border-b border-border bg-muted/20 px-3 py-1.5"
  >
    <span class="text-xs text-muted-foreground">
      {gridState.localRows.length} row{gridState.localRows.length !== 1 ? 's' : ''} &middot;
      {flatColumns.length} column{flatColumns.length !== 1 ? 's' : ''}
    </span>

    <div class="flex-1"></div>

    <!-- Edit toggle -->
    <button
      class="btn btn-ghost btn-xs gap-1 {gridState.editMode
        ? 'bg-accent text-accent-foreground'
        : 'text-muted-foreground hover:text-foreground'}"
      onclick={() => gridState.toggleEdit()}
      disabled={!gridState.hasData}
      title={gridState.editMode ? 'Disable cell editing' : 'Enable cell editing'}
    >
      <Icon icon={gridState.editMode ? 'mdi:pencil' : 'mdi:pencil-off'} class="size-3.5" />
    </button>

    <!-- Drag toggle -->
    <button
      class="btn btn-ghost btn-xs gap-1 {gridState.dragEnabled
        ? 'bg-accent text-accent-foreground'
        : 'text-muted-foreground hover:text-foreground'}"
      onclick={() => gridState.toggleDrag()}
      disabled={!gridState.hasData}
      title={gridState.dragEnabled ? 'Disable row drag & drop' : 'Enable row drag & drop'}
    >
      <Icon icon="mdi:drag" class="size-3.5" />
    </button>

    <!-- Filter toggle -->
    <button
      class="btn btn-ghost btn-xs gap-1 {gridState.filterEnabled
        ? 'bg-accent text-accent-foreground'
        : 'text-muted-foreground hover:text-foreground'}"
      onclick={() => gridState.toggleFilter()}
      disabled={!gridState.hasData}
      title={gridState.filterEnabled ? 'Disable column filters' : 'Enable column filters'}
    >
      <Icon
        icon={gridState.filterEnabled ? 'mdi:filter' : 'mdi:filter-off'}
        class="size-3.5"
      />
    </button>

    <!-- Expand truncated columns -->
    <button
      class="btn btn-ghost btn-xs gap-1 {hasWidthOverrides
        ? 'bg-accent text-accent-foreground'
        : 'text-muted-foreground hover:text-foreground'}"
      onclick={() => (hasWidthOverrides ? resetAllColumnWidths() : fitAllTruncatedColumns())}
      disabled={!gridState.hasData || (!hasWidthOverrides && truncatedColumns.length === 0)}
      title={hasWidthOverrides
        ? 'Reset all column widths'
        : `Expand truncated columns to fit content (${truncatedColumns.length})`}
    >
      <Icon
        icon={hasWidthOverrides ? 'mdi:arrow-collapse-horizontal' : 'mdi:arrow-expand-horizontal'}
        class="size-3.5"
      />
    </button>

    <!-- Grouping dropdown -->
    <div class="relative">
      <button
        bind:this={groupBtnEl}
        class="btn btn-ghost btn-xs gap-1 {gridState.groupingEnabled
          ? 'bg-accent text-accent-foreground'
          : 'text-muted-foreground hover:text-foreground'}"
        onclick={handleGroupToggle}
        disabled={!gridState.hasData}
        title={gridState.groupingEnabled ? 'Disable column grouping' : 'Enable column grouping'}
      >
        <Icon icon="mdi:format-columns" class="size-3.5" />
      </button>

      {#if gridState.groupDropdownOpen && gridState.groupingEnabled}
        <div
          id="grouping-dropdown"
          class="absolute right-0 top-full z-50 mt-1 w-56 rounded-md border border-border bg-popover p-2 shadow-md"
        >
          <div class="mb-2 text-xs font-medium text-muted-foreground">
            Group columns under:
          </div>
          <div class="max-h-48 space-y-0.5 overflow-y-auto">
            {#each gridState.columnKeys as key}
              {@const isParent = gridState.groupParentCol === key}
              {@const isChild =
                gridState.groupParentCol !== null &&
                key !== gridState.groupParentCol &&
                gridState.groupChildCols.has(key)}
              <button
                class="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-accent/50 {isParent
                  ? 'bg-accent font-medium text-accent-foreground'
                  : ''}"
                onclick={() => gridState.selectParentCol(key)}
              >
                <Icon
                  icon={isParent
                    ? 'mdi:folder-open'
                    : isChild
                      ? 'mdi:subdirectory-arrow-right'
                      : 'mdi:table-column'}
                  class="size-3.5 shrink-0"
                />
                <span class="truncate">{formatHeader(key)}</span>
                {#if isParent}
                  <Icon icon="mdi:check" class="ml-auto size-3 shrink-0 text-primary" />
                {/if}
              </button>

              {#if gridState.groupParentCol !== null && key !== gridState.groupParentCol}
                <label
                  class="flex w-full cursor-pointer items-center gap-2 pl-7 text-xs"
                >
                  <input
                    type="checkbox"
                    checked={gridState.groupChildCols.has(key)}
                    onchange={() => gridState.toggleChildCol(key)}
                    class="size-3 rounded"
                  />
                  <span class="text-[11px] text-muted-foreground">Include in group</span>
                </label>
              {/if}
            {/each}
          </div>
          <div class="mt-2 flex gap-1 border-t border-border pt-2">
            <button
              class="btn btn-ghost btn-xs flex-1 text-xs"
              onclick={() => gridState.clearGrouping()}
            >
              Clear
            </button>
            <button
              class="btn btn-ghost btn-xs flex-1 text-xs"
              onclick={() => {
                gridState.groupDropdownOpen = false;
              }}
            >
              Done
            </button>
          </div>
        </div>
      {/if}
    </div>

    <!-- Formula bar toggle -->
    <button
      class="btn btn-ghost btn-xs gap-1 {gridState.formulaBarVisible
        ? 'bg-accent text-accent-foreground'
        : 'text-muted-foreground hover:text-foreground'}"
      onclick={() => gridState.toggleFormulaBar()}
      disabled={!gridState.hasData}
      title={gridState.formulaBarVisible ? 'Hide formula bar' : 'Show formula bar'}
    >
      <Icon icon="mdi:function" class="size-3.5" />
    </button>

    <!-- Sigma dropdown -->
    <div class="relative">
      <button
        bind:this={sigmaBtnEl}
        class="btn btn-ghost btn-xs gap-1 {gridState.computedColumns.length > 0 ||
        gridState.rollUpRows.length > 0
          ? 'bg-accent text-accent-foreground'
          : 'text-muted-foreground hover:text-foreground'}"
        onclick={() => {
          gridState.sigmaDropdownOpen = !gridState.sigmaDropdownOpen;
          if (!gridState.sigmaDropdownOpen) {
            gridState.sigmaStep = 'menu';
            gridState.sigmaAction = null;
            gridState.sigmaAggType = null;
          }
        }}
        disabled={!gridState.hasData}
        title="Computed columns & roll-up rows"
      >
        <Icon icon="mdi:sigma" class="size-3.5" />
      </button>

      {#if gridState.sigmaDropdownOpen}
        <div
          id="sigma-dropdown"
          class="absolute right-0 top-full z-50 mt-1 w-64 rounded-md border border-border bg-popover p-2 shadow-md"
        >
          {#if gridState.sigmaStep === 'menu'}
            {#if gridState.computedColumns.length > 0 || gridState.rollUpRows.length > 0}
              <div class="mb-2">
                <div class="mb-1 px-1 text-xs font-medium text-muted-foreground">Active</div>
                {#each gridState.computedColumns as cc}
                  <div
                    class="flex items-center justify-between rounded px-2 py-0.5 text-xs hover:bg-accent/30"
                  >
                    <span class="truncate text-foreground">{cc.label}</span>
                    <button
                      class="ml-1 shrink-0 text-muted-foreground hover:text-destructive"
                      onclick={() => gridState.removeComputedColumn(cc.id)}
                      title="Remove"
                    >
                      <Icon icon="mdi:close" class="size-3" />
                    </button>
                  </div>
                {/each}
                {#each gridState.rollUpRows as ru}
                  <div
                    class="flex items-center justify-between rounded px-2 py-0.5 text-xs hover:bg-accent/30"
                  >
                    <span class="truncate text-foreground">{ru.label}</span>
                    <button
                      class="ml-1 shrink-0 text-muted-foreground hover:text-destructive"
                      onclick={() => gridState.removeRollUpRow(ru.id)}
                      title="Remove"
                    >
                      <Icon icon="mdi:close" class="size-3" />
                    </button>
                  </div>
                {/each}
              </div>
              <div class="mb-2 border-t border-border"></div>
            {/if}

            <div class="mb-1 px-1 text-xs font-medium text-muted-foreground">
              Add Computed Column
            </div>
            {#each AGG_TYPES as aggType}
              <button
                class="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-accent/50"
                onclick={() => gridState.openSigmaColumnSelect('computed', aggType)}
              >
                <Icon
                  icon="mdi:table-column-plus-after"
                  class="size-3.5 shrink-0 text-muted-foreground"
                />
                {AGG_LABELS[aggType]}
              </button>
            {/each}

            <div class="my-2 border-t border-border"></div>

            <div class="mb-1 px-1 text-xs font-medium text-muted-foreground">
              Add Roll-Up Row
            </div>
            {#each AGG_TYPES as aggType}
              <button
                class="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-accent/50"
                onclick={() => gridState.openSigmaColumnSelect('rollup', aggType)}
              >
                <Icon
                  icon="mdi:table-row-plus-after"
                  class="size-3.5 shrink-0 text-muted-foreground"
                />
                {AGG_LABELS[aggType]}
              </button>
            {/each}

            {#if gridState.computedColumns.length > 0 || gridState.rollUpRows.length > 0}
              <div class="mt-2 border-t border-border pt-2">
                <button
                  class="btn btn-ghost btn-xs w-full text-xs text-destructive hover:bg-destructive/10"
                  onclick={() => gridState.clearAllComputed()}
                >
                  Clear All
                </button>
              </div>
            {/if}
          {:else}
            <!-- Column select step -->
            <div class="mb-2 flex items-center gap-1">
              <button
                class="text-muted-foreground hover:text-foreground"
                onclick={() => gridState.cancelSigma()}
              >
                <Icon icon="mdi:arrow-left" class="size-3.5" />
              </button>
              <div class="text-xs font-medium text-foreground">
                {gridState.sigmaAction === 'computed'
                  ? `Select columns for ${AGG_LABELS[gridState.sigmaAggType!]}`
                  : `Select column for ${AGG_LABELS[gridState.sigmaAggType!]}`}
              </div>
            </div>

            <div class="mb-2 max-h-48 space-y-0.5 overflow-y-auto">
              {#each gridState.columnKeys as key}
                <label
                  class="flex w-full cursor-pointer items-center gap-2 rounded px-2 py-1 text-xs hover:bg-accent/50"
                >
                  <input
                    type={gridState.sigmaAction === 'computed' ? 'checkbox' : 'radio'}
                    name="sigma-col"
                    checked={gridState.sigmaSelectedCols.has(key)}
                    onchange={() => gridState.toggleSigmaColumn(key)}
                    class="size-3 rounded"
                  />
                  <span class="truncate">{formatHeader(key)}</span>
                </label>
              {/each}
            </div>

            <div class="flex gap-1 border-t border-border pt-2">
              <button
                class="btn btn-ghost btn-xs flex-1 text-xs"
                onclick={() => gridState.cancelSigma()}
              >
                Cancel
              </button>
              <button
                class="btn btn-primary btn-xs flex-1 text-xs"
                disabled={gridState.sigmaSelectedCols.size === 0}
                onclick={() => gridState.applySigma()}
              >
                Apply
              </button>
            </div>
          {/if}
        </div>
      {/if}
    </div>

    <!-- Separator -->
    <div class="h-4 w-px bg-border"></div>

    <!-- Create chart -->
    <button
      class="btn btn-ghost btn-xs gap-1 text-muted-foreground hover:text-foreground"
      onclick={handleCreateChart}
      disabled={!gridState.hasData}
      title="Create chart"
    >
      <Icon icon="mdi:chart-line" class="size-3.5" />
    </button>

    <!-- Export dropdown -->
    <div class="relative">
      <button
        bind:this={exportBtnEl}
        class="btn btn-ghost btn-xs gap-1 text-muted-foreground hover:text-foreground"
        onclick={() => (exportDropdownOpen = !exportDropdownOpen)}
        disabled={!gridState.hasData}
        title="Export data"
      >
        <Icon icon="mdi:download" class="size-3.5" />
      </button>

      {#if exportDropdownOpen}
        <div
          id="export-dropdown"
          class="absolute right-0 top-full z-50 mt-1 w-56 rounded-md border border-border bg-popover p-2 shadow-md"
        >
          <div class="px-2 pb-1.5">
            <p class="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Current grid view
            </p>
            <p class="text-[10px] text-muted-foreground/70">{exportSummary}</p>
          </div>
          <button
            class="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-accent/50"
            onclick={() => {
              exportCsv();
              exportDropdownOpen = false;
            }}
          >
            <Icon icon="mdi:file-delimited" class="size-3.5 shrink-0 text-muted-foreground" />
            CSV (grid view)
          </button>
          <button
            class="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-accent/50"
            onclick={() => {
              exportJson();
              exportDropdownOpen = false;
            }}
          >
            <Icon icon="mdi:code-json" class="size-3.5 shrink-0 text-muted-foreground" />
            JSON (grid view)
          </button>
          <button
            class="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-accent/50"
            onclick={() => {
              exportXlsx();
              exportDropdownOpen = false;
            }}
          >
            <Icon icon="mdi:file-excel" class="size-3.5 shrink-0 text-muted-foreground" />
            Excel (grid view)
          </button>
        </div>
      {/if}
    </div>
  </div>

  <!-- Formula bar -->
  {#if gridState.formulaBarVisible && gridState.hasData}
    <div
      class="flex shrink-0 items-center gap-2 border-b border-border bg-muted/10 px-3 py-1"
    >
      <span class="w-8 shrink-0 text-center font-mono text-xs text-muted-foreground">
        {gridState.selectedCellRef || '—'}
      </span>
      <div class="h-4 w-px bg-border"></div>
      <input
        class="input input-xs flex-1 border-none bg-transparent font-mono text-xs focus:outline-none focus:ring-0"
        placeholder="Enter value or formula (e.g., =SUM(A1:A10))"
        bind:value={gridState.formulaInput}
        onkeydown={handleFormulaKeydown}
      />
      <button
        class="btn btn-ghost btn-xs text-muted-foreground hover:text-foreground"
        onclick={() => gridState.submitFormula()}
        title="Apply formula"
        disabled={gridState.selectedRow < 0}
      >
        <Icon icon="mdi:check" class="size-3.5" />
      </button>
    </div>
  {/if}

  <!-- Grid -->
  <div class="min-h-0 flex-1 overflow-hidden">
    {#if !gridState.hasData}
      <div class="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
        <div class="rounded-full bg-base-200 p-4">
          <Icon icon="lucide:table-2" class="h-8 w-8 text-base-content/30" />
        </div>
        <p class="text-sm font-medium text-base-content/50">No data to display</p>
      </div>
    {:else if browser && RevoGrid}
      <div
        bind:this={gridWrapperEl}
        class="h-full w-full"
        class:border-t-2={gridState.editMode}
        class:border-primary={gridState.editMode}
        class:rg-raw-headers={rawHeaders}
      >
        <RevoGrid
          source={gridState.displayRows}
          pinnedBottomSource={rollUpPinnedRows}
          columns={gridColumns}
          readonly={!gridState.editMode}
          resize={true}
          filter={gridState.filterEnabled}
          stretch={false}
          theme="compact"
          style="height: 100%; width: 100%;"
          on:afteredit={handleAfterEdit}
          on:roworderchanged={handleRowOrderChanged}
          on:afterfocus={handleAfterFocus}
        />
      </div>
    {:else}
      <!-- Fallback table while RevoGrid loads -->
      <div class="h-full overflow-auto">
        <table class="w-full text-xs">
          <thead class="sticky top-0 bg-muted/50">
            <tr>
              {#each flatColumns as col}
                <th
                  class="whitespace-nowrap border-b border-border px-3 py-2 text-left font-medium text-muted-foreground"
                >
                  {col.name}
                </th>
              {/each}
              {#each computedColumnDefs as col}
                <th
                  class="whitespace-nowrap border-b border-border px-3 py-2 text-left font-medium text-primary/70"
                >
                  {col.name}
                </th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each gridState.displayRows.slice(0, 100) as row, i}
              <tr class={i % 2 === 0 ? 'bg-card' : 'bg-muted/20'}>
                {#each flatColumns as col}
                  <td class="whitespace-nowrap border-b border-border px-3 py-1.5">
                    {row[col.prop] ?? ''}
                  </td>
                {/each}
                {#each computedColumnDefs as col}
                  <td
                    class="whitespace-nowrap border-b border-border px-3 py-1.5 text-primary/80"
                  >
                    {row[col.prop] ?? ''}
                  </td>
                {/each}
              </tr>
            {/each}
            {#each rollUpPinnedRows as row}
              <tr class="border-t-2 border-border bg-muted/40 font-bold">
                {#each flatColumns as col}
                  <td class="whitespace-nowrap border-b border-border px-3 py-1.5">
                    {row[col.prop] ?? ''}
                  </td>
                {/each}
                {#each computedColumnDefs as col}
                  <td class="whitespace-nowrap border-b border-border px-3 py-1.5">
                    {row[col.prop] ?? ''}
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </div>

  <!-- Copy feedback -->
  {#if copyFeedback}
    <div
      class="pointer-events-none absolute bottom-3 right-3 z-50 rounded-md border border-border bg-popover px-2.5 py-1 text-xs text-foreground shadow-md"
    >
      {copyFeedback}
    </div>
  {/if}
</div>

<!-- Right-click copy menu (cells and column headers) -->
{#if copyMenu}
  <div
    id="grid-copy-menu"
    class="fixed z-[60] w-56 rounded-md border border-border bg-popover p-1 shadow-lg"
    style="left: {copyMenuPos.left}px; top: {copyMenuPos.top}px;"
  >
    <!-- Raw label, not uppercased: it is the exact string "Copy column name" writes -->
    <div class="truncate px-2 py-1 text-[10px] font-medium text-muted-foreground">
      {copyMenu.label}
    </div>

    {#if copyMenu.kind === 'cell'}
      <button
        class={COPY_MENU_ITEM}
        onclick={() => copyToClipboard(copyMenu!.value, 'Cell copied')}
      >
        <Icon icon="mdi:content-copy" class="size-3.5 shrink-0 text-muted-foreground" />
        Copy cell value
      </button>
      <button
        class={COPY_MENU_ITEM}
        disabled={!copyMenu.row}
        onclick={() => copyMenu?.row && copyRow(copyMenu.row, false)}
      >
        <Icon icon="mdi:table-row" class="size-3.5 shrink-0 text-muted-foreground" />
        Copy row
      </button>
      <button
        class={COPY_MENU_ITEM}
        disabled={!copyMenu.row}
        onclick={() => copyMenu?.row && copyRow(copyMenu.row, true)}
      >
        <Icon icon="mdi:table-row-plus-before" class="size-3.5 shrink-0 text-muted-foreground" />
        Copy row with headers
      </button>
      <div class="my-1 border-t border-border"></div>
    {/if}

    {#if columnWidthOverrides[copyMenu.prop] != null}
      <button class={COPY_MENU_ITEM} onclick={() => resetColumnWidth(copyMenu!.prop)}>
        <Icon icon="mdi:arrow-collapse-horizontal" class="size-3.5 shrink-0 text-muted-foreground" />
        Reset column width
      </button>
    {:else}
      <button
        class={COPY_MENU_ITEM}
        disabled={!isColumnTruncated(copyMenu.prop)}
        onclick={() => fitColumn(copyMenu!.prop)}
      >
        <Icon icon="mdi:arrow-expand-horizontal" class="size-3.5 shrink-0 text-muted-foreground" />
        Expand column to fit
      </button>
    {/if}

    <div class="my-1 border-t border-border"></div>

    <button
      class={COPY_MENU_ITEM}
      onclick={() => copyToClipboard(copyMenu!.label, 'Column name copied')}
    >
      <Icon icon="mdi:format-title" class="size-3.5 shrink-0 text-muted-foreground" />
      Copy column name
    </button>
    <button
      class={COPY_MENU_ITEM}
      onclick={() => copyColumnValues(copyMenu!.prop, copyMenu!.label, false)}
    >
      <Icon icon="mdi:table-column" class="size-3.5 shrink-0 text-muted-foreground" />
      Copy column values
    </button>
    <button
      class={COPY_MENU_ITEM}
      onclick={() => copyColumnValues(copyMenu!.prop, copyMenu!.label, true)}
    >
      <Icon icon="mdi:table-column-plus-before" class="size-3.5 shrink-0 text-muted-foreground" />
      Copy column with header
    </button>

    <div class="my-1 border-t border-border"></div>

    <button
      class={COPY_MENU_ITEM}
      onclick={() =>
        copyToClipboard(
          copyColumnDefs()
            .map((def) => def.label)
            .join(COL_SEP),
          'Column names copied',
        )}
    >
      <Icon icon="mdi:format-list-bulleted" class="size-3.5 shrink-0 text-muted-foreground" />
      Copy all column names
    </button>
    <button class={COPY_MENU_ITEM} onclick={copyTable}>
      <Icon icon="mdi:table-large" class="size-3.5 shrink-0 text-muted-foreground" />
      Copy whole table
    </button>
  </div>
{/if}

<style>
  /* When raw headers are requested, keep the original column name casing
     instead of the theme's uppercase transform (querysource / pipelines). */
  :global(.rg-raw-headers revo-grid[theme='compact'] .rgHeaderCell) {
    text-transform: none;
  }
</style>
