<script lang="ts">
	import { untrack } from 'svelte';

	interface Props {
		data: Record<string, any>[];
		columns?: string[];
		title?: string;
	}

	let { data = [], columns = [], title = 'Table View' } = $props<Props>();

	// State
	let searchQuery = $state('');
	let currentPage = $state(1);
	let itemsPerPage = 10;
	let sortField = $state<string | null>(null);
	let sortDirection = $state<'asc' | 'desc'>('asc');

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
				.map((col) => {
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
</script>

<div class="border-base-300 bg-base-100 flex flex-col gap-4 rounded-xl border p-4 shadow-sm">
	<!-- Header / Controls -->
	<div class="flex flex-wrap items-center justify-between gap-3">
		<div class="flex items-center gap-2">
			<span class="text-sm font-semibold">{title}</span>
			<span class="badge badge-sm badge-ghost">{data.length} rows</span>
		</div>

		<div class="flex flex-1 items-center justify-end gap-2">
			<!-- Search -->
			<label class="input input-bordered input-sm flex w-full max-w-xs items-center gap-2">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 16 16"
					fill="currentColor"
					class="h-4 w-4 opacity-70"
				>
					<path
						fill-rule="evenodd"
						d="M9.965 11.026a5 5 0 1 1 1.06-1.06l2.755 2.754a.75.75 0 1 1-1.06 1.06l-2.755-2.754ZM10.5 7a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0Z"
						clip-rule="evenodd"
					/>
				</svg>
				<input type="text" class="grow" placeholder="Search..." bind:value={searchQuery} />
			</label>

			<!-- Export -->
			<button class="btn btn-sm btn-outline gap-2" onclick={exportToCSV} disabled={!data.length}>
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
		</div>
	</div>

	<!-- Table -->
	<div class="border-base-200 overflow-x-auto rounded-lg border">
		<table class="table-sm table w-full">
			<!-- Head -->
			<thead class="bg-base-200/50 text-base-content/70">
				<tr>
					{#each tableColumns as col}
						<th
							class="hover:text-base-content cursor-pointer select-none"
							onclick={() => handleSort(col)}
						>
							<div class="flex items-center gap-1">
								{col.toUpperCase().replace(/_/g, ' ')}
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
			<tbody>
				{#if paginatedData.length > 0}
					{#each paginatedData as row}
						<tr class="hover:bg-base-200/50 transition-colors">
							{#each tableColumns as col}
								<td class="whitespace-nowrap">
									{#if row[col] === null || row[col] === undefined}
										<span class="text-base-content/30 italic">null</span>
									{:else if typeof row[col] === 'boolean'}
										<span class={`badge badge-xs ${row[col] ? 'badge-success' : 'badge-error'}`}
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
						<td colspan={tableColumns.length} class="py-8 text-center opacity-50">
							No results found
						</td>
					</tr>
				{/if}
			</tbody>
		</table>
	</div>

	<!-- Pagination -->
	{#if totalPages > 1}
		<div class="flex items-center justify-between px-2">
			<span class="text-xs opacity-50"
				>Showing {(currentPage - 1) * itemsPerPage + 1} to {Math.min(
					currentPage * itemsPerPage,
					processedData.length
				)} of {processedData.length}</span
			>
			<div class="join">
				<button
					class="join-item btn btn-xs"
					disabled={currentPage === 1}
					onclick={() => (currentPage = Math.max(1, currentPage - 1))}>«</button
				>
				<button class="join-item btn btn-xs no-animation">Page {currentPage}</button>
				<button
					class="join-item btn btn-xs"
					disabled={currentPage === totalPages}
					onclick={() => (currentPage = Math.min(totalPages, currentPage + 1))}>»</button
				>
			</div>
		</div>
	{/if}
</div>
