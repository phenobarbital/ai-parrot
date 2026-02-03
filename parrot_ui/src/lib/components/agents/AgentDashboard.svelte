<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { v4 as uuidv4 } from 'uuid';
	import { chatWithAgent } from '$lib/api/agent';
	import type { AgentChatRequest } from '$lib/types/agent';
	import ChatInput from './ChatInput.svelte';

	// New Dashboard Imports
	import DashboardModule from '$lib/dashboard/components/dashboard/dashboard-module.svelte';
	import { DashboardTab } from '$lib/dashboard/domain/dashboard-tab.svelte';
	import GridLayoutComponent from '$lib/dashboard/components/layouts/grid-layout.svelte';
	import type { GridLayout } from '$lib/dashboard/domain/layouts/grid-layout.svelte';
	import { AgentWidget } from '$lib/stores/dashboard/agent-widget.svelte';

	// Core Layout Styles still needed for grid defaults if using CSS Grid
	// import '$lib/dashboards/styles.css';

	let { agentName } = $props<{ agentName: string }>();

	// Initialize Local Dashboard Tab (avoids global dashboardContainer)
	const tab = new DashboardTab({
		title: `${agentName} Dashboard`,
		icon: '🤖',
		layoutMode: 'grid'
	});
	const layout = $derived(tab.layout as GridLayout);

	let currentSessionId = $state<string | null>(null);
	let isLoading = $state(false);
	let inputText = $state('');

	let followupTurnId = $state<string | null>(null);

	onMount(async () => {
		currentSessionId = uuidv4();
	});

	async function handleSend(query: string, methodName?: string, outputMode?: string) {
		if (!currentSessionId) return;

		isLoading = true;

		try {
			const sessionId = currentSessionId;

			// 1. Add "Thinking" Widget
			const loadingWidgetId = uuidv4();
			const loadingWidget = new AgentWidget({
				id: loadingWidgetId,
				title: query,
				type: 'agent-response',
				message: {
					content:
						'<div class="flex items-center justify-center h-full"><span class="loading loading-spinner loading-lg text-primary"></span></div>',
					output_mode: 'html'
				},
				position: { x: 0, y: 0, w: 6, h: 4 } // Default pos, layout logic will be added later
			});

			layout.addWidget(loadingWidget);

			// Build Payload
			const payload: AgentChatRequest = {
				query,
				session_id: sessionId,
				...(followupTurnId && { turn_id: followupTurnId }),
				...(outputMode && outputMode !== 'default' && { output_mode: outputMode })
			};

			if (followupTurnId) followupTurnId = null;

			// 2. Call API
			const result = await chatWithAgent(agentName, payload);

			// 3. Update Widget (replace loading with real)
			const widget = layout.getWidget(loadingWidgetId);
			if (widget instanceof AgentWidget) {
				// Update content
				widget.updateMessage({
					content:
						result.response ??
						(typeof result.output === 'string' ? result.output : JSON.stringify(result.output)),
					output_mode:
						result.output_mode ||
						((result.response || '').trim().startsWith('<') ? 'html' : 'markdown'),
					data: result.data,
					code: result.code,
					tool_calls: result.tool_calls
				});
			}
		} catch (error: any) {
			console.error('Chat Error', error);
			// Update widget to error state
			const widgets = layout.getWidgets();
			const lastWidget = widgets[widgets.length - 1];
			if (lastWidget instanceof AgentWidget) {
				lastWidget.updateMessage({
					content: `**Error:** ${error.message}`,
					output_mode: 'markdown'
				});
			}
		} finally {
			isLoading = false;
		}
	}

	function handleClear() {
		const widgets = [...layout.getWidgets()];
		for (const w of widgets) {
			layout.removeWidget(w);
		}
	}
</script>

<DashboardModule title="{agentName} Dashboard (Native)" icon="🤖">
	{#snippet headerExtra()}
		<div class="flex gap-2">
			<button class="btn btn-sm btn-ghost" onclick={handleClear} title="Clear all widgets">
				🗑️ Clear
			</button>
		</div>
	{/snippet}

	<div class="flex h-full flex-col">
		<!-- Dashboard Area -->
		<div class="min-h-0 flex-1 relative bg-base-100">
			<GridLayoutComponent {layout} />
		</div>

		<!-- Input Area -->
		<div class="border-base-300 z-20 shrink-0 border-t shadow-lg">
			<ChatInput onSend={handleSend} {isLoading} bind:text={inputText} recentQuestions={[]} />
		</div>
	</div>
</DashboardModule>

<style>
	/* Styles handled by DashboardModule and UI components */
</style>
