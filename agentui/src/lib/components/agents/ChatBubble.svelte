<script lang="ts">
	import { onMount } from 'svelte';
	import { marked } from 'marked';
	import hljs from 'highlight.js';
	import 'highlight.js/styles/github-dark.css'; // or your preferred theme
	import DOMPurify from 'isomorphic-dompurify';
	import type { AgentMessage } from '$lib/types/agent';
	import DataTable from './DataTable.svelte';

	let { message, onRepeat, onFollowup } = $props<{
		message: AgentMessage;
		onRepeat?: (text: string) => void;
		onFollowup?: (turnId: string, data: any) => void;
	}>();

	let isUser = $derived(message.role === 'user');
	let showData = $state(false);

	// Markdown parsing
	let parsedContent = $derived.by(() => {
		const raw = marked.parse(message.content || '');
		return DOMPurify.sanitize(raw as string);
	});

	// Copy to clipboard function
	const copyToClipboard = async (text: string) => {
		try {
			await navigator.clipboard.writeText(text);
			// Ideally show a toast here
			// alert('Copied to clipboard');
		} catch (err) {
			console.error('Failed to copy!', err);
		}
	};

	// Setup highlight.js and copy buttons after render
	// In Svelte 5, we can use an action or an effect.
	// For simplicity processing DOM in $effect

	let contentRef: HTMLElement;

	$effect(() => {
		if (contentRef) {
			// Highlight code blocks
			contentRef.querySelectorAll('pre code').forEach((el) => {
				hljs.highlightElement(el as HTMLElement);
			});

			// Add copy buttons to code blocks
			contentRef.querySelectorAll('pre').forEach((pre) => {
				if (pre.querySelector('.copy-btn')) return; // already added

				const button = document.createElement('button');
				button.className =
					'copy-btn absolute top-2 right-2 btn btn-xs btn-square btn-ghost opacity-50 hover:opacity-100';
				button.innerHTML =
					'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
				button.title = 'Copy Code';

				button.addEventListener('click', () => {
					const code = pre.querySelector('code')?.innerText || '';
					copyToClipboard(code);
					// ephemeral success state
					button.classList.add('text-success');
					setTimeout(() => button.classList.remove('text-success'), 1000);
				});

				pre.style.position = 'relative';
				pre.appendChild(button);
			});
		}
	});
</script>

