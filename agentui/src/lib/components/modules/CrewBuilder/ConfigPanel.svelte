<script lang="ts">
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

	let { agent, onClose, onUpdate, onDelete, inline = false } = $props();

	let showDeleteConfirm = $state(false);

	const models = ['gemini-2.5-pro', 'gpt-4', 'gpt-3.5-turbo', 'claude-3-opus', 'claude-3-sonnet'];

	// Create a local copy of data to edit
	let formData = $state({
		agent_id: '',
		name: '',
		agent_class: 'Agent',
		config: {
			model: 'gemini-2.5-pro',
			temperature: 0.7
		},
		tools: [] as string[],
		system_prompt: ''
	});

	// Track if user has manually edited the ID to stop auto-generation
	let agentIdManuallyEdited = $state(false);

	let previousAgentId = $state('');
	let readyForLiveUpdates = $state(false);

	$effect(() => {
		// Sync local state when prop changes
		if (agent && agent.agent_id !== previousAgentId) {
			readyForLiveUpdates = false;
			formData = {
				agent_id: agent.agent_id || '',
				name: agent.name || '',
				agent_class: agent.agent_class || 'Agent',
				config: {
					model: agent.config?.model || 'gemini-2.5-pro',
					temperature: agent.config?.temperature ?? 0.7
				},
				tools: [...(agent.tools || [])],
				system_prompt: agent.system_prompt || ''
			};
			agentIdManuallyEdited = false;
			previousAgentId = agent.agent_id;
			// Enable live updates next tick or after init
			setTimeout(() => {
				readyForLiveUpdates = true;
			}, 0);
		}
	});

	function emitFormUpdate(nextState = formData) {
		if (!readyForLiveUpdates) return;
		onUpdate?.(nextState);
	}

	function generateSlug(name: string) {
		if (!name) return '';
		return name
			.toLowerCase()
			.trim()
			.replace(/[^a-z0-9]+/g, '_')
			.replace(/^_+|_+$/g, '');
	}

	function handleNameInput(e: Event) {
		const value = (e.target as HTMLInputElement).value;
		formData.name = value;

		if (!agentIdManuallyEdited) {
			const slug = generateSlug(value);
			formData.agent_id = slug ? `agent_${slug}` : formData.agent_id;
		}
		emitFormUpdate();
	}

	function handleIdInput(e: Event) {
		const value = (e.target as HTMLInputElement).value;
		formData.agent_id = value;
		agentIdManuallyEdited = true;
		emitFormUpdate();
	}

	function updateField(field: string, value: any) {
		if (field.includes('.')) {
			const [parent, child] = field.split('.');
			// @ts-ignore
			formData[parent][child] = value;
		} else {
			// @ts-ignore
			formData[field] = value;
		}
		emitFormUpdate();
	}

	function handleSave() {
		onUpdate?.(formData);
		onClose?.();
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
			event.preventDefault();
			handleSave();
		}
	}

	function handleDeleteClick() {
		showDeleteConfirm = true;
	}

	function confirmDelete() {
		showDeleteConfirm = false;
		onDelete?.();
	}

	function cancelDelete() {
		showDeleteConfirm = false;
	}
</script>

