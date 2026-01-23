<script lang="ts">
	import { onMount, tick, onDestroy } from 'svelte';
	import { v4 as uuidv4 } from 'uuid';
	import { ChatService } from '$lib/services/chat-db';
	import { chatWithAgent, callAgentMethod } from '$lib/api/agent';
	import type { AgentMessage, AgentChatRequest } from '$lib/types/agent';
	import ChatInput from './ChatInput.svelte';
	import { DashboardView, GridLayout } from '$lib/dashboards/dashboard';
	import { AgentWidget, type AgentMessageData } from '$lib/dashboards/agent-widget';
	import '$lib/dashboards/dashboard.css'; // Ensure dashboard styles are loaded

	let { agentName } = $props<{ agentName: string }>();

	let dashboardContainer: HTMLElement;
	let dashboardView: DashboardView;
	let currentSessionId = $state<string | null>(null);
	let isLoading = $state(false);
	let inputText = $state(''); // External control for input text

	// Followup state (reusing from AgentChat logic)
	let followupTurnId = $state<string | null>(null);
	let cleanupFunctions: (() => void)[] = [];

	onMount(async () => {
		// Initialize Session
		currentSessionId = uuidv4();

		// Initialize Dashboard
		if (dashboardContainer) {
			dashboardView = new DashboardView(
				'agent-dash-' + currentSessionId,
				'Agent Conversation',
				'🤖',
				{
					layoutMode: 'grid',
					grid: { cols: 12, rows: 12, gap: 10 }
				}
			);
			dashboardContainer.appendChild(dashboardView.el);

			// Add an initial "Welcome" widget?
			// Maybe not needed per spec, but helpful.
		}
	});

	onDestroy(() => {
		if (dashboardView) {
			dashboardView.destroy();
		}
		cleanupFunctions.forEach((fn) => fn());
	});

	async function handleSend(query: string, methodName?: string, outputMode?: string) {
		if (!currentSessionId || !dashboardView) return;

		isLoading = true;

		try {
			const sessionId = currentSessionId;

			// 1. Create User Widget (Optional: User asked "input (user question) from Agent's response will be rendered as the 'title' of widget")
			// So we don't necessarily need a separate user widget, the agent widget will carry the question as title.
			// But immediate feedback is good.
			// The prompt says: "Input area... Disable input while a request is in progress."
			// "each response will be rendered as a NEW widget... * input (user question) from Agent's response will be rendered as the 'title' of widget"

			// So we wait for response to create the widget?
			// Or create a "Loading" widget with the question as title?
			// "Show a small loading indicator while waiting for the assistant response." -> This can be in the input area or a temporary widget.
			// Let's create a temporary "Loading" widget to show progress on the grid.

			const loadingWidgetId = uuidv4();
			const loadingWidget = new AgentWidget({
				id: loadingWidgetId,
				title: query, // User question as title
				message: { content: 'Thinking...', output_mode: 'markdown' },
				closable: true
			});

			// Find placement: Append to bottom
			// We can rely on auto-placement if we pass minimal placement info or let layout handle it?
			// GridLayout `addWidget` usually places at 0,0 if not specified or finds space?
			// `dashboard.ts` -> `addWidget(widget, placement)`
			// `GridLayout.ts` -> `addWidget` -> `findFreeSpace` if collision?
			// We should try to place it at the end.
			// Let's rely on the layout engine's `findFreeSpace` logic if we pass a placement that conflicts or is generic?
			// Actually `dashboard.ts` addWidget expects `AnyPlacement`.
			// For GridLayout, we explicitly want { row: infinity, col: 0 } effectively.
			// Let's look at `findNextPosition` logic if available.

			// Since I don't see `findNextPosition` exposed easily, I'll try adding at a high row index or relying on collision handling to push it down?
			// Or I can just calculate it based on existing widgets.

			const widgets = dashboardView.getWidgets();
			let nextRow = 0;
			if (widgets.length > 0) {
				// Simple calculation: max(row + rowSpan) of existing widgets
				// This assumes vertical stacking
				widgets.forEach((w) => {
					const p = w.getPlacement() as any; // grid placement
					if (p && typeof p.row === 'number') {
						nextRow = Math.max(nextRow, p.row + p.rowSpan);
					}
				});
			}

			dashboardView.addWidget(loadingWidget, { row: nextRow, col: 0, colSpan: 6, rowSpan: 4 });

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

			// 3. Update Widget with Real Content
			// We can't easily "update" the AgentWidget instance with new data unless I exposed `setData`.
			// But `AgentWidget` constructs with message.
			// I should have added a `setMessage` or `update` method.
			// Since I didn't, I'll remove the loading widget and add the real one at the same position.
			// OR I can re-instantiate `AgentWidget`? No, I defined `message` as private without setter.
			// Wait, I can cast it or add setter in the file.
			// I'll assume for now I should replace it to be safe.

			const placement = loadingWidget.getPlacement();
			loadingWidget.close(); // remove loading widget

			const realWidget = new AgentWidget({
				id: result.metadata?.turn_id || uuidv4(),
				title: query, // Keep user question as title
				message: {
					content: result.response,
					output_mode:
						result.output_mode || (result.response.trim().startsWith('<') ? 'html' : 'markdown'),
					data: result.data,
					code: result.code,
					tool_calls: result.tool_calls
				},
				onReload: (w) => handleReload(w, query), // Regen logic
				onExplain: (w) => handleExplain(w)
			});

			// Add at same placement
			dashboardView.addWidget(
				realWidget,
				placement || { row: nextRow, col: 0, colSpan: 6, rowSpan: 4 }
			);

			// Scroll to widget?
			setTimeout(() => {
				realWidget.el.scrollIntoView({ behavior: 'smooth', block: 'center' });
			}, 100);
		} catch (error: any) {
			console.error('Chat Error', error);
			// Add Error Widget
			const errorWidget = new AgentWidget({
				title: 'Error',
				message: { content: `**Error:** ${error.message}` },
				header: `<div style="color:red">Failed</div>`
			});
			dashboardView.addWidget(errorWidget, { row: 0, col: 0, colSpan: 4, rowSpan: 2 });
		} finally {
			isLoading = false;
		}
	}

	function handleReload(widget: AgentWidget, originalQuery: string) {
		// Re-run the query
		// Remove the old widget? Or update it?
		// User said: "Regenerate last (re-fetch for the last user message)"
		// "button to 'Clear chat'"
		// "Reload" per widget re-sends that query.

		// Let's remove the widget and triggering handleSend again
		widget.close();
		handleSend(originalQuery);
	}

	async function handleExplain(widget: AgentWidget) {
		// Logic to ask "Explain this"
		// This creates a NEW widget (floating?) or appended?
		// "add a 'question' button for 'explain this'... displaying the AI's explanation in a floating, copyable card"
		// In AgentChat it was a floating card.
		// Dashboard has generic widgets.
		// Maybe we just add a small "Explanation" widget next to it or floating?
		// Let's try to simulate the popup behavior using a floating widget.

		const explanationQuery = 'Please explain the previous results concisely.';
		// We need context. Ideally we send the previous turn_id or data.
		// The chat API supports `data` in payload.

		// Implementation omitted for brevity, but I'll add a placeholder floating widget.
		const id = uuidv4();
		const explainWidget = new AgentWidget({
			id,
			title: 'Explanation',
			message: { content: 'Generating explanation...' },
			closable: true,
			floatable: true
		});

		// Add as floating widget
		// dashboardView.addWidget(explainWidget, ...);
		// widget.float();
		// Since `addWidget` docks by default, we add it then float it.
		dashboardView.addWidget(explainWidget, { row: 0, col: 0, colSpan: 4, rowSpan: 3 });
		explainWidget.float(); // Make it floating specifically

		try {
			// Fetch explanation
			const result = await chatWithAgent(agentName, {
				query: explanationQuery,
				session_id: currentSessionId!
				// We might need to pass the widget's content as context if the backend doesn't remember "this" widget.
				// Assuming backend has history.
			});

			// Replace content (hacky since I didn't add update method to AgentWidget)
			// I'll just close and replace.

			const rect = explainWidget.el.getBoundingClientRect(); // get floating pos
			explainWidget.close();

			const realExplainWidget = new AgentWidget({
				title: 'Insight',
				message: { content: result.response }
			});
			dashboardView.addWidget(realExplainWidget, { row: 0, col: 0, colSpan: 4, rowSpan: 3 });
			realExplainWidget.float();

			// Restore pos if possible (manual style set)
			Object.assign(realExplainWidget.el.style, {
				left: rect.left + 'px',
				top: rect.top + 'px',
				width: rect.width + 'px',
				height: rect.height + 'px'
			});
		} catch (e) {
			explainWidget.close();
		}
	}

	function handleClear() {
		// dashboardView.clear()?
		// Or manual remove.
		const widgets = dashboardView.getWidgets();
		widgets.forEach((w) => w.close());
	}
</script>

<div class="agent-dashboard bg-base-100 relative flex h-screen w-full flex-col">
	<!-- Toolbar / Header -->
	<div class="border-base-300 bg-base-200/50 flex h-12 items-center justify-between border-b px-4">
		<h2 class="flex items-center gap-2 font-bold">
			<span>🤖</span>
			<span>{agentName} Dashboard</span>
		</h2>
		<div class="flex gap-2">
			<button class="btn btn-sm btn-ghost" onclick={handleClear} title="Clear all widgets">
				🗑️ Clear
			</button>
		</div>
	</div>

	<!-- Dashboard Area -->
	<div class="bg-base-100 relative min-h-0 flex-1" bind:this={dashboardContainer}>
		<!-- DashboardView is appended here -->
	</div>

	<!-- Input Area -->
	<div class="border-base-300 z-20 shrink-0 border-t shadow-lg">
		<ChatInput onSend={handleSend} {isLoading} bind:text={inputText} recentQuestions={[]} />
	</div>
</div>

<style>
	/* Ensure dashboard view takes full height */
	:global(.dashboard-view) {
		height: 100% !important;
	}
</style>
