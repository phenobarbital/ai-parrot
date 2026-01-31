<script lang="ts">
	import { untrack, onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { Button, Dropdown, DropdownItem, Modal, Label, Select } from 'flowbite-svelte';
	import { FileChartBarSolid, CloseOutline } from 'flowbite-svelte-icons';
	import type { Chart as ChartType } from 'chart.js';

	// Props
	interface Props {
		data: Record<string, any>[];
		columns?: string[];
		title?: string;
	}

	let { data = [], columns = [], title = 'Table View' }: Props = $props();

	// State
	let searchQuery = $state('');
	let currentPage = $state(1);
	let itemsPerPage = 10;
	let sortField = $state<string | null>(null);

	let sortDirection = $state<'asc' | 'desc'>('asc');

	// Chart State
	let showChart = $state(false);
	let chartType = $state<'bar' | 'pie' | null>(null);
	let chartConfigOpen = $state(false);
	let chartConfig = $state({ x: '', y: '', category: '', value: '' });
	// Helper state to hold the data used for the Chart (snapshot of table data)
	let chartData = $state<Record<string, any>[]>([]);
	
	// Chart.js instance reference
	let chartCanvas = $state<HTMLCanvasElement | null>(null);
	let chartInstance: ChartType | null = null;

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
				Object.values(row).some((val) => String(val).toLowerCase().includes(lowerQuery))
			);
		}

		// Sort
		if (sortField) {
			result.sort((a, b) => {
				const valA = a[sortField!];
				const valB = b[sortField!];

				if (valA < valB) return sortDirection === 'asc' ? -1 : 1;
				if (valA > valB) return sortDirection === 'asc' ? 1 : -1;
				return 0;
			});
		}

		return result;
	});

	// Derived: Pagination
	let totalPages = $derived(Math.ceil(processedData.length / itemsPerPage));
	let paginatedData = $derived(
		processedData.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage)
	);

	// Reset page on search
	$effect(() => {
		if (searchQuery) {
			untrack(() => {
				currentPage = 1;
			});
		}
	});

	// Effect to render Chart.js when showChart changes (client-side only)
	$effect(() => {
		if (!browser || !showChart || !chartCanvas || chartData.length === 0) return;

		// Dynamic import of Chart.js to avoid SSR issues
		import('chart.js').then(({ Chart, registerables }) => {
			Chart.register(...registerables);

			// Destroy previous chart if exists
			if (chartInstance) {
				chartInstance.destroy();
				chartInstance = null;
			}

			// Build chart based on type
			if (chartType === 'bar' && chartConfig.x && chartConfig.y) {
				const labels = chartData.map(row => String(row[chartConfig.x]));
				const values = chartData.map(row => Number(row[chartConfig.y]) || 0);

				chartInstance = new Chart(chartCanvas, {
					type: 'bar',
					data: {
						labels,
						datasets: [{
							label: chartConfig.y,
							data: values,
							backgroundColor: 'rgba(59, 130, 246, 0.7)',
							borderColor: 'rgba(59, 130, 246, 1)',
							borderWidth: 1
						}]
					},
					options: {
						responsive: true,
						maintainAspectRatio: false,
						plugins: {
							legend: { display: false }
						},
						scales: {
							y: { beginAtZero: true }
						}
					}
				});
			} else if (chartType === 'pie' && chartConfig.category && chartConfig.value) {
				const labels = chartData.map(row => String(row[chartConfig.category]));
				const values = chartData.map(row => Number(row[chartConfig.value]) || 0);

				// Generate colors
				const colors = labels.map((_, i) => {
					const hue = (i * 137.5) % 360; // Golden angle for color distribution
					return `hsl(${hue}, 70%, 60%)`;
				});

				chartInstance = new Chart(chartCanvas, {
					type: 'pie',
					data: {
						labels,
						datasets: [{
							data: values,
							backgroundColor: colors,
							borderWidth: 1
						}]
					},
					options: {
						responsive: true,
						maintainAspectRatio: false,
						plugins: {
							legend: { 
								display: true,
								position: 'right'
							}
						}
					}
				});
			}
		});

		// Cleanup when hiding chart
		return () => {
			if (chartInstance) {
				chartInstance.destroy();
				chartInstance = null;
			}
		};
	});

	function handleSort(field: string) {
		if (sortField === field) {
			sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
		} else {
			sortField = field;
			sortDirection = 'asc';
		}
	}

	function exportToCSV() {
		if (!processedData.length) return;

		const headers = tableColumns.join(',');
		const rows = processedData.map((row) =>
			tableColumns
				.map((col: string) => {
					const cell = row[col] === null || row[col] === undefined ? '' : row[col];
					const cellStr = String(cell);
					// Escape quotes and wrap in quotes if contains comma or newline
					if (cellStr.includes(',') || cellStr.includes('\n') || cellStr.includes('"')) {
						return `"${cellStr.replace(/"/g, '""')}"`;
					}
					return cellStr;
				})
				.join(',')
		);

		const csvContent = [headers, ...rows].join('\n');
		const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
		const url = URL.createObjectURL(blob);
		const link = document.createElement('a');
		link.setAttribute('href', url);
		link.setAttribute('download', `table_export_${Date.now()}.csv`);
		link.style.visibility = 'hidden';
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
	}

	function openChartConfig(type: 'bar' | 'pie') {
		chartType = type;
		// Default selections if possible
		const numericCols = tableColumns.filter(col => {
			const val = data[0]?.[col];
			return typeof val === 'number';
		});
		const stringCols = tableColumns.filter(col => {
			const val = data[0]?.[col];
			return typeof val === 'string';
		});

		if (type === 'bar') {
			chartConfig.x = stringCols[0] || tableColumns[0] || '';
			chartConfig.y = numericCols[0] || '';
		} else {
			chartConfig.category = stringCols[0] || tableColumns[0] || '';
			chartConfig.value = numericCols[0] || '';
		}
		
		chartConfigOpen = true;
	}

	function createChart() {
		// Snapshot the current processed data for the chart
		chartData = [...processedData];
		chartConfigOpen = false;
		showChart = true;
	}

	function closeChart() {
		showChart = false;
		chartType = null;
	}
