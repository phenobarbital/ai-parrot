<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { marked } from 'marked';
	import { v4 as uuidv4 } from 'uuid';
	import { Grid } from 'gridjs';
	import 'gridjs/dist/theme/mermaid.css'; // or any theme
	import hljs from 'highlight.js';
	import 'highlight.js/styles/github-dark.css';

	import { agentClient, type ChatResponse } from '$lib/api/client';
	import {
		db,
		saveConversation,
		saveMessage,
		getConversationHistory,
		getAllConversations,
		type Conversation,
		type Message
	} from '$lib/persistence/chat-db';

	// Props
	interface Props {
		agentName?: string;
		methodName?: string; // Optional default method
	}
	let { agentName = 'default', methodName = '' } = $props();

	// State
	let query = $state('');
	let conversations = $state<Conversation[]>([]);
	let currentSessionId = $state<string>(uuidv4());
	let messages = $state<Message[]>([]);
	let isLoading = $state(false);
	let showAdvanced = $state(false);
	let customMethodName = $state(methodName);
	let errorToast = $state<string | null>(null);

	// Sidebar
	let sidebarOpen = $state(true);

	// Load conversations on mount
	onMount(async () => {
		await loadConversations();
		// If we want to restore last conversation? For now just start new or empty.
	});

	async function loadConversations() {
		conversations = await getAllConversations();
	}

	async function selectConversation(conv: Conversation) {
		currentSessionId = conv.session_id;
		messages = await getConversationHistory(conv.session_id);
		// Scroll to bottom
		await tick();
		scrollToBottom();
	}

	function startNewChat() {
		currentSessionId = uuidv4();
		messages = [];
		query = '';
	}

	async function sendMessage() {
		if (!query.trim()) return;

		const userText = query;
		query = ''; // Clear input immediately
		isLoading = true;

		// 1. Create and Save User Message
		const turnId = uuidv4();
		const userMsg: Message = {
			turn_id: turnId,
			session_id: currentSessionId,
			role: 'user',
			content: userText,
			timestamp: Date.now()
		};

		// Optimistic UI
		messages = [...messages, userMsg];
		await tick();
		scrollToBottom();

		// Save to DB
		// First conversation record if needed
		if (messages.length === 1) {
			await saveConversation(currentSessionId, agentName, userText);
			await loadConversations(); // Refresh list
		}
		await saveMessage(userMsg);

		try {
			// 2. Call API
			const method = customMethodName.trim() || undefined;
			const res = await agentClient.chat(
				agentName,
				{
					query: userText,
					session_id: currentSessionId
				},
				method
			);

			// 3. Process Response
			const assistantMsg: Message = {
				turn_id: res.metadata.turn_id || uuidv4(),
				session_id: currentSessionId,
				role: 'assistant',
				content: res.response, // The markdown response
				data: res.data,
				code: res.code,
				output_mode: res.output_mode,
				metadata: res.metadata,
				tool_calls: res.tool_calls,
				timestamp: Date.now()
			};

			messages = [...messages, assistantMsg];
			await saveMessage(assistantMsg);
		} catch (err: any) {
			console.error('Chat Error', err);
			errorToast = err.message || 'Failed to send message';
			setTimeout(() => (errorToast = null), 3000);

			// Optional: Add error message to chat
			messages = [
				...messages,
				{
					turn_id: uuidv4(),
					session_id: currentSessionId,
					role: 'assistant',
					content: `⚠️ **Error**: ${err.message}`,
					timestamp: Date.now()
				}
			];
		} finally {
			isLoading = false;
			await tick();
			scrollToBottom();
		}
	}

	function scrollToBottom() {
		const el = document.getElementById('chat-scroll-area');
		if (el) el.scrollTop = el.scrollHeight;
	}

	function copyToClipboard(text: string) {
		navigator.clipboard.writeText(text).then(() => {
			// Could show brief toast
		});
	}

	// Markdown Renderer
	function renderMarkdown(text: string) {
		// Replace code blocks with unique IDs to hydrate later?
		// For simplicity, just use marked.
		// Configure marked for highlighting
		return marked.parse(text);
	}

	// Action for GridJS
	function gridAction(node: HTMLElement, data: any[]) {
		if (!data || !Array.isArray(data) || data.length === 0) return;

		const keys = Object.keys(data[0]);

		const grid = new Grid({
			columns: keys,
			data: data.map((row) => keys.map((k) => row[k])),
			search: true,
			sort: true,
			pagination: {
				limit: 5
			},
			className: {
				table: 'table table-xs table-zebra w-full'
			}
		});

		grid.render(node);

		return {
			destroy() {
				// Cleanup
			}
		};
	}

	function formatTime(ts: number) {
		return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}
</script>

<div
	class="bg-base-100 border-base-300 relative flex h-full w-full overflow-hidden rounded-xl border shadow-xl"
