<script lang="ts">
	import type { TableBlockData } from '../infographic-types';

	let { title, columns, rows, highlight_first_column }: TableBlockData = $props();

	function cellValue(val: unknown): string {
		if (val === null || val === undefined) return '';
		return String(val);
	}
</script>

<div class="rounded-lg border border-border bg-card overflow-hidden">
	{#if title}
		<div class="px-4 py-2 border-b border-border bg-muted/30">
			<h3 class="text-sm font-semibold text-foreground">{title}</h3>
		</div>
	{/if}
	<div class="overflow-x-auto">
		<table class="w-full text-sm border-collapse">
			<thead>
				<tr class="bg-primary text-primary-foreground">
					{#each columns as col (col)}
						<th class="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide whitespace-nowrap">
							{col}
						</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				{#each rows as row, rowIdx (rowIdx)}
					<tr class="{rowIdx % 2 === 0 ? 'bg-background' : 'bg-muted/20'} hover:bg-primary/5 transition-colors">
						{#each row as cell, cellIdx}
							<td
								class="px-4 py-2 border-b border-border/50 text-xs {highlight_first_column && cellIdx === 0
									? 'font-semibold text-foreground'
									: 'text-foreground/80'}"
							>
								{cellValue(cell)}
							</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</div>
