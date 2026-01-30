<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { v4 as uuidv4 } from 'uuid';
	import { ChatService } from '$lib/services/chat-db';
	import { chatWithAgent, callAgentMethod } from '$lib/api/agent';
	import type { AgentMessage, AgentChatRequest } from '$lib/types/agent';
	import ChatBubble from './ChatBubble.svelte';
	import ChatInput from './ChatInput.svelte';
	import ConversationList from './ConversationList.svelte';

	// Props
	let { agentName } = $props<{ agentName: string }>();

	// State
	let currentSessionId = $state<string | null>(null);
	let messages = $state<AgentMessage[]>([]);
	let pendingQuestions = $state<Set<string>>(new Set()); // Track pending message IDs
	let chatContainer = $state<HTMLElement>();
	let drawerOpen = $state(false); // Mobile drawer
	let inputText = $state(''); // External control for input text

	// Followup state
	let followupTurnId = $state<string | null>(null);
	let followupData = $state<any>(null);

	// Explanation state
	let explanationResult = $state<string | null>(null);
	let isExplaining = $state(false);

	// Derived: are there any pending questions?
	let hasPendingQuestions = $derived(pendingQuestions.size > 0);

	// Derived: recent user questions for quick repeat
	let recentQuestions = $derived(
		messages
			.filter((m) => m.role === 'user')
			.slice(-10)
			.reverse()
			.map((m) => m.content)
	);

	// Load messages when session changes
	$effect(() => {
		if (currentSessionId) {
			loadMessages(currentSessionId);
		} else {
			messages = [];
		}
	});

	async function loadMessages(sessionId: string) {
		messages = await ChatService.getMessages(sessionId);
		await tick();
		scrollToBottom();
	}

	function unescapeHtml(html: string): string {
		if (!html) return html;
		// If the HTML looks like it has JSON-style escapes for quotes/newlines, clean them.
		// NOTE: Standard JSON parsing handles this, but user feedback indicates explicit cleanup might be needed
		// for some backend responses.
		return html.replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\t/g, '\t');
	}

	function scrollToBottom() {
		// Auto scroll logic (existing)
		if (chatContainer) {
			chatContainer.scrollTop = chatContainer.scrollHeight;
		}
	}

	async function handleNewConversation() {
		const newId = uuidv4();
		await ChatService.createConversation(agentName, newId);
		currentSessionId = newId;
		drawerOpen = false;
	}

	async function handleSelectConversation(id: string) {
		currentSessionId = id;
		drawerOpen = false;
	}

	async function handleSend(query: string, methodName?: string, outputMode?: string) {
		if (!currentSessionId) {
			await handleNewConversation();
		}
		const sessionId = currentSessionId!;

		// 1. Create User Message
		const userMsgId = uuidv4();
		const userMsg: AgentMessage = {
			id: userMsgId,
			role: 'user',
			content: query,
			timestamp: new Date(),
			metadata: {
				session_id: sessionId,
				model: '',
				provider: '',
				turn_id: '',
				response_time: 0
			}
		};

		// Create a placeholder for the pending response
		const pendingResponseId = uuidv4();
		const pendingMsg: AgentMessage = {
			id: pendingResponseId,
			role: 'assistant',
			content: '',
			timestamp: new Date(),
			metadata: {
				session_id: sessionId,
				model: 'loading',
				provider: '',
				turn_id: '',
				response_time: 0
			}
		};

		// Optimistic Update with both user message and pending placeholder
		messages = [...messages, userMsg, pendingMsg];
		pendingQuestions = new Set([...pendingQuestions, pendingResponseId]);

		await ChatService.saveMessage(userMsg);
		await tick();
		scrollToBottom();

		try {
			// Build format_kwargs for output_mode
			const formatKwargs =
				outputMode && outputMode !== 'default'
					? {
							output_format: 'html',
							html_mode: 'complete',
							table_mode: 'ag-grid'
						}
					: undefined;

			const payload: AgentChatRequest = {
				query,
				session_id: sessionId,
				// Include followup data if replying to a previous response
				...(followupTurnId && { turn_id: followupTurnId }),
				...(followupData && { data: followupData }),
				...(outputMode && outputMode !== 'default' && { output_mode: outputMode }),
				...(formatKwargs && { format_kwargs: formatKwargs })
			};

			// Clear followup state after building payload
			if (followupTurnId) {
				followupTurnId = null;
				followupData = null;
			}

			// 2. Call API (non-blocking - allows more questions)
			const result = methodName
				? await callAgentMethod(agentName, methodName, payload)
				: await chatWithAgent(agentName, payload);

			// 3. Replace pending message with actual response
			const isHtml =
				result.response.trim().startsWith('<!DOCTYPE html') ||
				result.response.trim().startsWith('<html');
			const effectiveOutputMode = result.output_mode || (isHtml ? 'html' : 'default');

			const assistantMsg: AgentMessage = {
				id: result.metadata?.turn_id || pendingResponseId,
				role: 'assistant',
				content: result.response,
				timestamp: new Date(),
				metadata: result.metadata,
				data: result.data,
				code: result.code,
				output: result.output,
				tool_calls: result.tool_calls,
				output_mode: effectiveOutputMode,
				// Store HTML response for iframe rendering if it looks like HTML or output_mode says so
				htmlResponse:
					effectiveOutputMode !== 'default' || isHtml ? unescapeHtml(result.response) : null
			};

			messages = messages.map((m) => (m.id === pendingResponseId ? assistantMsg : m));
			await ChatService.saveMessage(assistantMsg);

			// Update title if it's the first message
			if (messages.filter((m) => m.role === 'user').length <= 1) {
				const title = query.split(' ').slice(0, 4).join(' ');
				await ChatService.updateConversationTitle(sessionId, title);
			}
		} catch (error: any) {
			console.error('Chat Error', error);
			const errorMsg: AgentMessage = {
				id: pendingResponseId,
				role: 'assistant',
				content: `**Error:** Failed to get response from agent. \n\n\`${error.message}\``,
				timestamp: new Date(),
				metadata: {
					session_id: sessionId,
					model: 'system',
					provider: '',
					turn_id: '',
					response_time: 0,
					is_error: true // Flag for retry logic
				}
			};
			messages = messages.map((m) => (m.id === pendingResponseId ? errorMsg : m));
			await ChatService.saveMessage(errorMsg);
		} finally {
			pendingQuestions.delete(pendingResponseId);
			pendingQuestions = new Set(pendingQuestions);
			await tick();
			scrollToBottom();
		}
	}

	function handleRepeat(text: string) {
		inputText = text;
	}

	function handleFollowup(turnId: string, data: any) {
		followupTurnId = turnId;
		followupData = data;
		// Focus on input would be nice, but we'll just show the indicator
	}

	function clearFollowup() {
		followupTurnId = null;
		followupData = null;
	}

	async function handleExplain(turnId: string, data: any) {
		isExplaining = true;
		explanationResult = null; // Reset previous explanation

		try {
			if (!currentSessionId) return;

			// Construct a specialized payload for explanation
			const payload: AgentChatRequest = {
				query: 'Please explain these results in a concise manner.',
				session_id: currentSessionId,
				turn_id: turnId,
				data: data // Send the specific data to explain
			};

			// Use the existing chat mechanism but don't add it to the message history visibly
			// We just want the response text
			const result = await chatWithAgent(agentName, payload);

			explanationResult = result.response;
		} catch (error: any) {
			console.error('Explanation Error', error);
			explanationResult = `Failed to get explanation: ${error.message}`;
		} finally {
			isExplaining = false;
		}
	}

	function closeExplanation() {
		explanationResult = null;
	}

	function copyExplanation() {
		if (explanationResult) {
			navigator.clipboard.writeText(explanationResult);
		}
	}

	function isPending(msgId: string): boolean {
		return pendingQuestions.has(msgId);
	}

	async function handleRetry(msgId: string) {
		const msgIndex = messages.findIndex((m) => m.id === msgId);
		if (msgIndex === -1) return;

		// The user message should be immediately before the error message
		const userMsg = messages[msgIndex - 1];
		if (!userMsg || userMsg.role !== 'user') {
			console.error('Cannot retry: previous message not found or not from user');
			return;
		}

		// Remove the error message from the UI
		messages = messages.filter((m) => m.id !== msgId);
		
		// Remove from DB if needed (optional based on persistence strategy, but good for cleanup)
		// await ChatService.deleteMessage(msgId); 

		// Resend the user's query
		await handleSend(userMsg.content);
	}