<div class={inline ? 'cb-inline-wrapper' : 'fixed inset-0 z-40 flex justify-end'}>
	{#if !inline}
		<div
			class="absolute inset-0 bg-black/25 backdrop-blur-sm"
			role="button"
			tabindex="0"
			onclick={() => onClose?.()}
			onkeydown={(event) => {
				if (event.key === 'Enter' || event.key === ' ') {
					event.preventDefault();
					onClose?.();
				}
			}}
		></div>
	{/if}

	<aside class={`cb-sheet`}>
		<div class="cb-sheet-body simple">
			<!-- Header -->
			<div class="cb-inspector-head">
				<h3 class="cb-inspector-title">Agent Configuration</h3>
				<button class="cb-btn ghost sm" onclick={() => onClose?.()}> ✕ </button>
			</div>

			<!-- Form Fields -->
			<div class="space-y-4 p-1">
				<div>
					<label class="cb-label">Agent Name</label>
					<input
						type="text"
						class="cb-input"
						value={formData.name}
						oninput={handleNameInput}
						placeholder="e.g. Senior Researcher"
						autofocus
					/>
				</div>

				<div>
					<label class="cb-label">Agent ID (Slug)</label>
					<input
						type="text"
						class="cb-input font-mono text-xs"
						value={formData.agent_id}
						oninput={handleIdInput}
						placeholder="agent_senior_researcher"
					/>
				</div>

				<div class="grid grid-cols-2 gap-3">
					<div>
						<label class="cb-label">Model</label>
						<select
							class="cb-input"
							value={formData.config.model}
							onchange={(e) => updateField('config.model', (e.target as HTMLSelectElement).value)}
						>
							{#each models as m}
								<option value={m}>{m}</option>
							{/each}
						</select>
					</div>
					<div>
						<label class="cb-label">Temperature: {formData.config.temperature}</label>
						<input
							type="range"
							class="cb-range"
							min="0"
							max="1"
							step="0.1"
							value={formData.config.temperature}
							oninput={(e) =>
								updateField('config.temperature', parseFloat((e.target as HTMLInputElement).value))}
						/>
						<div class="cb-range-meta">
							<span>Precise</span>
							<span>Creative</span>
						</div>
					</div>
				</div>

				<div>
					<label class="cb-label">System Prompt / Role</label>
					<textarea
						class="cb-input"
						rows="6"
						value={formData.system_prompt}
						oninput={(e) => updateField('system_prompt', (e.target as HTMLTextAreaElement).value)}
						onkeydown={handleKeydown}
						placeholder="Define the agent's role, goals, and constraints..."
					></textarea>
					<p class="mt-1 text-xs text-slate-400">Cmd+Enter to save and close</p>
				</div>

				<div>
					<label class="cb-label">Tools</label>
					<div class="cb-chip-grid">
						{#if formData.tools.length === 0}
							<div class="py-2 text-xs italic text-slate-400">No tools connected</div>
						{/if}
						<!-- Placeholder for tool selection which wasn't in original fully implemented -->
						<button class="cb-btn ghost dashed w-full justify-center text-xs">
							+ Add Tool (Coming Soon)
						</button>
					</div>
				</div>
			</div>
		</div>

		<div class="cb-sheet-footer">
			<button class="cb-btn danger ghost" onclick={handleDeleteClick}> Delete Agent </button>
			<div class="cb-footer-actions">
				<button class="cb-btn" onclick={() => onClose?.()}>Cancel</button>
				<button class="cb-btn primary solid" onclick={handleSave}>Done</button>
			</div>
		</div>
	</aside>
</div>

<ConfirmDialog
	isOpen={showDeleteConfirm}
	title="Delete Agent"
	message="Are you sure you want to delete this agent? This action cannot be undone."
	confirmText="Delete"
	cancelText="Cancel"
	isDangerous={true}
	onconfirm={confirmDelete}
	oncancel={cancelDelete}
/>

<style>
	.cb-sheet {
		position: relative;
		z-index: 10;
		display: flex;
		flex-direction: column;
		height: 100%;
		width: 100%;
		max-width: 420px;
		background: var(--cb-sheet-bg, #fff);
		color: #0f172a;
		box-shadow: -4px 0 24px rgba(0, 0, 0, 0.1);
		border-left: 1px solid rgba(0, 0, 0, 0.05);
	}

	:global(html.dark) .cb-sheet {
		--cb-sheet-bg: #1e293b;
		color: #e2e8f0;
		border-left: 1px solid rgba(255, 255, 255, 0.05);
	}

	.cb-sheet-body {
		flex: 1;
		overflow-y: auto;
		padding: 20px;
	}

	.cb-label {
		display: block;
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-bottom: 6px;
		color: #64748b;
	}

	:global(html.dark) .cb-label {
		color: #94a3b8;
	}

	.cb-input {
		width: 100%;
		border-radius: 8px;
		border: 1px solid #cbd5e1;
		background: #fff;
		color: #0f172a;
		padding: 10px 12px;
		font-size: 14px;
		transition: all 0.2s;
	}

	.cb-input:focus {
		border-color: #3b82f6;
		box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
		outline: none;
	}

	textarea.cb-input {
		line-height: 1.5;
		resize: vertical;
	}

	:global(html.dark) .cb-input {
		background: #0f172a;
		border-color: #334155;
		color: #e2e8f0;
	}

	:global(html.dark) .cb-input:focus {
		border-color: #60a5fa;
		box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.2);
	}

	.cb-range {
		width: 100%;
		accent-color: #3b82f6;
	}

	.cb-range-meta {
		display: flex;
		justify-content: space-between;
		font-size: 10px;
		color: #94a3b8;
		margin-top: 4px;
	}

	.cb-sheet-footer {
		padding: 16px 20px;
		border-top: 1px solid #e2e8f0;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		background: var(--cb-sheet-bg, #fff);
	}

	:global(html.dark) .cb-sheet-footer {
		border-color: #334155;
	}

	.cb-footer-actions {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	/* Button Styles from Original, simplified classes */
	.cb-btn {
		display: inline-flex;
		align-items: center;
		padding: 8px 16px;
		border-radius: 8px;
		font-size: 13px;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.2s;
		border: 1px solid transparent;
		background: transparent;
		color: #64748b;
	}

	:global(html.dark) .cb-btn {
		color: #94a3b8;
	}

	.cb-btn:hover {
		background: rgba(0, 0, 0, 0.05);
		color: #0f172a;
	}

	:global(html.dark) .cb-btn:hover {
		background: rgba(255, 255, 255, 0.05);
		color: #fff;
	}

	.cb-btn.primary.solid {
		background: #3b82f6;
		color: white;
		border: 1px solid #2563eb;
		box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
	}

	.cb-btn.primary.solid:hover {
		background: #2563eb;
	}

	.cb-btn.ghost.danger {
		color: #ef4444;
	}

	.cb-btn.ghost.danger:hover {
		background: #fef2f2;
	}

	:global(html.dark) .cb-btn.ghost.danger:hover {
		background: rgba(239, 68, 68, 0.1);
	}

	.cb-inspector-head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 20px;
	}

	.cb-inspector-title {
		margin: 0;
		font-size: 16px;
		font-weight: 700;
		color: #0f172a;
	}

	:global(html.dark) .cb-inspector-title {
		color: #fff;
	}

	.cb-chip-grid {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.cb-btn.dashed {
		border: 1px dashed #cbd5e1;
	}
	:global(html.dark) .cb-btn.dashed {
		border-color: #475569;
	}

	.cb-inline-wrapper {
		position: relative;
		height: 100%;
		border-left: 1px solid #e2e8f0;
	}
	:global(html.dark) .cb-inline-wrapper {
		border-color: #334155;
	}
</style>
