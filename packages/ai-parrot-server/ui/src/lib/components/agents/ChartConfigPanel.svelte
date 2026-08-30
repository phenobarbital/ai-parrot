<script lang="ts">
	import Icon from "@iconify/svelte";
	import { AppToggle } from "$lib/ui/components";
	// ai-parrot (FEAT-476 TASK-2595): Badge/Separator aren't re-exported from
	// $lib/ui/components (TASK-2593 trimmed that barrel to only the App*
	// wrappers) — every shadcn primitive already exists in the Admin UI's
	// own internal shadcn tree and is imported from there directly.
	import { Badge } from "$lib/ui/internal/shadcn/ui/badge";
	import { Separator } from "$lib/ui/internal/shadcn/ui/separator";
	import DataChart from "./DataChart.svelte";
	import {
		chartTypes,
		getChartType,
		type ChartTypeDefinition,
	} from "./chart-types";

	/**
	 * Temporary chart configuration shape.
	 */
	export interface ChartTempConfig {
		type: string;
		x: string;
		y: string[];
		stacked: boolean;
		trendline: boolean;
		median: boolean;
		splitSeries: boolean;
		title: string;
		showLegend: boolean;
		xAxisMode: "category" | "time";
		/** Map-specific: columns shown in marker popup tooltip */
		mapLabelColumns?: string[];
		/** Map-specific: column for latitude */
		mapLatColumn?: string;
		/** Map-specific: column for longitude */
		mapLngColumn?: string;
		/** Map-specific: marker pin color */
		mapMarkerColor?: string;
	}

	interface Props {
		open: boolean;
		columns: string[];
		previewData?: Record<string, any>[];
		config: ChartTempConfig;
		onclose: () => void;
		onadd: (config: ChartTempConfig) => void;
	}

	let { open, columns, previewData = [], config = $bindable(), onclose, onadd }: Props = $props();

	// Derived: currently selected chart type definition
	let selectedChartDef = $derived<ChartTypeDefinition | undefined>(
		getChartType(config.type),
	);

	// Derived: available columns for Y-axis (excludes already selected)
	let availableYColumns = $derived(
		columns.filter((col) => !config.y.includes(col)),
	);

	// Derived: available columns for map tooltip (excludes already selected)
	let availableMapLabelColumns = $derived(
		columns.filter((c) => !(config.mapLabelColumns || []).includes(c)),
	);

	// Preview: can we show a chart preview?
	let canPreview = $derived(
		selectedChartDef?.axisMode !== "map" &&
		previewData.length > 0 &&
		config.x &&
		config.y.length > 0,
	);

	function selectChartType(id: string) {
		config.type = id;
		const def = getChartType(id);
		if (def && !def.supportsStacked) config.stacked = false;
		if (def && !def.supportsTrendline) config.trendline = false;
		if (def && !def.supportsMedian) config.median = false;
		if (def && !def.multiSeries && config.y.length > 1) {
			config.y = [config.y[0]];
		}
	}

	function addYColumn(col: string) {
		if (!config.y.includes(col)) {
			config.y = [...config.y, col];
		}
	}

	function removeYColumn(col: string) {
		config.y = config.y.filter((c) => c !== col);
	}

	function handleAdd() {
		if (selectedChartDef?.axisMode === "map") {
			if (!config.mapLatColumn || !config.mapLngColumn) {
				alert("Please select latitude and longitude columns.");
				return;
			}
		} else if (!config.x || config.y.length === 0) {
			alert("Please select X-axis and at least one Y-axis column.");
			return;
		}
		onadd(config);
	}

	// Dynamic placeholder for chart title based on current axis selections
	let titlePlaceholder = $derived(() => {
		const yLabel = config.y[0];
		const xLabel = config.x;
		if (yLabel && xLabel) {
			const fmt = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/[_-]/g, ' ');
			return `e.g. ${fmt(yLabel)} by ${fmt(xLabel)}`;
		}
		return 'e.g. Revenue by Month';
	});

	// Preview pan & zoom state
	let previewZoom = $state(1);
	let previewPanX = $state(0);
	let previewPanY = $state(0);
	let isDragging = $state(false);
	let dragStartX = $state(0);
	let dragStartY = $state(0);

	let previewTransform = $derived(
		`scale(${previewZoom}) translate(${previewPanX / previewZoom}px, ${previewPanY / previewZoom}px)`
	);
	let previewMoved = $derived(previewZoom !== 1 || previewPanX !== 0 || previewPanY !== 0);

	function resetPreview() {
		previewZoom = 1;
		previewPanX = 0;
		previewPanY = 0;
	}

	// Reset pan/zoom when chart config changes
	$effect(() => {
		// track config key fields to trigger reset
		config.type; config.x; config.y.length;
		resetPreview();
	});

	function onPreviewWheel(e: WheelEvent) {
		e.preventDefault();
		e.stopPropagation();
		const factor = e.deltaY < 0 ? 1.12 : 0.9;
		previewZoom = Math.max(0.5, Math.min(6, previewZoom * factor));
	}

	function onPreviewMouseDown(e: MouseEvent) {
		if (e.button !== 0) return;
		isDragging = true;
		dragStartX = e.clientX - previewPanX;
		dragStartY = e.clientY - previewPanY;
	}

	function onPreviewMouseMove(e: MouseEvent) {
		if (!isDragging) return;
		previewPanX = e.clientX - dragStartX;
		previewPanY = e.clientY - dragStartY;
	}

	function onPreviewMouseUp() {
		isDragging = false;
	}

	// ── Horizontal resize (drag the left edge) ────────────────────────
	const MIN_PANEL_WIDTH = 320;
	let panelWidth = $state(380);
	let resizing = $state(false);
	let resizeStartX = 0;
	let resizeStartWidth = 0;

	function maxPanelWidth() {
		if (typeof window === "undefined") return 880;
		return Math.min(880, Math.round(window.innerWidth * 0.9));
	}

	function onResizePointerDown(e: PointerEvent) {
		e.preventDefault();
		resizing = true;
		resizeStartX = e.clientX;
		resizeStartWidth = panelWidth;
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
	}

	function onResizePointerMove(e: PointerEvent) {
		if (!resizing) return;
		// Panel is anchored to the right edge, so dragging the left edge
		// leftwards (clientX decreasing) widens it.
		const next = resizeStartWidth + (resizeStartX - e.clientX);
		panelWidth = Math.max(MIN_PANEL_WIDTH, Math.min(maxPanelWidth(), next));
	}

	function onResizePointerUp(e: PointerEvent) {
		if (!resizing) return;
		resizing = false;
		try {
			(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
		} catch {}
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) {
			onclose();
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === "Escape") {
			onclose();
		}
	}
