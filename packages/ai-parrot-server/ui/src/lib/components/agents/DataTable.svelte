<script lang="ts">
	import { untrack, onMount } from "svelte";
	import { browser } from "$app/environment";
	import Icon from "@iconify/svelte";
	// ai-parrot (FEAT-476 TASK-2594): DataChart/DataMap/ChartConfigPanel
	// (features.charts / features.maps, TASK-2595) are no longer static
	// imports — loaded on demand via dynamic import() at their render
	// sites below, matching the pattern already established in
	// ChatBubble.svelte. `ChartTempConfig` stays a type-only import (no
	// runtime cost).
	import type { ChartTempConfig } from "./ChartConfigPanel.svelte";
	import { features } from "$lib/features";
	import { isNumericLike } from "./numeric-parser";

	let DataChartComp = $state<typeof import("./DataChart.svelte").default | null>(null);
	let DataMapComp = $state<typeof import("./DataMap.svelte").default | null>(null);
	let ChartConfigPanelComp = $state<
		typeof import("./ChartConfigPanel.svelte").default | null
	>(null);

	function ensureChartComponentsLoaded() {
		if (!features.charts && !features.maps) return;
		if (!DataChartComp && features.charts) {
			import("./DataChart.svelte").then((m) => (DataChartComp = m.default));
		}
		if (!DataMapComp && features.maps) {
			import("./DataMap.svelte").then((m) => (DataMapComp = m.default));
		}
		if (!ChartConfigPanelComp) {
			import("./ChartConfigPanel.svelte").then(
				(m) => (ChartConfigPanelComp = m.default),
			);
		}
	}

	// Props
	interface Props {
		data: Record<string, any>[];
		columns?: string[];
		title?: string;
		chartBackend?: "chartjs" | "layerchart";
		onCopyChartToCanvas?: (data: Record<string, any>[], config: any, imageDataUrl?: string) => void;
		onCopyChartToChartCanvas?: (data: Record<string, any>[], config: any) => void;
	}

	let {
		data = [],
		columns = [],
		title = "",
		chartBackend = "chartjs",
		onCopyChartToCanvas,
		onCopyChartToChartCanvas,
	}: Props = $props();

	// State
	let searchQuery = $state("");
	let currentPage = $state(1);
	let itemsPerPage = 10;
	let sortField = $state<string | null>(null);

	let sortDirection = $state<"asc" | "desc">("asc");

	// Chart State
	interface ActiveChart {
		id: string;
		type: string;
		x: string;
		y: string[];
		stacked?: boolean;
		trendline?: boolean;
		splitSeries?: boolean;
		title?: string;
		showLegend?: boolean;
		mapLabelColumns?: string[];
		mapLatColumn?: string;
		mapLngColumn?: string;
		mapMarkerColor?: string;
	}

	let activeCharts = $state<ActiveChart[]>([]);
	let chartConfigOpen = $state(false);
	let rolodexMode = $state(false);
	let rolodexIndex = $state(0);

	// Temporary config for the panel
	let tempConfig: ChartTempConfig = $state({
		type: "bar",
		x: "",
		y: [] as string[],
		stacked: false,
		trendline: false,
		median: false,
		splitSeries: false,
		title: "",
		showLegend: true,
		xAxisMode: "category",
	});

	// Derived: Columns
	let tableColumns = $derived.by(() => {
		if (columns.length > 0) return columns;
		if (data && data.length > 0) return Object.keys(data[0]);
		return [];
	});

	// Derived: Filtered & Sorted Data
	let processedData = $derived.by(() => {
		let result = [...data];

		// Filter
		if (searchQuery) {
			const lowerQuery = searchQuery.toLowerCase();
			result = result.filter((row) =>
				Object.values(row).some((val) =>
					String(val).toLowerCase().includes(lowerQuery),
				),
			);
		}

		// Sort
		if (sortField) {
			result.sort((a, b) => {
				const valA = a[sortField!];
				const valB = b[sortField!];

				if (valA < valB) return sortDirection === "asc" ? -1 : 1;
				if (valA > valB) return sortDirection === "asc" ? 1 : -1;
				return 0;
			});
		}

		return result;
	});

	// Derived: Pagination
	let totalPages = $derived(Math.ceil(processedData.length / itemsPerPage));
	let paginatedData = $derived(
		processedData.slice(
			(currentPage - 1) * itemsPerPage,
			currentPage * itemsPerPage,
		),
	);

	// Reset page on search
	$effect(() => {
		if (searchQuery) {
			untrack(() => {
				currentPage = 1;
			});
		}
	});

	function handleSort(field: string) {
		if (sortField === field) {
			sortDirection = sortDirection === "asc" ? "desc" : "asc";
		} else {
			sortField = field;
			sortDirection = "asc";
		}
	}

	function exportToCSV() {
		if (!processedData.length) return;

		const headers = tableColumns.join(",");
		const rows = processedData.map((row) =>
			tableColumns
				.map((col: string) => {
					const cell =
						row[col] === null || row[col] === undefined
							? ""
							: row[col];
					const cellStr = String(cell);
					// Escape quotes and wrap in quotes if contains comma or newline
					if (
						cellStr.includes(",") ||
						cellStr.includes("\n") ||
						cellStr.includes('"')
					) {
						return `"${cellStr.replace(/"/g, '""')}"`;
					}
					return cellStr;
				})
				.join(","),
		);

		const csvContent = [headers, ...rows].join("\n");
		const blob = new Blob([csvContent], {
			type: "text/csv;charset=utf-8;",
		});
		const url = URL.createObjectURL(blob);
		const link = document.createElement("a");
		link.setAttribute("href", url);
		link.setAttribute("download", `table_export_${Date.now()}.csv`);
		link.style.visibility = "hidden";
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
	}

	function findColumnByPattern(cols: string[], patterns: string[]): string {
		const lower = cols.map((c) => c.toLowerCase());
		for (const pat of patterns) {
			const idx = lower.findIndex((c) => c === pat || c.includes(pat));
			if (idx !== -1) return cols[idx];
		}
		return "";
	}

	function openChartConfig(presetType?: string) {
		ensureChartComponentsLoaded();
		const numericCols = tableColumns.filter((col) => {
			const val = data[0]?.[col];
			return isNumericLike(val);
		});
		const stringCols = tableColumns.filter((col) => {
			const val = data[0]?.[col];
			return typeof val === "string";
		});

		const defaultLatCol = findColumnByPattern(tableColumns, ["latitude", "lat"]);
		const defaultLngCol = findColumnByPattern(tableColumns, ["longitude", "lng", "lon", "long"]);
		const defaultLabelCol = findColumnByPattern(tableColumns, ["name", "label", "title", "description"]);

		tempConfig = {
			type: presetType || "bar",
			x: stringCols[0] || tableColumns[0] || "",
			y: numericCols.length > 0 ? [numericCols[0]] : [],
			stacked: false,
			trendline: false,
			median: false,
			splitSeries: false,
			title: "",
			showLegend: true,
			xAxisMode: "category",
			mapLatColumn: defaultLatCol || numericCols[0] || tableColumns[0] || "",
			mapLngColumn: defaultLngCol || (numericCols.length > 1 ? numericCols[1] : numericCols[0]) || tableColumns[0] || "",
			mapLabelColumns: defaultLabelCol ? [defaultLabelCol] : (stringCols.length > 0 ? [stringCols[0]] : []),
			mapMarkerColor: "blue",
		};

		chartConfigOpen = true;
	}

	function addChart(cfg: ChartTempConfig) {
		activeCharts.push({
			id: crypto.randomUUID(),
			type: cfg.type,
			x: cfg.x,
			y: [...cfg.y],
			stacked: cfg.stacked,
			trendline: cfg.trendline,
			splitSeries: cfg.splitSeries,
			title: cfg.title || undefined,
			showLegend: cfg.showLegend,
			mapLabelColumns: cfg.mapLabelColumns ? [...cfg.mapLabelColumns] : [],
			mapLatColumn: cfg.mapLatColumn,
			mapLngColumn: cfg.mapLngColumn,
			mapMarkerColor: cfg.mapMarkerColor,
		});

		chartConfigOpen = false;
	}

	function removeChart(id: string) {
		activeCharts = activeCharts.filter((c) => c.id !== id);
	}

	// ─── Cell type detection ────────────────────────────────────────────────────
	const DATE_RE = /^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?)?$/;

	type CellType = "null" | "boolean" | "number" | "date" | "string";

	function getCellType(value: unknown): CellType {
		if (value === null || value === undefined) return "null";
		if (typeof value === "boolean") return "boolean";
		if (typeof value === "number") return "number";
		if (typeof value === "string") {
			if (DATE_RE.test(value.trim())) return "date";
			if (value.trim() !== "" && !isNaN(Number(value))) return "number";
		}
		return "string";
	}

	function formatCell(value: unknown, type: CellType): string {
		if (type === "null") return "null";
		if (type === "number" && typeof value === "string") return value; // keep original string precision
		return String(value);
	}

	// ─── Cell copy-on-click ─────────────────────────────────────────────────────
	let copiedKey = $state<string | null>(null);
	let copyTimer: ReturnType<typeof setTimeout> | null = null;

	function copyCell(rowIdx: number, col: string, value: unknown) {
		if (value === null || value === undefined) return;
		const key = `${rowIdx}:${col}`;
		navigator.clipboard.writeText(String(value)).catch(() => {});
		copiedKey = key;
		if (copyTimer) clearTimeout(copyTimer);
		copyTimer = setTimeout(() => { copiedKey = null; }, 1200);
	}

