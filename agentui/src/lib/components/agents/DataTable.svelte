<script lang="ts">
	import { onDestroy } from 'svelte';
	import { 
		createGrid, 
		ModuleRegistry, 
		AllCommunityModule,
		type GridApi, 
		type GridOptions, 
		type ColDef 
	} from 'ag-grid-community';
	import 'ag-grid-community/styles/ag-grid.css';
	import 'ag-grid-community/styles/ag-theme-alpine.css';

	// Register AG Grid modules (required for v35+)
	ModuleRegistry.registerModules([AllCommunityModule]);

	// Props
	let { data = [], columns = [] } = $props<{
		data: Record<string, any>[];
		columns?: string[];
	}>();

	let gridElement: HTMLElement | null = $state(null);
	let gridApi: GridApi | null = null;
	let gridInitialized = $state(false);

	// Build column definitions from data
	function buildColumnDefs(): ColDef[] {
		const cols = columns.length > 0 ? columns : (data && data.length > 0 ? Object.keys(data[0]) : []);
		return cols.map((col: string) => ({
			field: col,
			headerName: col,
			sortable: true,
			filter: true,
			resizable: true,
			flex: 1,
			minWidth: 100
		}));
	}

	// Export to CSV
	function exportToCSV() {
		if (gridApi) {
			gridApi.exportDataAsCsv({
				fileName: `data_export_${Date.now()}.csv`
			});
		}
	}

	// Initialize grid when element becomes available
	$effect(() => {
		if (gridElement && data && data.length > 0 && !gridInitialized) {
			const colDefs = buildColumnDefs();
			
			const gridOptions: GridOptions = {
				columnDefs: colDefs,
				rowData: data,
				defaultColDef: {
					sortable: true,
					filter: true,
					resizable: true
				},
				pagination: true,
				paginationPageSize: 10,
				paginationPageSizeSelector: [10, 25, 50, 100],
				domLayout: 'autoHeight',
				suppressRowHoverHighlight: false,
				rowSelection: 'multiple'
			};

			gridApi = createGrid(gridElement, gridOptions);
			gridInitialized = true;
		}
	});

	onDestroy(() => {
		if (gridApi) {
			gridApi.destroy();
			gridApi = null;
		}
	});
</script>

<div class="space-y-2">
	<!-- Export Button -->
	<div class="flex justify-end gap-2">
		<button class="btn btn-sm btn-outline gap-2" onclick={exportToCSV} disabled={!data || !data.length}>
			<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="h-4 w-4">
				<path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3" />
			</svg>
			Export CSV
		</button>
	</div>

	<!-- AG Grid Container -->
	{#if data && data.length > 0}
		<div
			bind:this={gridElement}
			class="ag-theme-alpine-dark border-base-300 w-full rounded-lg border"
			style="min-height: 300px;"
		></div>
	{:else}
		<div class="border-base-300 rounded-lg border p-4 text-center text-sm opacity-50">
			No data available
		</div>
	{/if}
</div>

<style>
	/* Override AG Grid theme for dark mode */
	:global(.ag-theme-alpine-dark) {
		--ag-background-color: oklch(var(--b1));
		--ag-header-background-color: oklch(var(--b2));
		--ag-odd-row-background-color: oklch(var(--b1));
		--ag-row-hover-color: oklch(var(--b2) / 0.5);
		--ag-border-color: oklch(var(--b3));
		--ag-header-foreground-color: oklch(var(--bc));
		--ag-foreground-color: oklch(var(--bc));
		--ag-secondary-foreground-color: oklch(var(--bc) / 0.7);
		--ag-input-border-color: oklch(var(--b3));
		--ag-input-focus-border-color: oklch(var(--p));
	}

	:global(.ag-theme-alpine-dark .ag-header-cell) {
		font-weight: 600;
	}

	:global(.ag-theme-alpine-dark .ag-paging-panel) {
		background-color: oklch(var(--b2));
		border-top: 1px solid oklch(var(--b3));
	}
</style>
