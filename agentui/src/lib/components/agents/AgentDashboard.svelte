<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { v4 as uuidv4 } from 'uuid';
	import { chatWithAgent } from '$lib/api/agent';
	import type { AgentChatRequest } from '$lib/types/agent';
	import ChatInput from './ChatInput.svelte';

	// Native Svelte Dashboard Imports
	import { DashboardModel } from '$lib/stores/dashboard/store.svelte';
	import Dashboard from '$lib/components/dashboard/Dashboard.svelte';
	import { AgentWidget } from '$lib/stores/dashboard/agent-widget.svelte';

	// Core Layout Styles still needed for grid defaults if using CSS Grid
	// import '$lib/dashboards/styles.css';

	let { agentName } = $props<{ agentName: string }>();

	// Initialize Single Dashboard Model
	const dashboardModel = new DashboardModel('agent-dashboard', `${agentName} Dashboard`, '🤖');

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

			dashboardModel.addWidget(loadingWidget);

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
			const widget = dashboardModel.getWidget(loadingWidgetId);
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
			const widget = dashboardModel.getWidget(
				dashboardModel.widgets[dashboardModel.widgets.length - 1].id
			);
			if (widget instanceof AgentWidget) {
				widget.updateMessage({
					content: `**Error:** ${error.message}`,
					output_mode: 'markdown'
				});
			}
		} finally {
			isLoading = false;
		}
	}

	function handleClear() {
		dashboardModel.widgets = [];
	}
</script>

<div class="agent-dashboard bg-base-100 relative flex h-screen w-full flex-col">
	<!-- Toolbar -->
	<div class="border-base-300 bg-base-200/50 flex h-12 items-center justify-between border-b px-4">
		<h2 class="flex items-center gap-2 font-bold">
			<span>🤖</span>
			<span>{agentName} Dashboard (Native)</span>
		</h2>
		<div class="flex gap-2">
			<button class="btn btn-sm btn-ghost" onclick={handleClear} title="Clear all widgets">
				🗑️ Clear
			</button>
		</div>
	</div>

	<!-- Dashboard Area -->
	<div class="bg-base-100 relative min-h-0 flex-1">
		<Dashboard model={dashboardModel} />
	</div>

	<!-- Input Area -->
	<div class="border-base-300 z-20 shrink-0 border-t shadow-lg">
		<ChatInput onSend={handleSend} {isLoading} bind:text={inputText} recentQuestions={[]} />
	</div>
</div>