</script>

{#if open}
	<!-- Backdrop -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 z-40 bg-black/20 transition-opacity"
		onclick={handleBackdropClick}
		onkeydown={handleKeydown}
	></div>

	<!-- Sliding Right Panel -->
	<div
		class="fixed right-0 top-0 z-50 flex h-full max-w-[90vw] flex-col border-l border-slate-200 bg-white shadow-xl transition-transform duration-300 dark:border-slate-700 dark:bg-slate-900 {resizing
			? 'select-none'
			: ''}"
		style="width: {panelWidth}px;"
	>
		<!-- Resize handle (left edge) -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="group absolute left-0 top-0 z-10 h-full w-2 -translate-x-1/2 cursor-col-resize touch-none"
			onpointerdown={onResizePointerDown}
			onpointermove={onResizePointerMove}
			onpointerup={onResizePointerUp}
			onpointercancel={onResizePointerUp}
			title="Drag to resize"
		>
			<div
				class="pointer-events-none absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 transition-colors {resizing
					? 'bg-indigo-500'
					: 'bg-transparent group-hover:bg-indigo-400'}"
			></div>
		</div>

		<!-- Header -->
		<div
			class="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-700"
		>
			<div class="min-w-0">
				<h2 class="text-sm font-semibold text-slate-900 dark:text-slate-100">
					Configure {selectedChartDef?.label ?? "Chart"}
				</h2>
				{#if config.x && config.y.length > 0 && selectedChartDef?.axisMode !== "map"}
					<p class="mt-0.5 truncate text-[11px] text-slate-400 dark:text-slate-500">
						{config.y[0]}{config.y.length > 1 ? ` +${config.y.length - 1}` : ""} by {config.x}
					</p>
				{/if}
			</div>
			<button
				class="ml-3 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 shadow-sm transition-all hover:border-slate-300 hover:bg-slate-100 hover:text-slate-800 hover:shadow dark:border-slate-600 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-slate-500 dark:hover:bg-slate-700 dark:hover:text-slate-100"
				onclick={onclose}
				aria-label="Close panel"
				title="Close"
			>
				<Icon icon="mdi:close" class="h-4 w-4" />
			</button>
		</div>

		<!-- Scrollable Content -->
		<div class="flex-1 overflow-y-auto px-4 py-3">
			<!-- Chart Title -->
			<div class="mb-3">
				<label
					for="panel-chart-title"
					class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400"
					>Chart Title</label
				>
				<input
					id="panel-chart-title"
					type="text"
					class="input input-sm w-full"
					placeholder={titlePlaceholder()}
					bind:value={config.title}
				/>
			</div>

			<!-- ── CHART TYPE ────────────────────────────── -->
			<div class="mb-1 flex items-center gap-2">
				<span class="text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">Chart Type</span>
				<Separator class="flex-1" />
			</div>

			<div class="mb-3 mt-1.5">
				<div class="grid grid-cols-5 gap-1">
					{#each chartTypes as ct (ct.id)}
						<button
							class="flex flex-col items-center gap-0.5 rounded border px-1 py-1 text-xs transition-all duration-150
								{config.type === ct.id
								? 'border-indigo-300 bg-indigo-50 text-indigo-700 font-semibold ring-1 ring-indigo-300 dark:border-indigo-700 dark:bg-indigo-950 dark:text-indigo-300 dark:ring-indigo-700'
								: 'border-slate-200 bg-slate-50/80 text-slate-500 hover:border-slate-300 hover:bg-slate-100 hover:text-slate-700 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-400 dark:hover:border-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300'}"
							onclick={() => selectChartType(ct.id)}
							title={ct.label}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="1.5"
								stroke="currentColor"
								class="h-4 w-4 shrink-0"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d={ct.iconPath}
								/>
							</svg>
							<span class="truncate text-[9px] leading-tight">{ct.label}</span>
						</button>
					{/each}
				</div>
			</div>

			<!-- ── DATA MAPPING ──────────────────────────── -->
			<div class="mb-1 flex items-center gap-2">
				<span class="text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">Data Mapping</span>
				<Separator class="flex-1" />
			</div>

			<div class="mb-3 mt-1.5 flex flex-col gap-2">
				{#if selectedChartDef?.axisMode === "map"}
					<!-- Map Configuration -->
					<div>
						<label
							for="panel-map-lat"
							class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400"
						>
							Latitude Column <span class="text-red-500">*</span>
						</label>
						<select
							id="panel-map-lat"
							class="select select-sm w-full"
							bind:value={config.mapLatColumn}
						>
							{#each columns as col}
								<option value={col}>{col}</option>
							{/each}
						</select>
					</div>

					<div>
						<label
							for="panel-map-lng"
							class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400"
						>
							Longitude Column <span class="text-red-500">*</span>
						</label>
						<select
							id="panel-map-lng"
							class="select select-sm w-full"
							bind:value={config.mapLngColumn}
						>
							{#each columns as col}
								<option value={col}>{col}</option>
							{/each}
						</select>
					</div>

					<!-- Popup Tooltip Columns (tags + chips) -->
					<div>
						<!-- svelte-ignore a11y_label_has_associated_control -->
						<label class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">
							Popup Tooltip Columns
						</label>

						<!-- Selected tags -->
						{#if (config.mapLabelColumns || []).length > 0}
							<div class="mb-1.5 flex flex-wrap gap-1">
								{#each config.mapLabelColumns || [] as col (col)}
									<button
										class="inline-flex items-center gap-0.5 rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700 transition-colors hover:bg-red-50 hover:text-red-600 dark:bg-indigo-950 dark:text-indigo-300 dark:hover:bg-red-950 dark:hover:text-red-400"
										onclick={() => {
											config.mapLabelColumns = (config.mapLabelColumns || []).filter((c) => c !== col);
										}}
										title="Remove {col}"
									>
										{col}
										<Icon icon="mdi:close" class="h-2.5 w-2.5" />
									</button>
								{/each}
							</div>
						{/if}

						<!-- Available chips -->
						<div class="flex flex-wrap gap-1">
							{#each availableMapLabelColumns as col (col)}
								<button
									class="inline-flex cursor-pointer items-center gap-0.5 rounded-full border border-slate-200 bg-white px-2 py-0.5 text-xs text-slate-600 transition-all duration-150 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-indigo-600 dark:hover:bg-indigo-950 dark:hover:text-indigo-300"
									onclick={() => {
										config.mapLabelColumns = [...(config.mapLabelColumns || []), col];
									}}
								>
									<Icon icon="mdi:plus" class="h-2.5 w-2.5" />
									{col}
								</button>
							{:else}
								<p class="text-xs italic text-slate-400">All columns selected</p>
							{/each}
						</div>
						<p class="mt-1 text-[10px] text-slate-400 dark:text-slate-500">
							First column is bold as title in the popup.
						</p>
					</div>

					<!-- Marker Color -->
					<div>
						<!-- svelte-ignore a11y_label_has_associated_control -->
						<label class="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">
							Marker Color
						</label>
						<div class="flex flex-wrap gap-1.5">
							{#each [
								{ id: "blue", fill: "#3b82f6", label: "Blue" },
								{ id: "red", fill: "#ef4444", label: "Red" },
								{ id: "green", fill: "#22c55e", label: "Green" },
								{ id: "orange", fill: "#f97316", label: "Orange" },
								{ id: "purple", fill: "#a855f7", label: "Purple" },
								{ id: "pink", fill: "#ec4899", label: "Pink" },
								{ id: "cyan", fill: "#06b6d4", label: "Cyan" },
								{ id: "yellow", fill: "#eab308", label: "Yellow" },
							] as color (color.id)}
								<button
									class="flex h-6 w-6 items-center justify-center rounded-full border-2 transition-all
										{(config.mapMarkerColor || 'blue') === color.id
										? 'border-slate-800 scale-110 shadow-md dark:border-white'
										: 'border-transparent hover:border-slate-300 dark:hover:border-slate-500'}"
									style="background-color: {color.fill}"
									title={color.label}
									onclick={() => (config.mapMarkerColor = color.id)}
								>
									{#if (config.mapMarkerColor || "blue") === color.id}
										<svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 text-white" viewBox="0 0 20 20" fill="currentColor">
											<path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
										</svg>
									{/if}
								</button>
							{/each}
						</div>
					</div>
				{:else}
					<!-- X-Axis -->
					<div>
						<div class="mb-1 flex items-center gap-1.5">
							<span class="inline-flex h-4 w-4 items-center justify-center rounded bg-indigo-100 text-[9px] font-bold text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300">X</span>
							<label
								for="panel-x-axis"
								class="text-xs font-medium text-slate-600 dark:text-slate-400"
							>
								{selectedChartDef?.axisMode === "none"
									? "Category Label (Legend)"
									: "X-Axis"}
							</label>
						</div>
						<select
							id="panel-x-axis"
							class="select select-sm w-full"
							bind:value={config.x}
						>
							{#each columns as col}
								<option value={col}>{col}</option>
							{/each}
						</select>
						{#if selectedChartDef?.axisMode === "cartesian"}
							<div class="mt-1.5">
								<label
									for="panel-x-mode"
									class="mb-0.5 block text-[10px] font-medium text-slate-400 dark:text-slate-500"
								>
									Axis Mode
								</label>
								<select
									id="panel-x-mode"
									class="select select-sm w-full"
									bind:value={config.xAxisMode}
								>
									<option value="category">Categorical</option>
									<option value="time">Time Series</option>
								</select>
							</div>
						{/if}
					</div>

					<!-- Y-Axis / Value -->
					{#if selectedChartDef?.multiSeries}
						<!-- Tags + chips for multi-series charts -->
						<div>
							<div class="mb-1 flex items-center gap-1.5">
								<span class="inline-flex h-4 w-4 items-center justify-center rounded bg-emerald-100 text-[9px] font-bold text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300">Y</span>
								<span class="text-xs font-medium text-slate-600 dark:text-slate-400">Values / Series</span>
								{#if config.y.length > 0}
									<Badge variant="secondary" class="text-[10px]">{config.y.length} selected</Badge>
								{/if}
							</div>

							<!-- Selected tags -->
							{#if config.y.length > 0}
								<div class="mb-1.5 flex flex-wrap gap-1">
									{#each config.y as col (col)}
										<button
											class="inline-flex items-center gap-0.5 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 transition-colors hover:bg-red-50 hover:text-red-600 dark:bg-emerald-950 dark:text-emerald-300 dark:hover:bg-red-950 dark:hover:text-red-400"
											onclick={() => removeYColumn(col)}
											title="Remove {col}"
										>
											{col}
											<Icon icon="mdi:close" class="h-2.5 w-2.5" />
										</button>
									{/each}
								</div>
							{/if}

							<!-- Available chips -->
							<div class="flex flex-wrap gap-1">
								{#each availableYColumns as col (col)}
									{@const isXAxis = col === config.x}
									<button
										class="inline-flex items-center gap-0.5 rounded-full border px-2 py-0.5 text-xs transition-all duration-150
											{isXAxis
											? 'border-slate-100 bg-slate-50 text-slate-300 cursor-not-allowed dark:border-slate-700 dark:bg-slate-800 dark:text-slate-600'
											: 'cursor-pointer border-slate-200 bg-white text-slate-600 hover:border-emerald-300 hover:bg-emerald-50 hover:text-emerald-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-emerald-600 dark:hover:bg-emerald-950 dark:hover:text-emerald-300'}"
										onclick={() => !isXAxis && addYColumn(col)}
										disabled={isXAxis}
										title={isXAxis ? "Already used as X-Axis" : `Add ${col}`}
									>
										<Icon icon="mdi:plus" class="h-2.5 w-2.5" />
										{col}
									</button>
								{:else}
									<p class="text-xs italic text-slate-400">All columns selected</p>
								{/each}
							</div>
						</div>
					{:else}
						<!-- Single-select for pie/doughnut -->
						<div>
							<div class="mb-1 flex items-center gap-1.5">
								<span class="inline-flex h-4 w-4 items-center justify-center rounded bg-emerald-100 text-[9px] font-bold text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300">Y</span>
								<label
									for="panel-value"
									class="text-xs font-medium text-slate-600 dark:text-slate-400"
									>Value</label
								>
							</div>
							<select
								id="panel-value"
								class="select select-sm w-full"
								value={config.y[0] || ""}
								onchange={(e) =>
									(config.y = [
										e.currentTarget.value,
									])}
							>
								{#each columns as col}
									<option value={col}>{col}</option>
								{/each}
							</select>
						</div>
					{/if}
				{/if}
			</div>

			<!-- ── OPTIONS ───────────────────────────────── -->
			{#if selectedChartDef?.axisMode !== "map"}
				<div class="mb-1 flex items-center gap-2">
					<span class="text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">Options</span>
					<Separator class="flex-1" />
				</div>

				<div class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
					<div class="scale-75 origin-left"><AppToggle bind:checked={config.showLegend} label="Legend" /></div>
					{#if selectedChartDef?.supportsStacked}
						<div class="scale-75 origin-left"><AppToggle bind:checked={config.stacked} label="Stack" /></div>
					{/if}
					{#if selectedChartDef?.supportsTrendline}
						<div class="scale-75 origin-left"><AppToggle bind:checked={config.trendline} label="Trend" /></div>
					{/if}
					{#if selectedChartDef?.supportsMedian}
						<div class="scale-75 origin-left"><AppToggle bind:checked={config.median} label="Median" /></div>
					{/if}
					{#if selectedChartDef?.multiSeries && config.y.length >= 2}
						<div class="scale-75 origin-left"><AppToggle bind:checked={config.splitSeries} label="Split Series" /></div>
					{/if}
				</div>
			{/if}

			<!-- ── PREVIEW ──────────────────────────────── -->
			{#if selectedChartDef?.axisMode !== "map"}
				<div class="mb-1 mt-3 flex items-center gap-2">
					<span class="text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">Preview</span>
					<Separator class="flex-1" />
				</div>

				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div
					class="relative mt-1.5 overflow-hidden rounded-lg border border-slate-200 bg-slate-50/50 dark:border-slate-700 dark:bg-slate-800/50"
					style="height: 160px;"
					onwheel={canPreview ? onPreviewWheel : undefined}
					onmousedown={canPreview ? onPreviewMouseDown : undefined}
					onmousemove={canPreview ? onPreviewMouseMove : undefined}
					onmouseup={canPreview ? onPreviewMouseUp : undefined}
					onmouseleave={canPreview ? onPreviewMouseUp : undefined}
					ondblclick={canPreview ? resetPreview : undefined}
					style:cursor={!canPreview ? 'default' : isDragging ? 'grabbing' : 'grab'}
				>
					{#if canPreview}
						{#if previewMoved}
							<button
								class="absolute right-1.5 top-1.5 z-10 rounded bg-white/80 px-1.5 py-0.5 text-[10px] font-medium text-slate-500 shadow-sm backdrop-blur-sm transition-colors hover:bg-white hover:text-slate-700 dark:bg-slate-800/80 dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-slate-200"
								onclick={resetPreview}
								title="Reset zoom & pan"
							>Reset</button>
						{/if}
						<div
							class="h-full w-full origin-center"
							style="transform: {previewTransform}; will-change: transform;"
						>
							{#key `${config.type}-${config.x}-${config.y.join(',')}-${config.stacked}-${config.trendline}-${config.median}-${config.splitSeries}-${config.showLegend}`}
								<DataChart
									data={previewData}
									legendPosition="bottom"
									compact={true}
									config={{
										type: config.type,
										x: config.x,
										y: config.y,
										stacked: config.stacked,
										trendline: config.trendline,
										median: config.median,
										splitSeries: config.splitSeries,
										title: "",
										showLegend: config.showLegend,
										xAxisMode: config.xAxisMode,
									}}
								/>
							{/key}
						</div>
					{:else}
						<div class="flex h-full flex-col items-center justify-center gap-1.5 text-slate-400 dark:text-slate-500">
							<Icon icon="mdi:chart-box-outline" class="h-7 w-7" />
							<span class="text-xs">Select X-Axis and Y series to preview</span>
						</div>
					{/if}
				</div>
			{/if}
		</div>

		<!-- Footer -->
		<div
			class="flex justify-end gap-2 border-t border-slate-200 px-4 py-3 dark:border-slate-700"
		>
			<button
				class="inline-flex items-center justify-center gap-1.5 rounded border border-slate-300 bg-transparent px-3 py-1.5 text-xs font-medium text-slate-600 transition-all hover:bg-slate-50 hover:text-slate-800 dark:border-slate-600 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
				onclick={onclose}
			>
				Cancel
			</button>
			<button
				class="inline-flex items-center justify-center gap-1.5 rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-all hover:bg-indigo-700 hover:shadow-md active:shadow-sm dark:bg-indigo-500 dark:hover:bg-indigo-600"
				onclick={handleAdd}
			>
				<Icon icon="mdi:plus" class="h-3.5 w-3.5" />
				{selectedChartDef?.axisMode === "map" ? "Add Map" : "Add Chart"}
			</button>
		</div>
	</div>
{/if}
