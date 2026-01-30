<script lang="ts">
	let {
		onSend,
		isLoading,
		text = $bindable(''),
		followupTurnId = null,
		onClearFollowup,
		recentQuestions = []
	} = $props<{
		onSend: (text: string, methodName?: string, outputMode?: string) => void;
		isLoading: boolean;
		text?: string;
		followupTurnId?: string | null;
		onClearFollowup?: () => void;
		recentQuestions?: string[];
	}>();

	let outputMode = $state('default');
	let showHistory = $state(false);
	let textarea: HTMLTextAreaElement;

	const outputModes = [
		{ value: 'default', label: 'Default (Auto)' },
		{ value: 'table', label: 'Table' },
		{ value: 'plotly', label: 'Plotly Chart' },
		{ value: 'matplotlib', label: 'Matplotlib Chart' },
		{ value: 'bokeh', label: 'Bokeh Chart' },
		{ value: 'seaborn', label: 'Seaborn Chart' },
		{ value: 'holoviews', label: 'HoloViews' },
		{ value: 'echarts', label: 'ECharts' },
		{ value: 'altair', label: 'Altair' },
		{ value: 'map', label: 'Map Visualization' }
	];

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			handleSubmit();
		}
	}

	function handleSubmit() {
		if (!text.trim() || isLoading) return;
		onSend(text, undefined, outputMode !== 'default' ? outputMode : undefined);
		text = '';
		outputMode = 'default';
		if (textarea) {
			textarea.style.height = 'auto';
		}
	}

	function autoResize() {
		if (textarea) {
			textarea.style.height = 'auto';
			textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
		}
	}

	function selectQuestion(question: string) {
		text = question;
		showHistory = false;
		autoResize();
	}
</script>

<div class="border-base-300 bg-base-100 border-t px-3 py-2">
	<!-- Follow-up Indicator -->
	{#if followupTurnId}
		<div
			class="bg-success/10 border-success text-success mb-2 flex items-center justify-between rounded-lg border px-2 py-1.5"
		>
			<div class="flex items-center gap-2">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="1.5"
					stroke="currentColor"
					class="h-3.5 w-3.5"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M9 15 3 9m0 0 6-6M3 9h12a6 6 0 0 1 0 12h-3"
					/>
				</svg>
				<span class="text-xs font-medium">Replying to previous response</span>
				<span class="badge badge-success badge-xs">{followupTurnId.slice(0, 8)}...</span>
			</div>
			<button
				class="btn btn-ghost btn-xs h-5 min-h-0 w-5 p-0"
				onclick={() => onClearFollowup && onClearFollowup()}
				title="Cancel follow-up"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="1.5"
					stroke="currentColor"
					class="h-3.5 w-3.5"
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
				</svg>
			</button>
		</div>
	{/if}

	<!-- Main Input Area - Card Style -->
	<div class="bg-base-200 border-base-300 rounded-2xl border p-2">
		<!-- Textarea -->
		<textarea
			bind:this={textarea}
			bind:value={text}
			oninput={autoResize}
			onkeydown={handleKeydown}
			placeholder="Ask a question..."
			class="textarea placeholder-base-content/50 w-full resize-none border-0 bg-transparent p-0 text-base focus:outline-none"
			style="min-height: 60px; max-height: 200px;"
			disabled={isLoading}
		></textarea>

		<!-- Bottom Bar: Actions -->
		<div class="mt-1 flex items-center justify-between">
			<!-- Left Side: History Button -->
			<div class="flex items-center gap-2">
				<!-- Question History Dropdown -->
				<div class="dropdown dropdown-top">
					<button
						class="btn btn-ghost btn-sm btn-circle"
						title="Question history"
						onclick={() => (showHistory = !showHistory)}
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="h-5 w-5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
							/>
						</svg>
					</button>

					{#if showHistory && recentQuestions.length > 0}
						<div
							class="dropdown-content bg-base-100 rounded-box border-base-300 z-[50] mb-2 w-80 border p-0 shadow-xl"
						>
							<div
								class="bg-primary text-primary-content rounded-t-box flex items-center justify-between px-4 py-3"
							>
								<div class="flex items-center gap-2">
									<svg
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
										stroke-width="1.5"
										stroke="currentColor"
										class="h-5 w-5"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
										/>
									</svg>
									<div>
										<div class="font-semibold">Question History</div>
										<div class="text-xs opacity-70">{recentQuestions.length} questions</div>
									</div>
								</div>
								<button class="text-xs hover:underline" onclick={() => (showHistory = false)}
									>Close</button
								>
							</div>
							<ul class="max-h-80 overflow-y-auto py-2">
								{#each recentQuestions.slice(0, 10) as question, i}
									<li>
										<button
											class="hover:bg-base-200 flex w-full items-start gap-3 px-4 py-3 text-left transition-colors"
											onclick={() => selectQuestion(question)}
										>
											<div class="flex-1">
												<p class="line-clamp-2 text-sm">{question}</p>
											</div>
											<span class="badge badge-ghost badge-sm">Default</span>
										</button>
									</li>
								{/each}
							</ul>
						</div>
					{:else if showHistory}
						<div
							class="dropdown-content bg-base-100 rounded-box border-base-300 z-[50] mb-2 w-60 border p-4 shadow-xl"
						>
							<p class="text-sm opacity-50">No recent questions</p>
						</div>
					{/if}
				</div>
			</div>

			<!-- Right Side: Output Mode + Send -->
			<div class="flex items-center gap-2">
				<!-- Output Mode Selector -->
				<select
					class="select select-bordered max-w-xs"
					bind:value={outputMode}
					title="Response format"
				>
					{#each outputModes as mode}
						<option value={mode.value}>{mode.label}</option>
					{/each}
				</select>

				<!-- Send Button -->
				<button
					class="btn btn-primary btn-sm"
					onclick={handleSubmit}
					disabled={isLoading || !text.trim()}
				>
					{#if isLoading}
						<span class="loading loading-spinner loading-xs"></span>
					{:else}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 24 24"
							fill="currentColor"
							class="h-4 w-4"
						>
							<path
								d="M3.478 2.404a.75.75 0 00-.926.941l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.404z"
							/>
						</svg>
					{/if}
				</button>
			</div>
		</div>
	</div>
</div>
