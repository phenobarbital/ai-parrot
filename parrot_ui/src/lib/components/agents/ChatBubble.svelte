<script lang="ts">
	import { onMount } from 'svelte';
	import { marked } from 'marked';
	import hljs from 'highlight.js';
	import 'highlight.js/styles/github-dark.css'; // or your preferred theme
	import DOMPurify from 'isomorphic-dompurify';
	import type { AgentMessage } from '$lib/types/agent';
	import DataTable from './DataTable.svelte';
	import ECharts from '$lib/components/visualizations/ECharts.svelte';
	import Vega from '$lib/components/visualizations/Vega.svelte';

	// Props
	let { message, onRepeat, onFollowup, onExplain, onRetry } = $props<{
		message: AgentMessage;
		onRepeat?: (text: string) => void;
		onFollowup?: (turnId: string, data: any) => void;
		onExplain?: (turnId: string, data: any) => void;
		onRetry?: (msgId: string) => void;
	}>();

	let isUser = $derived(message.role === 'user');
	let showData = $state(false);
	
	// Check for error state either via metadata or content convention
	let isError = $derived(message.metadata?.is_error || message.content.startsWith('**Error:**'));
	
	// Check if data is present and not empty
	let hasData = $derived(
		message.data && 
		(Array.isArray(message.data) ? message.data.length > 0 : Object.keys(message.data).length > 0)
	);

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

	let contentRef = $state<HTMLElement>();

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
		<time class="text-xs opacity-50">{new Date(message.timestamp).toLocaleTimeString()}</time>
	</div>

	<div
		class={`chat-bubble group relative ${isUser ? 'w-auto max-w-4xl chat-bubble-primary' : '!w-full max-w-[calc(100%-4rem)] chat-bubble-secondary !bg-[#f9fafb] !text-slate-900'}`}
	>
		<!-- Side Actions (Reply, Explain, Metadata, Copy) -->
		<!-- Rendered outside the bubble content visually but positioned relative to it -->
		{#if !isUser}
			<div
				class="absolute -right-10 top-0 flex h-full flex-col gap-1 py-2 opacity-0 transition-opacity group-hover:opacity-100"
			>
				<!-- Follow-up Reply -->
				{#if onFollowup && message.metadata?.turn_id}
					<button
						class="btn btn-ghost btn-xs btn-square text-success"
						onclick={() => onFollowup(message.metadata?.turn_id || '', message.data)}
						title="Reply to this message"
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

				<!-- Explain -->
				{#if onExplain && message.data}
					<button
						class="btn btn-ghost btn-xs btn-square text-warning"
						onclick={() => onExplain(message.id, message.data)}
						title="Explain results"
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
								d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 5.25h.008v.008H12v-.008Z"
							/>
						</svg>
					</button>
				{/if}

				<!-- Metadata -->
				{#if message.metadata}
					<div class="dropdown dropdown-end dropdown-left">
						<button
							class="btn btn-ghost btn-xs btn-square"
							aria-label="Metadata"
							title="Metadata"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								class="h-4 w-4 stroke-current"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="2"
									d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
								></path>
							</svg>
						</button>
						<div
							tabindex="0"
							class="dropdown-content card card-compact bg-base-100 text-base-content border-base-300 z-[1] mr-2 w-64 border p-2 shadow"
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
				{/if}

				<!-- Copy -->
				<button
					class="btn btn-ghost btn-xs btn-square"
					onclick={() => copyToClipboard(message.content)}
					title="Copy answer"
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
							d="M15.666 3.888A2.25 2.25 0 0 0 13.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 0 1-.75.75H9a.75.75 0 0 1-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 0 1-2.25 2.25H6.75A2.25 2.25 0 0 1 4.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 0 1 1.927-.184"
						/>
					</svg>
				</button>
			</div>
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
		{#if !message.htmlResponse}
			<div bind:this={contentRef} class={`prose prose-sm max-w-none ${isUser ? 'dark:prose-invert' : ''} ${isError ? 'text-error' : ''}`}>
				{@html parsedContent}
			</div>

			<!-- Retry Action for Errors -->
			{#if isError && onRetry}
				<div class="mt-2 flex justify-center w-full border-t border-error/20 pt-2">
					<button 
						class="btn btn-sm btn-ghost gap-2 text-error hover:bg-error/10"
						onclick={() => onRetry && onRetry(message.id)}
						title="Retry request"
					>
						<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-4">
  							<path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
						</svg>
						Retry
					</button>
				</div>
			{/if}
		{/if}

			<!-- Visualization Content (Moved inside bubble) -->
		{#if !isUser}
			<div class="mt-2 flex w-full flex-col gap-2">
			
			<!-- Native ECharts Rendering (Priority if output data exists) -->
			{#if message.output_mode === 'echarts' && message.output}
				<div class="border-base-300 bg-base-100 rounded-box border">
					<div class="border-b border-base-300 bg-base-200 p-2 px-4 flex items-center gap-2 text-sm font-medium">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="size-4 text-purple-500"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M3.75 3v11.25A2.25 2.25 0 0 0 6 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0 1 18 16.5h-2.25m-7.5 0h7.5m-7.5 0-1 3m8.5-3 1 3m0 0 .5 1.5m-.5-1.5h-9.5m0 0-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6"
							/>
						</svg>
						Chart View (ECharts)
					</div>
					<div class="bg-white p-4">
						<ECharts
							options={typeof message.output === 'string'
								? JSON.parse(message.output)
								: message.output}
							style="width: 100%; height: 500px;"
						/>
					</div>
				</div>

			<!-- Native Vega/Altair Rendering (Priority if output data exists) -->
			{:else if message.output_mode === 'altair' && message.output && !message.htmlResponse}
				<div class="border-base-300 bg-base-100 rounded-box border">
					<div class="border-b border-base-300 bg-base-200 p-2 px-4 flex items-center gap-2 text-sm font-medium">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="size-4 text-orange-500"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z"
							/>
						</svg>
						Chart View (Altair)
					</div>
					<div class="bg-white p-4 dark:bg-[#1d232a]">
						<Vega
							spec={typeof message.output === 'string'
								? JSON.parse(message.output)
								: message.output}
							style="width: 100%; min-height: 400px;"
						/>
					</div>
				</div>

			<!-- HTML Response Iframe (Fallback for all modes) -->
			{:else if message.htmlResponse}
				<div class="border-base-300 bg-base-100 rounded-box border">
					<div class="border-b border-base-300 bg-base-200 p-2 px-4 flex items-center gap-2 text-sm font-medium">
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
					<div class="p-0">
						<iframe
							class="w-full rounded-lg"
							style="min-height: 500px; background: #ffffff; border: 1px solid #ccc;"
							srcdoc={message.htmlResponse}
							sandbox="allow-scripts allow-forms allow-popups allow-same-origin"
							title="Response visualization"
						></iframe>
					</div>
				</div>
			{/if}

			<!-- Data Display -->
			{#if hasData}
				<div class="mt-2">
					<button
						class="btn btn-sm rounded-full border-none bg-blue-50 text-blue-600 hover:bg-blue-100 flex items-center gap-2 h-9 px-4 normal-case font-medium"
						onclick={() => (showData = !showData)}
					>
						{#if Array.isArray(message.data) && message.data.length > 0 && message.output_mode !== 'json'}
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-4">
								<path
									fill-rule="evenodd"
									d="M1 4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V4Zm1 3.25V9h12V7.25H2Zm0 3.25V12h12v-1.5H2Z"
									clip-rule="evenodd"
								/>
							</svg>
							Show data
							<span
								class="badge badge-sm border-none bg-white text-blue-600 min-w-[20px] h-5 flex items-center justify-center p-0"
								>{message.data.length}</span
							>
						{:else}
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-4">
								<path
									fill-rule="evenodd"
									d="M3 3.5A1.5 1.5 0 0 1 4.5 2h6.879a1.5 1.5 0 0 1 1.06.44l4.122 4.12A1.5 1.5 0 0 1 17 7.622V16.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 16.5v-13Zm10.857 5.691a.75.75 0 0 0-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 1 0-1.06 1.061l2.5 2.5a.75.75 0 0 0 1.137-.089l4-5.5Z"
									clip-rule="evenodd"
								/>
							</svg>
							Show JSON data
							<span
								class="badge badge-sm border-none bg-white text-blue-600 min-w-[20px] h-5 flex items-center justify-center p-0"
								>{Array.isArray(message.data)
									? message.data.length
									: Object.keys(message.data).length}</span
							>
						{/if}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class={`size-3 ml-1 transition-transform ${showData ? 'rotate-180' : ''}`}
						>
							<path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
						</svg>
					</button>

					{#if showData}
						<div class="mt-3 animate-in fade-in slide-in-from-top-2 duration-200">
							{#if Array.isArray(message.data) && message.data.length > 0 && message.output_mode !== 'json'}
								<DataTable data={message.data} />
							{:else}
								<pre
									class="bg-[#1f2937] text-gray-100 rounded-lg p-4 text-sm overflow-auto max-h-96"><code
										class="language-json">{JSON.stringify(message.data, null, 2)}</code
									></pre>
							{/if}
						</div>
					{/if}
				</div>
			{/if}
			</div>
		{/if}
	</div>


</div>

<style>
	/* Markdown table styling - Light Theme */
	:global(.prose table) {
		width: 100% !important;
		border-collapse: collapse !important;
		margin: 1rem 0 !important;
		font-size: 0.875rem !important;
		border: 1px solid #e5e7eb !important; /* gray-200 */
		border-radius: 0.5rem !important;
		overflow: hidden !important;
		background-color: #ffffff !important;
		box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05) !important;
	}

	:global(.prose thead) {
		background-color: #f3f4f6 !important; /* gray-100 */
	}

	:global(.prose th) {
		background-color: #f3f4f6 !important; /* gray-100 */
		color: #111827 !important; /* gray-900 */
		padding: 0.75rem 1rem !important;
		text-align: left !important;
		font-weight: 600 !important;
		border-bottom: 2px solid #e5e7eb !important; /* gray-200 */
		border-right: 1px solid #e5e7eb !important;
	}

	:global(.prose th:last-child) {
		border-right: none !important;
	}

	:global(.prose td) {
		padding: 0.75rem 1rem !important;
		border-bottom: 1px solid #e5e7eb !important; /* gray-200 */
		border-right: 1px solid #e5e7eb !important;
		color: #374151 !important; /* gray-700 */
	}

	:global(.prose td:last-child) {
		border-right: none !important;
	}

	:global(.prose tbody tr:nth-child(odd)) {
		background-color: #ffffff !important;
	}

	:global(.prose tbody tr:nth-child(even)) {
		background-color: #f9fafb !important; /* gray-50 */
	}

	:global(.prose tbody tr:hover) {
		background-color: #f3f4f6 !important; /* gray-100 */
	}

	:global(.prose tbody tr:last-child td) {
		border-bottom: none !important;
	}

	/* Code block styling - Keep dark for contrast or switch to light if preferred. Keeping dark for now as it's standard for code. */
	:global(.prose pre) {
		background-color: #1f2937 !important; /* gray-800 */
		border: 1px solid #374151 !important; /* gray-700 */
		border-radius: 0.5rem !important;
		padding: 1rem !important;
		overflow-x: auto !important;
	}

	:global(.prose code) {
		background-color: #f3f4f6 !important; /* gray-100 */
		color: #ef4444 !important; /* red-500 or similar for inline code */
		padding: 0.125rem 0.375rem !important;
		border-radius: 0.25rem !important;
		font-size: 0.875em !important;
		font-weight: 500 !important;
	}

	:global(.prose pre code) {
		background: none !important;
		color: inherit !important;
		padding: 0 !important;
	}

	/* Force assistant bubbles to be full width in the grid */
	:global(.chat-start) {
		grid-template-columns: auto 1fr !important;
	}
	:global(.chat-start .chat-bubble) {
		width: 100% !important;
		max-width: 100% !important; /* Let the inline style handle the subtraction */
	}
</style>