</script>

<div class="flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-4 text-slate-700 shadow-sm">
	<!-- Header / Controls -->
	<div class="flex flex-wrap items-center justify-between gap-3">
		<div class="flex items-center gap-2">
			<span class="text-sm font-semibold text-slate-900">{title}</span>
			<span class="badge badge-sm border-none bg-slate-100 text-slate-600">{data.length} rows</span>
		</div>

		<div class="flex flex-1 items-center justify-end gap-2">
			<!-- Search -->
			<label
				class="input input-sm border-slate-300 focus-within:border-primary focus-within:outline-none flex w-full max-w-xs items-center gap-2 border bg-white text-slate-700"
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

			<!-- Export -->
			<button
				class="btn btn-sm btn-outline border-slate-300 text-slate-600 hover:border-slate-400 hover:bg-slate-50 hover:text-slate-800 gap-2 font-medium normal-case"
				onclick={exportToCSV}
				disabled={!data.length}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="1.5"
					stroke="currentColor"
					class="h-4 w-4"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"
					/>
				</svg>
				Export CSV
			</button>

			<!-- Chart Button -->
			<Button color="light" size="sm" class="gap-2" id="chart-menu-btn" disabled={!data.length}>
				<FileChartBarSolid class="w-4 h-4" />
				Chart
				<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-3 h-3 ml-1">
  					<path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
				</svg>
			</Button>
			<Dropdown triggeredBy="#chart-menu-btn" class="list-none p-1 w-44">
				<DropdownItem onclick={() => openChartConfig('bar')} class="text-sm py-1 px-2 rounded hover:bg-slate-100">Show as Bar Chart</DropdownItem>
				<DropdownItem onclick={() => openChartConfig('pie')} class="text-sm py-1 px-2 rounded hover:bg-slate-100">Show as Pie Chart</DropdownItem>
			</Dropdown>
		</div>
	</div>

	<!-- Table -->
	<div class="overflow-x-auto rounded-lg border border-slate-200">
		<table class="w-full min-w-full divide-y divide-slate-200 text-left text-sm text-slate-600">
			<!-- Head -->
			<thead class="bg-slate-50 text-slate-900 font-semibold">
				<tr class="divide-x divide-slate-200">
					{#each tableColumns as col}
						<th
							class="hover:bg-slate-100 cursor-pointer select-none px-4 py-2 text-xs uppercase tracking-wider transition-colors"
							onclick={() => handleSort(col)}
						>
							<div class="flex items-center gap-1">
								{col.replace(/_/g, ' ')}
								{#if sortField === col}
									<span class="text-xs">
										{#if sortDirection === 'asc'}▲{:else}▼{/if}
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
					{#each paginatedData as row}
						<tr class="hover:bg-slate-50 divide-x divide-slate-200 transition-colors">
							{#each tableColumns as col}
								<td class="whitespace-nowrap px-4 py-2">
									{#if row[col] === null || row[col] === undefined}
										<span class="text-slate-400 italic">null</span>
									{:else if typeof row[col] === 'boolean'}
										<span
											class={`badge badge-xs border-none ${row[col] ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}
										></span>
										<span class="ml-1 text-xs">{row[col]}</span>
									{:else}
										{row[col]}
									{/if}
								</td>
							{/each}
						</tr>
					{/each}
				{:else}
					<tr>
						<td colspan={tableColumns.length} class="text-slate-400 py-12 text-center">
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
			class="border-slate-100 flex items-center justify-between border-t px-2 pt-2"
		>
			<span class="text-xs text-slate-500"
				>Showing {(currentPage - 1) * itemsPerPage + 1} to {Math.min(
					currentPage * itemsPerPage,
					processedData.length
				)} of {processedData.length}</span
			>
			<div class="join">
				<button
					class="join-item btn btn-xs btn-outline border-slate-300 text-slate-600 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-800 disabled:border-slate-200 disabled:bg-transparent disabled:text-slate-300"
					disabled={currentPage === 1}
					onclick={() => (currentPage = Math.max(1, currentPage - 1))}>«</button
				>
				<button
					class="join-item btn btn-xs btn-outline border-slate-300 bg-white text-slate-700 hover:border-slate-300 hover:bg-white hover:text-slate-700 cursor-default no-animation"
					>Page {currentPage}</button
				>
				<button
					class="join-item btn btn-xs btn-outline border-slate-300 text-slate-600 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-800 disabled:border-slate-200 disabled:bg-transparent disabled:text-slate-300"
					disabled={currentPage === totalPages}
					onclick={() => (currentPage = Math.min(totalPages, currentPage + 1))}>»</button
				>
			</div>
		</div>
	{/if}
</div>

	<!-- Chart Rendering Area -->
	{#if showChart && chartType}
		<div class="mt-4 relative">
			<button 
				class="btn btn-sm btn-circle btn-ghost absolute top-0 right-0 z-10" 
				onclick={closeChart}
				title="Close Chart"
			>
				<CloseOutline class="w-5 h-5" />
			</button>
			
			<h3 class="text-sm font-semibold mb-4 text-center">Chart View ({chartType === 'bar' ? 'Bar' : 'Pie'})</h3>

			<div class="h-[300px] p-4">
				<canvas bind:this={chartCanvas}></canvas>
			</div>
		</div>
	{/if}

	<!-- Configuration Modal -->
	<Modal bind:open={chartConfigOpen} title={`Configure ${chartType === 'bar' ? 'Bar' : 'Pie'} Chart`} size="xs" autoclose={false}>
		<div class="flex flex-col gap-4">
			{#if chartType === 'bar'}
				<div>
					<Label class="mb-2">X-Axis (Category/Date)</Label>
					<Select bind:value={chartConfig.x}>
						{#each tableColumns as col}
							<option value={col}>{col}</option>
						{/each}
					</Select>
				</div>
				<div>
					<Label class="mb-2">Y-Axis (Value)</Label>
					<Select bind:value={chartConfig.y}>
						{#each tableColumns as col}
							<option value={col}>{col}</option>
						{/each}
					</Select>
				</div>
			{:else}
				<div>
					<Label class="mb-2">Category Label</Label>
					<Select bind:value={chartConfig.category}>
						{#each tableColumns as col}
							<option value={col}>{col}</option>
						{/each}
					</Select>
				</div>
				<div>
					<Label class="mb-2">Value</Label>
					<Select bind:value={chartConfig.value}>
						{#each tableColumns as col}
							<option value={col}>{col}</option>
						{/each}
					</Select>
				</div>
			{/if}
			<div class="flex justify-end gap-2 mt-2">
				<Button color="alternative" onclick={() => chartConfigOpen = false}>Cancel</Button>
				<Button color="primary" onclick={createChart}>Create Chart</Button>
			</div>
		</div>
	</Modal>

