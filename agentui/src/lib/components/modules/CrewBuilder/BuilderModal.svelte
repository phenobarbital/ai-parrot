<script lang="ts">
	import { Background, BackgroundVariant, Controls, MiniMap, SvelteFlow } from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import { onDestroy } from 'svelte';

	import AgentNode from './AgentNode.svelte';
	// import DataNode from './DataNode.svelte'; // Future use
	// import ToolNode from './ToolNode.svelte'; // Future use

	import ConfigPanel from './ConfigPanel.svelte';
	import Toolbar from './Toolbar.svelte';
	import { crewStore } from '$lib/stores/crewStore';
	import { crew as crewApi } from '$lib/api/crew';
	import { themeStore } from '$lib/stores/theme.svelte.js';

	let { showModal = false, crewId = null, viewMode = false, onClose = () => {} } = $props();

	// Constants
	const FLOW_CANVAS_THEME = {
		light: {
			bgColor: '#f8fafc',
			patternColor: '#cbd5e1',
			edgeColor: '#94a3b8'
		},
		dark: {
			bgColor: '#0f172a',
			patternColor: '#334155',
			edgeColor: '#475569'
		}
	};

	// Default flow setup
	const nodeTypes = {
		agentNode: AgentNode
	};

	// Local State
	let showConfigPanel = $state(false);
	let selectedNodeId = $state<string | null>(null);
	let isCrewLoading = $state(false);
	let loadError = $state('');
	let jsonError = $state('');
	// @ts-ignore
	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	let loadRequestId = 0;
	// @ts-ignore
	// @ts-ignore
	let isApplyingJsonChange = $state(false);

	// Direct store usage for Svelte Flow 2-way binding
	// @ts-ignore
	let selectedNode = $derived($crewStore.nodes.find((n) => n.id === selectedNodeId));
	let colorScheme = $state('light');
	// @ts-ignore
	let crewMetadata = $state({
		name: '',
		description: '',
		execution_mode: 'sequential'
	});

	let builderTab = $state('visual');
	let uploading = $state(false);
	let uploadNotice = $state<{ type: 'success' | 'error'; message: string; tone: string } | null>(
		null
	);
	let noticeTimeout: any = null;

	// Simplified UI state for migration (removing complex collapsible logic for now if not needed or keeping defaults)
	/*
	let detailsCollapsed = $state(false);
	let inspectorCollapsed = $state(false);
	let collectionsCollapsed = $state(false);
    */

	// Subscribe to stores
	const flowCanvasTheme = $derived.by(
		() => FLOW_CANVAS_THEME[colorScheme as 'light' | 'dark'] ?? FLOW_CANVAS_THEME.light
	);

	$effect(() => {
		// Sync theme
		colorScheme = $themeStore.currentTheme === 'dark' ? 'dark' : 'light';
	});

	$effect(() => {
		const unsubscribeCrew = crewStore.subscribe((value) => {
			crewMetadata = value.metadata;
		});

		return () => {
			unsubscribeCrew();
		};
	});

	// Reset or Load on Open
	$effect(() => {
		if (showModal && crewId) {
			loadCrewById(crewId);
		} else if (showModal && !crewId) {
			crewStore.reset();
			const current = crewStore.exportToJSON();
			// @ts-ignore
			if (!current?.agents?.length) {
				// @ts-ignore
				crewStore.importCrew({
					name: 'New Crew',
					agents: [],
					description: 'A new agent crew',
					execution_mode: 'sequential'
				});
				// Add one initial agent
				crewStore.addAgent();
			}
		}
	});

	async function loadCrewById(id: string) {
		loadError = '';
		isCrewLoading = true;
		// const requestId = ++loadRequestId;

		if (!id) {
			crewStore.reset();
			selectedNodeId = null;
			showConfigPanel = false;
			isCrewLoading = false;
			return;
		}

		try {
			const data = await crewApi.getCrewById(id);
			crewStore.importCrew(data);
		} catch (error: any) {
			console.error('Failed to load crew', error);
			loadError = error?.message || 'Failed to load crew';
		} finally {
			isCrewLoading = false;
		}
	}

	function handleNodeClick(event: any) {
		// SvelteFlow 5 passes { event, node } directly
		const node = event.node || event.detail?.node;

		if (node && node.type === 'agentNode') {
			selectedNodeId = node.id;
			showConfigPanel = true;
		} else {
			selectedNodeId = null;
			showConfigPanel = false;
		}
	}

	function handlePaneClick() {
		// Deselect if clicking on empty space
		selectedNodeId = null;
		showConfigPanel = false;
	}

	function onConnect(connection: any) {
		crewStore.addEdge(connection);
	}

	function handleAddAgent() {
		crewStore.addAgent();
	}

	function closeConfigPanel() {
		selectedNodeId = null;
		showConfigPanel = false;
	}

	function handleUpdateAgent(data: any) {
		if (!selectedNodeId) return;
		crewStore.updateAgent(selectedNodeId, data);
	}

	function handleDeleteAgent() {
		if (!selectedNodeId) return;
		crewStore.deleteAgent(selectedNodeId);
		closeConfigPanel();
	}

	function handleExport() {
		const crewJSON = crewStore.exportToJSON();
		const blob = new Blob([JSON.stringify(crewJSON, null, 2)], { type: 'application/json' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `${crewJSON.name || 'crew'}.json`;
		a.click();
		URL.revokeObjectURL(url);
	}

	// JSON Editor logic omitted for brevity/complexity reduction in first pass, using visual builder primarily.
	// Can migrate `ace-builds` integration if strict requirement, but simplified for now.

	// @ts-ignore
	function updateMetadata(next) {
		crewStore.updateMetadata(next);
	}

	async function handleSaveCrew() {
		dismissNotice();
		try {
			uploading = true;
			const payload = crewStore.exportToJSON();
			// @ts-ignore
			const response = await crewApi.createCrew(payload);
			uploadNotice = {
				// @ts-ignore
				message: response?.name || payload.name,
				tone: 'positive',
				type: 'success'
			};
		} catch (error: any) {
			console.error('Save failed', error);
			uploadNotice = {
				message: error.message || 'Failed to save crew',
				tone: 'critical',
				type: 'error'
			};
		} finally {
			uploading = false;
			// Auto dismiss
			noticeTimeout = setTimeout(() => {
				dismissNotice();
			}, 3000);
		}
	}

	function dismissNotice() {
		uploadNotice = null;
		if (noticeTimeout) {
			clearTimeout(noticeTimeout);
			noticeTimeout = null;
		}
	}

	onDestroy(() => {
		if (noticeTimeout) {
			clearTimeout(noticeTimeout);
		}
	});
</script>

{#if showModal}
	<div class={`cb-shell ${colorScheme}`}>
		<div class="cb-shell-tools">
			<!-- Top Toolbar -->
			<Toolbar {handleAddAgent} {handleExport} handleClose={onClose} {viewMode} />
		</div>

		<div class="cb-workspace">
			<div class="cb-primary">
				{#if builderTab === 'visual'}
					<!-- Visual Flow Canvas -->
					<div
						class="crew-flow-surface"
						style={`--crew-flow-bg:${flowCanvasTheme.bgColor}; --crew-flow-edge:${flowCanvasTheme.edgeColor}; --crew-flow-pattern:${flowCanvasTheme.patternColor};`}
					>
						{#if isCrewLoading}
							<div
								class="absolute inset-0 z-10 flex items-center justify-center bg-white/50 dark:bg-black/50"
							>
								<span class="loading loading-spinner loading-lg"></span>
							</div>
						{/if}

						<!-- Svelte Flow Component -->
						<SvelteFlow
							nodes={$crewStore.nodes}
							edgeTypes={{}}
							{nodeTypes}
							edges={$crewStore.edges}
							fitView
							on:nodeclick={handleNodeClick}
							on:paneclick={handlePaneClick}
							on:connect={onConnect}
						>
							<Controls showZoom={true} showFitView={true} />
							<MiniMap
								height={100}
								width={140}
								nodeColor={colorScheme === 'dark' ? '#334155' : '#e2e8f0'}
								maskColor={colorScheme === 'dark' ? 'rgba(0,0,0,0.3)' : 'rgba(255,255,255,0.6)'}
							/>
							<Background
								variant={BackgroundVariant.Dots}
								gap={32}
								size={1}
								bgColor={flowCanvasTheme.bgColor}
								patternColor={flowCanvasTheme.patternColor}
							/>
						</SvelteFlow>
					</div>
				{/if}
			</div>

			<!-- Configuration Side Panel -->
			{#if showConfigPanel && selectedNodeId}
				<div class="cb-inspector-panel">
					<ConfigPanel
						agent={$crewStore.nodes.find((n) => n.id === selectedNodeId)?.data}
						onClose={closeConfigPanel}
						onUpdate={handleUpdateAgent}
						onDelete={handleDeleteAgent}
						inline={true}
					/>
				</div>
			{/if}
		</div>
	</div>
{/if}

<style>
	/* Shell Layout */
	.cb-shell {
		position: fixed;
		inset: 0;
		z-index: 50;
		background: #f1f5f9;
		display: flex;
		flex-direction: column;
		font-family: 'Inter', sans-serif;
	}

	:global(.cb-shell.dark) {
		background: #020617;
		color: #e2e8f0;
	}

	.cb-shell-tools {
		flex-shrink: 0;
		z-index: 20;
	}

	.cb-workspace {
		flex: 1;
		display: flex;
		overflow: hidden;
		position: relative;
	}

	.cb-primary {
		flex: 1;
		position: relative;
		display: flex;
		flex-direction: column;
	}

	.crew-flow-surface {
		flex: 1;
		position: relative;
		background: var(--crew-flow-bg);
	}

	.cb-inspector-panel {
		width: 400px;
		background: white;
		border-left: 1px solid #e2e8f0;
		z-index: 10;
		height: 100%;
		overflow-y: auto;
	}

	:global(.cb-shell.dark) .cb-inspector-panel {
		background: #0f172a;
		border-color: #1e293b;
	}
</style>