</script>

<div class="bg-base-100 relative flex h-full w-full overflow-hidden">
	<!-- Sidebar (Desktop) -->
	<div class="hidden h-full flex-none md:flex">
		<ConversationList
			{agentName}
			{currentSessionId}
			onSelect={handleSelectConversation}
			onNew={handleNewConversation}
		/>
	</div>

	<!-- Mobile Drawer Toggle -->
	<div class="absolute left-4 top-4 z-20 md:hidden">
		<button
			class="btn btn-circle btn-sm btn-ghost"
			title="Open menu"
			onclick={() => (drawerOpen = !drawerOpen)}
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				fill="none"
				viewBox="0 0 24 24"
				stroke-width="1.5"
				stroke="currentColor"
				class="h-6 w-6"
			>
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5"
				/>
			</svg>
		</button>
	</div>

	<!-- Mobile Drawer Overlay -->
	{#if drawerOpen}
		<div
			class="absolute inset-0 z-30 bg-black/50 md:hidden"
			onclick={() => (drawerOpen = false)}
			role="button"
			tabindex="0"
			onkeydown={(e) => e.key === 'Escape' && (drawerOpen = false)}
		></div>
		<div
			class="bg-base-200 absolute inset-y-0 left-0 z-40 w-80 transform shadow-xl transition-transform duration-300 md:hidden {drawerOpen
				? 'translate-x-0'
				: '-translate-x-full'}"
		>
			<ConversationList
				{agentName}
				{currentSessionId}
				onSelect={handleSelectConversation}
				onNew={handleNewConversation}
			/>
		</div>
	{/if}

	<!-- Main Chat Area -->
	<div class="bg-base-100 flex h-full min-h-0 min-w-0 flex-1 flex-col">
		{#if !currentSessionId}
			<!-- Empty State -->
			<div class="flex flex-1 flex-col items-center justify-center p-8 text-center opacity-50">
				<div class="bg-base-200 mb-4 flex h-24 w-24 items-center justify-center rounded-full">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="1.5"
						stroke="currentColor"
						class="h-12 w-12"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z"
						/>
					</svg>
				</div>
				<h2 class="mb-2 text-2xl font-bold">Welcome to Agent Chat</h2>
				<p>Select a conversation or start a new one to begin.</p>
				<button class="btn btn-primary mt-4" onclick={handleNewConversation}>Start Chatting</button>
			</div>
		{:else}
			<!-- Messages - scrollable area with constrained height -->
			<div bind:this={chatContainer} class="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-2">
				{#each messages as msg (msg.id)}
					{#if isPending(msg.id)}
						<!-- Pending Response Placeholder -->
						<div class="chat chat-start">
							<div class="chat-header mb-1 text-xs opacity-50">Agent</div>
							<div class="chat-bubble bg-[#f9fafb] text-slate-900 border border-slate-200 shadow-sm flex items-center gap-3 py-4 px-6 !w-auto">
								<span class="loading loading-spinner text-primary loading-md"></span>
								<span class="font-medium text-sm animate-pulse">Thinking...</span>
							</div>
						</div>
					{:else}
						<ChatBubble
							message={msg}
							onRepeat={handleRepeat}
							onFollowup={handleFollowup}
							onExplain={handleExplain}
							onRetry={handleRetry}
						/>
					{/if}
				{/each}
			</div>

			<!-- Explanation Floating Card -->
			{#if isExplaining || explanationResult}
				<div
					class="absolute bottom-24 right-4 z-20 w-80 transform transition-all duration-300 ease-in-out sm:w-96"
				>
					<div
						class="card card-compact bg-warning/20 border-warning/30 text-base-content border shadow-xl"
					>
						<div class="card-body">
							<div class="mb-1 flex items-start justify-between">
								<h3 class="card-title flex items-center gap-2 text-sm">
									<svg
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
										stroke-width="1.5"
										stroke="currentColor"
										class="size-4"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z"
										/>
									</svg>
									AI Insight
								</h3>
								<div class="flex gap-1">
									{#if explanationResult}
										<button
											class="btn btn-ghost btn-xs btn-square"
											title="Copy"
											onclick={copyExplanation}
										>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												fill="none"
												viewBox="0 0 24 24"
												stroke-width="1.5"
												stroke="currentColor"
												class="size-4"
											>
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													d="M15.666 3.888A2.25 2.25 0 0 0 13.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 0 1-.75.75H9a.75.75 0 0 1-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 0 1-2.25 2.25H6.75A2.25 2.25 0 0 1 4.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 0 1 1.927-.184"
												/>
											</svg>
										</button>
									{/if}
									<button
										class="btn btn-ghost btn-xs btn-square"
										title="Close"
										onclick={closeExplanation}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke-width="1.5"
											stroke="currentColor"
											class="size-4"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M6 18 18 6M6 6l12 12"
											/>
										</svg>
									</button>
								</div>
							</div>

							{#if isExplaining}
								<div class="flex items-center gap-2 py-4">
									<span class="loading loading-spinner text-warning loading-sm"></span>
									<span class="text-sm opacity-80">Generating explanation...</span>
								</div>
							{:else if explanationResult}
								<div class="prose prose-sm max-h-60 overflow-y-auto text-sm">
									{explanationResult}
								</div>
							{/if}
						</div>
					</div>
				</div>
			{/if}

			<!-- Input - Always enabled for concurrent questions -->
			<div class="shrink-0">
				<ChatInput
					onSend={handleSend}
					isLoading={false}
					bind:text={inputText}
					{followupTurnId}
					onClearFollowup={clearFollowup}
					{recentQuestions}
				/>
			</div>

			<!-- Pending indicator bar -->
			{#if hasPendingQuestions}
				<div
					class="bg-base-200 border-base-300 flex items-center justify-center gap-2 border-t px-4 py-2 text-sm"
				>
					<span class="loading loading-spinner loading-xs"></span>
					<span
						>{pendingQuestions.size} question{pendingQuestions.size > 1 ? 's' : ''} pending...</span
					>
				</div>
			{/if}
		{/if}
	</div>
</div>