<div class={`chat ${isUser ? 'chat-end' : 'chat-start'}`}>
	<div class="chat-header mb-1 text-xs opacity-50">
		{isUser ? 'You' : message.metadata?.provider ? `${message.metadata.model}` : 'Agent'}
		<time class="ml-1 text-xs opacity-50">{new Date(message.timestamp).toLocaleTimeString()}</time>
	</div>

	<div
		class={`chat-bubble w-full max-w-4xl ${isUser ? 'chat-bubble-primary' : 'chat-bubble-secondary !bg-base-200 !text-base-content'}`}
	>
		<!-- Metadata Info Icon -->
		{#if !isUser && message.metadata}
			<div class="dropdown dropdown-end absolute -right-8 top-0">
				<div tabindex="0" role="button" class="btn btn-circle btn-ghost btn-xs text-info">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						class="h-4 w-4 stroke-current"
						><path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
						></path></svg
					>
				</div>
				<div
					tabindex="0"
					class="dropdown-content card card-compact bg-base-100 text-base-content border-base-300 z-[1] w-64 border p-2 shadow"
				>
					<div class="card-body">
						<h3 class="card-title text-sm">Metadata</h3>
						<div class="text-xs">
							<p><strong>Session:</strong> {message.metadata.session_id.slice(0, 8)}...</p>
							<p><strong>Turn:</strong> {message.metadata.turn_id?.slice(0, 8)}...</p>
							<p><strong>Model:</strong> {message.metadata.model}</p>
							<p>
								<strong>Latency:</strong>
								{message.metadata.response_time ? `${message.metadata.response_time}ms` : 'N/A'}
							</p>
						</div>
					</div>
				</div>
			</div>

			<!-- Follow-up Reply Button -->
			{#if onFollowup && message.metadata?.turn_id}
				<button
					class="btn btn-circle btn-ghost btn-xs text-success absolute -right-8 top-6"
					onclick={() => onFollowup(message.metadata?.turn_id || '', message.data)}
					title="Reply to this message (follow-up question)"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="1.5"
						stroke="currentColor"
						class="h-4 w-4"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M9 15 3 9m0 0 6-6M3 9h12a6 6 0 0 1 0 12h-3"
						/>
					</svg>
				</button>
			{/if}
		{/if}

		<!-- Repeat Question Button for User Messages -->
		{#if isUser && onRepeat}
			<button
				class="btn btn-ghost btn-xs btn-square absolute -left-8 top-0 opacity-50 hover:opacity-100"
				onclick={() => onRepeat(message.content)}
				title="Repeat this question"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="1.5"
					stroke="currentColor"
					class="h-4 w-4"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99"
					/>
				</svg>
			</button>
		{/if}

		<!-- Message Content -->
		<div bind:this={contentRef} class="prose prose-sm dark:prose-invert max-w-none">
			{@html parsedContent}
		</div>
	</div>

	<!-- HTML Response Iframe - for output_mode responses with full HTML -->
	{#if !isUser && message.htmlResponse}
		<div class="chat-footer mt-2 w-full max-w-4xl">
			<div class="collapse-arrow border-base-300 bg-base-100 rounded-box collapse border">
				<input type="checkbox" checked />
				<div class="collapse-title flex items-center gap-2 text-sm font-medium">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="1.5"
						stroke="currentColor"
						class="text-secondary h-4 w-4"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M17.25 6.75 22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3-4.5 16.5"
						/>
					</svg>
					Interactive View ({message.output_mode || 'html'})
				</div>
				<div class="collapse-content p-0">
					<iframe
						class="w-full rounded-lg border-0"
						style="min-height: 500px; background: #1d232a;"
						srcdoc={message.htmlResponse}
						sandbox="allow-scripts allow-same-origin"
						title="Response visualization"
					></iframe>
				</div>
			</div>
		</div>
	{/if}

	<!-- Data Display - Array shows AG Grid, Dict shows JSON viewer -->
	{#if !isUser && message.data}
		{#if Array.isArray(message.data) && message.data.length > 0}
			<!-- Array Data: Show as AG Grid table -->
			<div class="chat-footer mt-2 w-full max-w-4xl">
				<div class="collapse-arrow border-base-300 bg-base-100 rounded-box collapse border">
					<input type="checkbox" bind:checked={showData} />
					<div class="collapse-title flex items-center gap-2 text-sm font-medium">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="text-primary h-4 w-4"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 0 1-1.125-1.125M3.375 19.5h7.5c.621 0 1.125-.504 1.125-1.125m-9.75 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-7.5A1.125 1.125 0 0 1 12 18.375m9.75-12.75c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125m19.5 0v1.5c0 .621-.504 1.125-1.125 1.125M2.25 5.625v1.5c0 .621.504 1.125 1.125 1.125m0 0h17.25m-17.25 0h7.5c.621 0 1.125.504 1.125 1.125M3.375 8.25v1.5c0 .621.504 1.125 1.125 1.125m17.25-2.625h-7.5c-.621 0-1.125.504-1.125 1.125m-8.25-2.625H12m0 0V8.25m0-2.625V5.625"
							/>
						</svg>
						Show data table ({message.data.length} rows)
					</div>
					<div class="collapse-content p-0">
						{#if showData}
							<div class="p-2">
								<DataTable data={message.data} />
							</div>
						{/if}
					</div>
				</div>
			</div>
		{:else if typeof message.data === 'object' && message.data !== null && !Array.isArray(message.data)}
			<!-- Object/Dict Data: Show as syntax-highlighted JSON -->
			<div class="chat-footer mt-2 w-full max-w-4xl">
				<div class="collapse-arrow border-base-300 bg-base-100 rounded-box collapse border">
					<input type="checkbox" bind:checked={showData} />
					<div class="collapse-title flex items-center gap-2 text-sm font-medium">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="text-warning h-4 w-4"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M17.25 6.75 22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3-4.5 16.5"
							/>
						</svg>
						Show JSON data ({Object.keys(message.data).length} keys)
					</div>
					<div class="collapse-content p-0">
						{#if showData}
							<div class="p-2">
								<pre
									class="bg-base-200 text-base-content max-h-96 overflow-auto rounded-lg p-4 text-sm"><code
										class="language-json">{JSON.stringify(message.data, null, 2)}</code
									></pre>
							</div>
						{/if}
					</div>
				</div>
			</div>
		{/if}
	{/if}

	{#if !isUser}
		<div class="chat-footer mt-1 text-xs opacity-50">
			<button class="btn btn-ghost btn-xs" onclick={() => copyToClipboard(message.content)}>
				Copy answer
			</button>
		</div>
	{/if}
</div>

<style>
	/* Markdown table styling - Using hardcoded dark theme colors */
	:global(.prose table) {
		width: 100% !important;
		border-collapse: collapse !important;
		margin: 1rem 0 !important;
		font-size: 0.875rem !important;
		border: 1px solid #3d4451 !important;
		border-radius: 0.5rem !important;
		overflow: hidden !important;
	}

	:global(.prose thead) {
		background-color: #242933 !important;
	}

	:global(.prose th) {
		background-color: #242933 !important;
		color: #7582ff !important;
		padding: 0.75rem 1rem !important;
		text-align: left !important;
		font-weight: 700 !important;
		border-bottom: 2px solid rgba(117, 130, 255, 0.3) !important;
		border-right: 1px solid #3d4451 !important;
	}

	:global(.prose th:last-child) {
		border-right: none !important;
	}

	:global(.prose td) {
		padding: 0.625rem 1rem !important;
		border-bottom: 1px solid #3d4451 !important;
		border-right: 1px solid #3d4451 !important;
		color: #a6adba !important;
	}

	:global(.prose td:last-child) {
		border-right: none !important;
	}

	:global(.prose tbody tr:nth-child(odd)) {
		background-color: #1d232a !important;
	}

	:global(.prose tbody tr:nth-child(even)) {
		background-color: #242933 !important;
	}

	:global(.prose tbody tr:hover) {
		background-color: #2a303c !important;
	}

	:global(.prose tbody tr:last-child td) {
		border-bottom: none !important;
	}

	/* Code block styling */
	:global(.prose pre) {
		background-color: #242933 !important;
		border: 1px solid #3d4451 !important;
		border-radius: 0.5rem !important;
		padding: 1rem !important;
		overflow-x: auto !important;
	}

	:global(.prose code) {
		background-color: #242933 !important;
		padding: 0.125rem 0.375rem !important;
		border-radius: 0.25rem !important;
		font-size: 0.875em !important;
	}

	:global(.prose pre code) {
		background: none !important;
		padding: 0 !important;
	}
</style>