>
	<!-- Sidebar -->
	{#if sidebarOpen}
		<div
			class="border-base-300 bg-base-200/50 flex w-64 flex-col border-r transition-all duration-300 ease-in-out"
		>
			<div class="border-base-300 flex items-center justify-between border-b p-4">
				<h2 class="text-lg font-bold">Chats</h2>
				<button class="btn btn-ghost btn-sm btn-square" onclick={() => (sidebarOpen = false)}>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-5 w-5"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						><path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M11 19l-7-7 7-7m8 14l-7-7 7-7"
						/></svg
					>
				</button>
			</div>
			<div class="p-2">
				<button class="btn btn-primary btn-block gap-2" onclick={startNewChat}>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-5 w-5"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						><path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M12 4v16m8-8H4"
						/></svg
					>
					New Chat
				</button>
			</div>
			<div class="flex-1 space-y-1 overflow-y-auto p-2">
				{#each conversations as conv}
					<button
						class="hover:bg-base-300 w-full rounded-lg border border-transparent p-3 text-left text-sm transition-colors"
						class:bg-base-300={currentSessionId === conv.session_id}
						class:border-primary={currentSessionId === conv.session_id}
						onclick={() => selectConversation(conv)}
					>
						<div class="truncate font-medium">{conv.title}</div>
						<div class="text-base-content/60 text-xs">
							{new Date(conv.updated_at).toLocaleDateString()}
						</div>
					</button>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Main Chat Area -->
	<div class="relative flex h-full flex-1 flex-col">
		<!-- Header (if sidebar closed or just toolbar) -->
		{#if !sidebarOpen}
			<div class="absolute left-2 top-2 z-10">
				<button class="btn btn-circle btn-sm bg-base-200" onclick={() => (sidebarOpen = true)}>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-5 w-5"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						><path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M4 6h16M4 12h16M4 18h16"
						/></svg
					>
				</button>
			</div>
		{/if}

		<!-- Scrollable Messages -->
		<div id="chat-scroll-area" class="flex-1 space-y-6 overflow-y-auto p-4">
			{#if messages.length === 0}
				<div class="text-base-content/50 flex h-full flex-col items-center justify-center">
					<div class="bg-primary/10 mb-4 rounded-full p-4">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							class="text-primary h-12 w-12"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
							><path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
							/></svg
						>
					</div>
					<h3 class="text-xl font-bold">Start a conversation</h3>
					<p class="text-sm">Ask anything to {agentName}</p>
				</div>
			{/if}

			{#each messages as msg}
				<div class="chat {msg.role === 'user' ? 'chat-end' : 'chat-start'} group">
					<div class="chat-header mb-1 text-xs opacity-50">
						{msg.role === 'user' ? 'You' : agentName}
						<time class="ml-1">{formatTime(msg.timestamp)}</time>
					</div>
					<div
						class="chat-bubble {msg.role === 'user'
							? 'chat-bubble-primary'
							: 'chat-bubble-secondary !text-base-content !bg-base-200'} max-w-[85%] shadow-md"
					>
						{#if msg.role === 'assistant'}
							<!-- Render Markdown -->
							<div class="prose prose-sm dark:prose-invert max-w-none">
								<!-- eslint-disable-next-line svelte/no-at-html-tags -->
								{@html renderMarkdown(msg.content)}
							</div>

							<!-- Data Table Collapsible -->
							{#if msg.data}
								<div
									class="collapse-arrow border-base-300 bg-base-100 rounded-box collapse mt-4 border"
								>
									<input type="checkbox" />
									<div class="collapse-title flex items-center gap-2 text-sm font-medium">
										<svg
											xmlns="http://www.w3.org/2000/svg"
											class="h-4 w-4"
											viewBox="0 0 24 24"
											fill="none"
											stroke="currentColor"
											stroke-width="2"
											stroke-linecap="round"
											stroke-linejoin="round"
											><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line
												x1="3"
												y1="9"
												x2="21"
												y2="9"
											></line><line x1="3" y1="15" x2="21" y2="15"></line><line
												x1="9"
												y1="3"
												x2="9"
												y2="21"
											></line><line x1="15" y1="3" x2="15" y2="21"></line></svg
										>
										Show Data Table {Array.isArray(msg.data) ? `(${msg.data.length} rows)` : ''}
									</div>
									<div class="collapse-content overflow-x-auto">
										{#if Array.isArray(msg.data)}
											<div use:gridAction={msg.data}></div>
										{:else}
											<pre class="text-xs">{JSON.stringify(msg.data, null, 2)}</pre>
										{/if}
									</div>
								</div>
							{/if}

							<!-- Code Block from 'code' field -->
							{#if msg.code}
								<div
									class="bg-base-300 border-base-content/10 mt-4 overflow-hidden rounded-lg border p-0 text-sm"
								>
									<div
										class="bg-base-content/5 border-base-content/10 flex items-center justify-between border-b px-4 py-1"
									>
										<span class="font-mono text-xs opacity-70">Code</span>
										<button class="btn btn-xs btn-ghost" onclick={() => copyToClipboard(msg.code!)}
											>Copy</button
										>
									</div>
									<pre class="overflow-x-auto p-4"><code>{msg.code}</code></pre>
								</div>
							{/if}

							<!-- Footer Actions -->
							<div
								class="border-base-content/10 mt-4 flex items-center justify-between border-t pt-2"
							>
								<button class="btn btn-xs btn-ghost" onclick={() => copyToClipboard(msg.content)}>
									Copy Response
								</button>

								<!-- Metadata Popover -->
								<div class="dropdown dropdown-top dropdown-end">
									<div
										tabindex="0"
										role="button"
										class="btn btn-xs btn-circle btn-ghost text-info"
										aria-label="Metadata"
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											class="h-4 w-4"
											fill="none"
											viewBox="0 0 24 24"
											stroke="currentColor"
											><path
												stroke-linecap="round"
												stroke-linejoin="round"
												stroke-width="2"
												d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
											/></svg
										>
									</div>
									<div
										tabindex="0"
										class="dropdown-content card card-compact bg-base-300 text-base-content z-[2] w-64 p-2 shadow"
									>
										<div class="card-body">
											<h3 class="card-title text-xs">Response Metadata</h3>
											<div class="max-h-40 space-y-1 overflow-y-auto text-xs">
												<p><strong>Model:</strong> {msg.metadata?.model || 'N/A'}</p>
												<p><strong>Latency:</strong> {msg.metadata?.response_time}s</p>
												<p><strong>Turn ID:</strong> {msg.turn_id}</p>
												{#if msg.tool_calls && msg.tool_calls.length}
													<div class="divider my-1"></div>
													<strong>Tool Calls:</strong>
													{#each msg.tool_calls as tool}
														<div class="bg-base-100 mt-1 rounded p-1">
															<div class="font-mono">{tool.name}</div>
															<div class="truncate opacity-70">
																{JSON.stringify(tool.arguments)}
															</div>
														</div>
													{/each}
												{/if}
											</div>
										</div>
									</div>
								</div>
							</div>
						{:else}
							<!-- User Bubble Content -->
							<div class="whitespace-pre-wrap">{msg.content}</div>
						{/if}
					</div>
				</div>
			{/each}

			{#if isLoading}
				<div class="chat chat-start">
					<div class="chat-bubble chat-bubble-secondary !bg-base-200 animate-pulse">
						<span class="loading loading-dots loading-sm"></span>
					</div>
				</div>
			{/if}
		</div>

		<!-- Input Area -->
		<div class="bg-base-100 border-base-300 border-t p-4">
			<!-- Advanced Options Collapsible -->
			<div class="collapse-arrow bg-base-100 border-base-200 rounded-box collapse mb-2 border">
				<input type="checkbox" bind:checked={showAdvanced} />
				<div class="collapse-title min-h-0 py-2 text-xs font-medium">Advanced Options</div>
				<div class="collapse-content">
					<div class="form-control w-full max-w-xs">
						<label class="label">
							<span class="label-text text-xs">Method Name</span>
						</label>
						<input
							type="text"
							placeholder="e.g. specialized_mode"
							bind:value={customMethodName}
							class="input input-sm input-bordered w-full"
						/>
					</div>
				</div>
			</div>

			<div class="flex items-end gap-2">
				<!-- File Upload -->
				<button class="btn btn-circle btn-ghost" title="Upload File">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-6 w-6"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						><path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M12 4v16m8-8H4"
						/></svg
					>
				</button>

				<!-- Text Area -->
				<div class="relative flex-1">
					<textarea
						class="textarea textarea-bordered w-full resize-none leading-normal"
						placeholder="Send a message..."
						rows="1"
						bind:value={query}
						onkeydown={(e) => {
							if (e.key === 'Enter' && !e.shiftKey) {
								e.preventDefault();
								sendMessage();
							}
						}}
					></textarea>
				</div>

				<!-- Send Button -->
				<button
					class="btn btn-primary btn-circle"
					onclick={sendMessage}
					disabled={isLoading || !query.trim()}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-5 w-5"
						viewBox="0 0 20 20"
						fill="currentColor"
					>
						<path
							d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z"
						/>
					</svg>
				</button>
			</div>
			<div class="text-base-content/30 mt-1 text-center text-xs">
				Supports Markdown • Shift+Enter for new line
			</div>
		</div>
	</div>
</div>

<!-- Simple Toast -->
{#if errorToast}
	<div class="toast toast-end z-50">
		<div class="alert alert-error">
			<span>{errorToast}</span>
		</div>
	</div>
{/if}
