<script lang="ts">
	import { registry } from '$lib/stores/dashboard/registry.svelte';
	import type { Dashboard } from '$lib/stores/dashboard/dashboard.svelte';
	import { Widget } from '$lib/stores/dashboard/widget.svelte';
	import { AgentWidget } from '$lib/stores/dashboard/agent-widget.svelte';

	let { dashboard, isOpen = $bindable(false) } = $props<{
		dashboard: Dashboard;
		isOpen: boolean;
	}>();

	let dialog: HTMLDialogElement;
	let widgetName = $state('New Widget');
	let selectedType = $state<string | null>(null);

	$effect(() => {
		if (isOpen) dialog?.showModal();
		else dialog?.close();
	});

	function close() {
		isOpen = false;
	}

	function addWidget() {
		if (!selectedType) return;

		const def = registry.get(selectedType);
		if (!def) return;

		let w: Widget;
		// Special case for AgentWidget or generic factory
		if (def.type === 'agent-chat') {
			w = new AgentWidget({
				title: widgetName,
				type: def.type,
				...def.defaultConfig
			});
		} else {
			w = new Widget({
				title: widgetName,
				type: def.type,
				...def.defaultConfig
			});
		}

		dashboard.addWidget(w);
		close();
	}
</script>

<dialog class="modal" bind:this={dialog} onclose={close}>
	<div class="modal-box flex h-[80vh] w-11/12 max-w-4xl flex-col overflow-hidden p-0">
		<!-- Header -->
		<div class="bg-base-100 flex items-center justify-between border-b p-4">
			<h3 class="text-lg font-bold">Add a Runtime Widget</h3>
			<button class="btn btn-sm btn-ghost btn-circle" onclick={close}>✕</button>
		</div>

		<!-- Content -->
		<div class="bg-base-200/50 flex-1 overflow-y-auto p-6">
			<div class="form-control mb-6 w-full">
				<label class="label">
					<span class="label-text">Widget Name</span>
				</label>
				<input
					type="text"
					bind:value={widgetName}
					class="input input-bordered w-full"
					placeholder="Type here"
				/>
			</div>

			<div class="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
				{#each registry.getAll() as def}
					<button
						class="card bg-base-100 hover:border-primary border border-transparent text-left shadow-sm transition-all hover:shadow-md"
						class:ring-2={selectedType === def.type}
						class:ring-primary={selectedType === def.type}
						onclick={() => (selectedType = def.type)}
					>
						<div class="card-body flex flex-col items-center gap-2 p-4 text-center">
							<div class="text-4xl">{def.icon}</div>
							<div class="font-bold">{def.name}</div>
							<div class="text-base-content/70 text-xs">{def.description}</div>
						</div>
					</button>
				{/each}
			</div>
		</div>

		<!-- Footer -->
		<div class="modal-action bg-base-100 m-0 border-t p-4">
			<button class="btn" onclick={close}>Cancel</button>
			<button class="btn btn-primary" disabled={!selectedType} onclick={addWidget}
				>Add Widget</button
			>
		</div>
	</div>
	<form method="dialog" class="modal-backdrop">
		<button>close</button>
	</form>
</dialog>
