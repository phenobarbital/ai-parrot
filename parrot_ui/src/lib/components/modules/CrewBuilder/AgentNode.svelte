<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';

	let { data, selected = false } = $props();

	let agentName = $derived(data.name || 'Unnamed Agent');
	let agentId = $derived(data.agent_id || 'unknown');
	let model = $derived(data.config?.model || 'Not configured');
	let hasTools = $derived(data.tools && data.tools.length > 0);
	
	// Helper for compact ID display
	let displayId = $derived(agentId.length > 18 ? agentId.slice(0, 16) + '..' : agentId);
</script>

<div
	class={`bg-base-100 flex w-64 flex-col rounded-xl border border-base-200 shadow-sm transition-all duration-200 ${selected ? 'border-primary shadow-md ring-1 ring-primary/20' : 'hover:border-base-300'}`}
>
	<!-- Target Handles (Left) - Distributed vertically -->
	{#each ['top-1/4', 'top-1/2', 'top-3/4'] as pos, i}
		<Handle
			type="target"
			position={Position.Left}
			id={`target-${i}`}
			class={`!bg-base-100 !border-primary !h-2 !w-2 !border-[1px] ${pos} !-left-[5px]`}
		/>
	{/each}

	<div class="flex flex-col gap-1.5 p-2">
		<!-- Header -->
		<div class="flex items-center gap-1.5 border-b border-base-200/60 pb-1.5">
			<div class="flex h-5 w-5 items-center justify-center rounded bg-primary/10 text-xs">
				🤖
			</div>
			<div class="min-w-0 flex-1">
				<div class="truncate text-xs font-bold text-base-content leading-tight" title={agentName}>
					{agentName}
				</div>
				<div class="truncate font-mono text-[10px] text-base-content/60 leading-tight" title={agentId}>
					{displayId}
				</div>
			</div>
		</div>

		<!-- Details -->
		<div class="flex flex-col gap-1 px-0.5">
			<div class="flex items-center justify-between text-[10px]">
				<span class="font-medium text-base-content/60">Model</span>
				<span class="truncate font-mono text-base-content/80 max-w-[60px]" title={model}>{model.replace('gemini-', '').replace('claude-', '')}</span>
			</div>
			
			<div class="flex items-center justify-between text-[10px]">
				<span class="font-medium text-base-content/60">Temp</span>
				<span class="font-mono text-base-content/80">{data.config?.temperature ?? 0.7}</span>
			</div>

			{#if hasTools}
				<div class="mt-0.5 flex items-center justify-between rounded bg-base-200/50 px-1 py-0.5 text-[10px]">
					<span class="font-medium text-base-content/60">Tools</span>
					<div class="flex items-center gap-0.5">
						<span class="font-bold text-primary">{data.tools.length}</span>
					</div>
				</div>
			{/if}
		</div>
	</div>

	<!-- Source Handles (Right) - Distributed vertically -->
	{#each ['top-1/4', 'top-1/2', 'top-3/4'] as pos, i}
		<Handle
			type="source"
			position={Position.Right}
			id={`source-${i}`}
			class={`!bg-base-100 !border-primary !h-2 !w-2 !border-[1px] ${pos} !-right-[5px]`}
		/>
	{/each}
</div>

<style>
	/* Handle override to ensure they are visible on top of card border */
	:global(.svelte-flow__handle) {
		z-index: 10;
	}
</style>