</script>

<div
	class="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-3 text-slate-700 shadow-sm"
>
	<!-- Header / Controls -->
	<div class="flex flex-wrap items-center justify-between gap-2">
		<div class="flex items-center gap-2">
			{#if title}<span class="text-xs font-semibold text-slate-900"
					>{title}</span
				>{/if}
			<span class="badge badge-xs border-none bg-slate-100 text-slate-600"
				>{data.length} rows</span
			>
		</div>

		<div class="flex flex-1 items-center justify-end gap-1.5">
			<!-- Search -->
			<label
				class="input input-xs border-slate-300 focus-within:border-primary focus-within:outline-none flex w-full max-w-xs items-center gap-2 border bg-white text-slate-700"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 16 16"
					fill="currentColor"
					class="text-slate-500 h-4 w-4 opacity-50"
				>
					<path
						fill-rule="evenodd"
						d="M9.965 11.026a5 5 0 1 1 1.06-1.06l2.755 2.754a.75.75 0 1 1-1.06 1.06l-2.755-2.754ZM10.5 7a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0Z"
						clip-rule="evenodd"
						opacity="0.5"
					/>
				</svg>
				<input
					type="text"
					class="placeholder:text-slate-400 grow"
					placeholder="Search..."
					bind:value={searchQuery}
				/>
			</label>

			<!-- Export CSV (icon-only) -->
			<button
				class="btn btn-sm btn-square btn-outline border-slate-300 text-slate-600 hover:border-slate-400 hover:bg-slate-50 hover:text-slate-800"
				onclick={exportToCSV}
				disabled={!data.length}
				title="Export CSV"
			>
				<Icon icon="mdi:download" class="w-4 h-4" />
			</button>

			<!-- Chart Button (icon-only) -->
			{#if features.charts || features.maps}
				<button
					class="btn btn-sm btn-square btn-outline border-slate-300 text-slate-600 hover:border-slate-400 hover:bg-slate-50 hover:text-slate-800"
					onclick={() => openChartConfig()}
					disabled={!data.length}
					title="Add chart"
				>
					<Icon icon="mdi:chart-bar" class="w-4 h-4" />
				</button>
			{/if}
		</div>
	</div>

	<!-- Table -->
	<div class="overflow-x-auto rounded-lg border border-slate-200">
		<table
			class="w-full min-w-full divide-y divide-slate-200 text-left text-xs text-slate-600"
		>
			<!-- Head -->
			<thead class="bg-slate-50 text-slate-900 font-semibold">
				<tr class="divide-x divide-slate-200">
					{#each tableColumns as col}
						<th
							class="hover:bg-slate-100 cursor-pointer select-none px-3 py-1.5 text-[11px] uppercase tracking-wider transition-colors"
							onclick={() => handleSort(col)}
						>
							<div class="flex items-center gap-1">
								{col.replace(/_/g, " ")}
								{#if sortField === col}
									<span class="text-xs">
										{#if sortDirection === "asc"}▲{:else}▼{/if}
									</span>
								{/if}
							</div>
						</th>
					{/each}
				</tr>
			</thead>
			<!-- Body -->
			<tbody class="divide-y divide-slate-200 bg-white">
				{#if paginatedData.length > 0}
					{#each paginatedData as row, rowIdx}
						<tr
							class="hover:bg-slate-50 divide-x divide-slate-200 transition-colors"
						>
							{#each tableColumns as col}
								{@const cellType = getCellType(row[col])}
								{@const cellKey = `${rowIdx}:${col}`}
								{@const isCopied = copiedKey === cellKey}
								<td
									class="group relative whitespace-nowrap pl-3 pr-10 py-1.5 cursor-pointer"
									onclick={() => copyCell(rowIdx, col, row[col])}
									title="Click to copy"
								>
									{#if cellType === "null"}
										<span class="text-slate-400 italic text-[11px]">null</span>
									{:else if cellType === "boolean"}
										<span class="inline-flex items-center gap-1">
											<span class={`badge badge-xs border-none ${row[col] ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-600"}`}></span>
											<span class={row[col] ? "text-emerald-700" : "text-red-600"}>{formatCell(row[col], cellType)}</span>
										</span>
									{:else if cellType === "number"}
										<span class="font-mono text-blue-600 tabular-nums">{formatCell(row[col], cellType)}</span>
									{:else if cellType === "date"}
										<span class="font-mono text-violet-600 text-[11px]">{formatCell(row[col], cellType)}</span>
									{:else}
										<span class="text-slate-700">{formatCell(row[col], cellType)}</span>
									{/if}
									{#if isCopied}
										<span class="pointer-events-none absolute right-1 top-1/2 -translate-y-1/2 rounded bg-emerald-600 px-1 py-0.5 text-[10px] text-white shadow">✓</span>
									{:else}
										<span class="pointer-events-none absolute right-1 top-1/2 -translate-y-1/2 rounded bg-slate-700 px-1 py-0.5 text-[10px] text-white opacity-0 shadow transition-opacity group-hover:opacity-70">copy</span>
									{/if}
								</td>
							{/each}
						</tr>
					{/each}
				{:else}
					<tr>
						<td
							colspan={tableColumns.length}
							class="text-slate-400 py-12 text-center"
						>
							No results found
						</td>
					</tr>
				{/if}
			</tbody>
		</table>
	</div>

	<!-- Pagination -->
	{#if totalPages > 1}
		<div
			class="border-slate-100 flex items-center justify-between border-t px-1.5 pt-1.5"
		>
			<span class="text-[10px] text-slate-500"
				>Showing {(currentPage - 1) * itemsPerPage + 1} to {Math.min(
					currentPage * itemsPerPage,
					processedData.length,
				)} of {processedData.length}</span
			>
			<div class="join">
				<button
					class="join-item btn btn-xs h-6 min-h-0 px-1.5 text-[10px] btn-outline border-slate-300 text-slate-600 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-800 disabled:border-slate-200 disabled:bg-transparent disabled:text-slate-300"
					disabled={currentPage === 1}
					onclick={() => (currentPage = Math.max(1, currentPage - 1))}
					>«</button
				>
				<button
					class="join-item btn btn-xs h-6 min-h-0 px-2 text-[10px] btn-outline border-slate-300 bg-white text-slate-700 hover:border-slate-300 hover:bg-white hover:text-slate-700 cursor-default no-animation"
					>Page {currentPage}</button
				>
				<button
					class="join-item btn btn-xs h-6 min-h-0 px-1.5 text-[10px] btn-outline border-slate-300 text-slate-600 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-800 disabled:border-slate-200 disabled:bg-transparent disabled:text-slate-300"
					disabled={currentPage === totalPages}
					onclick={() =>
						(currentPage = Math.min(totalPages, currentPage + 1))}
					>»</button
				>
			</div>
		</div>
	{/if}
</div>

<!-- Active Charts Area -->
{#if activeCharts.length > 0}
	<!-- View Mode Toggle -->
	<div class="mt-4 flex items-center justify-between">
		<span class="text-xs font-medium text-slate-500">
			{activeCharts.length} chart{activeCharts.length > 1 ? "s" : ""}
		</span>
		{#if activeCharts.length > 1}
			<button
				class="btn btn-xs gap-1.5 transition-all duration-200
					{rolodexMode
					? 'btn-primary text-white'
					: 'btn-outline border-slate-300 text-slate-600 hover:bg-slate-50'}"
				onclick={() => {
					rolodexMode = !rolodexMode;
					if (rolodexMode)
						rolodexIndex = Math.min(
							rolodexIndex,
							activeCharts.length - 1,
						);
				}}
				title={rolodexMode
					? "Show all charts stacked"
					: "Show charts as carousel"}
			>
				{#if rolodexMode}
					<!-- Stacked icon -->
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="1.5"
						stroke="currentColor"
						class="w-4 h-4"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25a2.25 2.25 0 0 1-2.25-2.25v-2.25Z"
						/>
					</svg>
					Show All
				{:else}
					<!-- Carousel icon -->
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="1.5"
						stroke="currentColor"
						class="w-4 h-4"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M6 6.878V6a2.25 2.25 0 0 1 2.25-2.25h7.5A2.25 2.25 0 0 1 18 6v.878m-12 0c.235-.083.487-.128.75-.128h10.5c.263 0 .515.045.75.128m-12 0A2.25 2.25 0 0 0 4.5 9v.878m13.5-3A2.25 2.25 0 0 1 19.5 9v.878m-15-3A2.25 2.25 0 0 0 3 9v10.5a2.25 2.25 0 0 0 2.25 2.25h13.5A2.25 2.25 0 0 0 21 19.5V9a2.25 2.25 0 0 0-1.5-2.122"
						/>
					</svg>
					Carousel
				{/if}
			</button>
		{/if}
	</div>

	{#if rolodexMode && activeCharts.length > 1}
		<!-- Rolodex / Carousel View -->
		<div class="relative mt-2" style="perspective: 1200px;">
			<!-- Card stack: show current + peek of adjacent cards -->
			<div class="relative" style="min-height: 360px;">
				{#each activeCharts as chart, i (chart.id)}
					{@const offset = i - rolodexIndex}
					{@const isVisible = Math.abs(offset) <= 2}
					{#if isVisible}
						<div
							class="absolute inset-0 transition-all duration-500 ease-out"
							style="
								transform: translateY({offset * 12}px) scale({1 - Math.abs(offset) * 0.04});
								opacity: {offset === 0 ? 1 : Math.max(0, 0.5 - Math.abs(offset) * 0.15)};
								z-index: {100 - Math.abs(offset)};
								pointer-events: {offset === 0 ? 'auto' : 'none'};
								filter: {offset === 0 ? 'none' : 'blur(1px)'};
							"
						>
							{#if chart.type === "map" && features.maps && DataMapComp}
								<DataMapComp
									data={processedData}
									config={chart}
									onClose={() => removeChart(chart.id)}
								/>
							{:else if chart.type !== "map" && features.charts && DataChartComp}
								<DataChartComp
									data={processedData}
									config={chart}
									onClose={() => removeChart(chart.id)}
									onCopyToCanvas={onCopyChartToCanvas}
									onCopyToChartCanvas={onCopyChartToChartCanvas}
								/>
							{/if}
						</div>
					{/if}
				{/each}
			</div>

			<!-- Navigation Controls -->
			<div class="flex items-center justify-center gap-2 mt-1.5">
				<button
					class="btn btn-xs btn-circle h-6 w-6 min-h-0 btn-outline border-slate-300 text-slate-500 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30 disabled:cursor-not-allowed"
					disabled={rolodexIndex === 0}
					aria-label="Previous chart"
					onclick={() =>
						(rolodexIndex = Math.max(0, rolodexIndex - 1))}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="2"
						stroke="currentColor"
						class="w-3 h-3"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M15.75 19.5 8.25 12l7.5-7.5"
						/>
					</svg>
				</button>

				<!-- Dot indicators -->
				<div class="flex items-center gap-1">
					{#each activeCharts as _, i}
						<button
							class="rounded-full transition-all duration-300
								{i === rolodexIndex
								? 'w-4 h-1.5 bg-blue-500'
								: 'w-1.5 h-1.5 bg-slate-300 hover:bg-slate-400'}"
							onclick={() => (rolodexIndex = i)}
							title="Chart {i + 1}"
						></button>
					{/each}
				</div>

				<button
					class="btn btn-xs btn-circle h-6 w-6 min-h-0 btn-outline border-slate-300 text-slate-500 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30 disabled:cursor-not-allowed"
					disabled={rolodexIndex >= activeCharts.length - 1}
					aria-label="Next chart"
					onclick={() =>
						(rolodexIndex = Math.min(
							activeCharts.length - 1,
							rolodexIndex + 1,
						))}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="2"
						stroke="currentColor"
						class="w-3 h-3"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="m8.25 4.5 7.5 7.5-7.5 7.5"
						/>
					</svg>
				</button>
			</div>

			<p class="text-[10px] text-center text-slate-400 mt-0.5">
				{rolodexIndex + 1} / {activeCharts.length}
			</p>
		</div>
	{:else}
		<!-- Stacked View (default) -->
		<div
			class="mt-2 flex flex-col gap-4 animate-in slide-in-from-top-2 fade-in duration-300"
		>
			{#each activeCharts as chart (chart.id)}
				{#if chart.type === "map" && features.maps && DataMapComp}
					<DataMapComp
						data={processedData}
						config={chart}
						onClose={() => removeChart(chart.id)}
					/>
				{:else if chart.type !== "map" && features.charts && DataChartComp}
					<DataChartComp
						data={processedData}
						config={chart}
						onClose={() => removeChart(chart.id)}
						onCopyToCanvas={onCopyChartToCanvas}
						onCopyToChartCanvas={onCopyChartToChartCanvas}
					/>
				{/if}
			{/each}
		</div>
	{/if}
{/if}

<!-- Chart Configuration Panel -->
{#if (features.charts || features.maps) && ChartConfigPanelComp}
	<ChartConfigPanelComp
		open={chartConfigOpen}
		columns={tableColumns}
		previewData={data.slice(0, 20)}
		bind:config={tempConfig}
		onclose={() => (chartConfigOpen = false)}
		onadd={addChart}
	/>
{/if}
