<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';

	let { data, selected = false } = $props();

	let agentName = $derived(data.name || 'Unnamed Agent');
	let agentId = $derived(data.agent_id || 'unknown');
	let model = $derived(data.config?.model || 'Not configured');
	let hasTools = $derived(data.tools && data.tools.length > 0);
</script>

<div
	class={`card card-compact bg-base-100 w-60 border-2 transition-shadow ${selected ? 'border-primary shadow-lg' : 'border-base-200 shadow'}`}
>
	<!-- Target Handle (Left) -->
	<Handle
		type="target"
		position={Position.Left}
		class="!bg-base-100 !border-primary !h-2.5 !w-2.5 !border-2"
	/>

	<div class="card-body gap-2 p-3">
		<!-- Header -->
		<div class="border-base-200 flex items-center gap-2 border-b pb-2">
			<div class="text-2xl">🤖</div>
			<div class="min-w-0">
				<div class="text-base-content truncate text-xs font-bold leading-tight" title={agentName}>
					{agentName}
				</div>
				<div
					class="text-base-content/60 truncate font-mono text-[10px] leading-tight"
					title={agentId}
				>
					{agentId}
				</div>
			</div>
		</div>

		<!-- Details -->
		<div class="space-y-1 text-[10px]">
			<div class="flex items-center justify-between">
				<span class="text-base-content/70 font-medium">Model:</span>
				<span
					class="text-base-content bg-base-200 rounded px-1 py-0.5 font-mono text-[10px] leading-none"
					>{model}</span
				>
			</div>
			{#if hasTools}
				<div class="flex items-center justify-between">
					<span class="text-base-content/70 font-medium">Tools:</span>
					<span class="text-primary text-[10px] font-medium">{data.tools.length}</span>
				</div>
			{/if}
			<div class="flex items-center justify-between">
				<span class="text-base-content/70 font-medium">Temp:</span>
				<span class="text-base-content text-[10px]">{data.config?.temperature ?? 0.7}</span>
			</div>
		</div>
	</div>

	<!-- Source Handle (Right) -->
	<Handle
		type="source"
		position={Position.Right}
		class="!bg-base-100 !border-primary !h-2.5 !w-2.5 !border-2"
	/>
</div>

<style>
	/* No custom CSS needed, usage of DaisyUI/Tailwind */
</style>
