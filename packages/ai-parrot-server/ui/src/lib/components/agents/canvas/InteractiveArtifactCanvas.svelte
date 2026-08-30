<script lang="ts">
	import Icon from '@iconify/svelte';
	import type { InteractiveArtifactTabData } from '$lib/types/agent';

	let { data, agentId = '' }: { data: unknown; agentId?: string } = $props();

	function normalizeData(raw: unknown): InteractiveArtifactTabData | null {
		if (!raw || typeof raw !== 'object') return null;
		const d = raw as Partial<InteractiveArtifactTabData>;
		if (!d.artifact_id || (!d.html_url && !d.html_inline)) return null;
		return {
			artifact_id: d.artifact_id,
			html_inline: d.html_inline ?? null,
			html_url: d.html_url ?? '',
			template_name: d.template_name ?? 'artifact',
			theme: d.theme ?? null,
			libraries_used: Array.isArray(d.libraries_used) ? d.libraries_used : [],
			enhanced: typeof d.enhanced === 'boolean' ? d.enhanced : true,
			session_id: d.session_id,
		};
	}

	let tabData = $derived(normalizeData(data));
	let hasInline = $derived(typeof tabData?.html_inline === 'string' && tabData.html_inline.length > 0);
	let hasUrl = $derived(typeof tabData?.html_url === 'string' && tabData.html_url.length > 0);
	let isEmpty = $derived(!tabData || (!hasInline && !hasUrl));

	let showEnhancedBanner = $state(true);
	let isLoading = $state(true);

	$effect(() => {
		// Reset loading state whenever the displayed artifact changes
		tabData;
		isLoading = true;
	});
</script>

<div class="flex flex-col h-full">
	<!-- enhanced: false banner (conditional, dismissible) -->
	{#if tabData && !tabData.enhanced && showEnhancedBanner}
		<div
			class="flex items-start gap-2 bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-300 text-xs px-3 py-2 shrink-0"
		>
			<Icon icon="mdi:information-outline" class="size-3.5 mt-0.5 shrink-0" />
			<span class="flex-1"
				>This artifact was rendered with a default layout because the AI content failed validation.
				Ask the agent again with more context.</span
			>
			<button
				class="shrink-0 hover:opacity-70"
				onclick={() => (showEnhancedBanner = false)}
				aria-label="Dismiss"
			>
				<Icon icon="mdi:close" class="size-3.5" />
			</button>
		</div>
	{/if}

	<!-- content area -->
	{#if !isEmpty}
		<div class="flex-1 relative min-h-0">
			<!-- loading spinner overlay -->
			{#if isLoading}
				<div
					class="absolute inset-0 flex items-center justify-center bg-background/60 z-10"
				>
					<Icon icon="mdi:loading" class="size-8 animate-spin text-muted-foreground" />
				</div>
			{/if}

			<!--
				iframe: prefer srcdoc (no RTT, no expiry risk).
				sandbox: allow-scripts — enables interactivity (charts, buttons, etc.)
				         allow-forms — enables form submissions within the artifact
				         allow-modals — enables alert()/confirm()/prompt() dialogs
				         allow-popups — enables window.open() calls from artifact code
				         allow-same-origin is intentionally ABSENT — if present, the
				         iframe could access the parent's cookies, localStorage and DOM,
				         which would be a privilege-escalation security hole.
			-->
			{#if hasInline}
				<iframe
					srcdoc={tabData!.html_inline!}
					sandbox="allow-scripts allow-forms allow-modals allow-popups"
					referrerpolicy="no-referrer"
					loading="lazy"
					title="Interactive Artifact"
					class="w-full h-full border-0"
					onload={() => (isLoading = false)}
				></iframe>
			{:else if hasUrl}
				<iframe
					src={tabData!.html_url}
					sandbox="allow-scripts allow-forms allow-modals allow-popups"
					referrerpolicy="no-referrer"
					loading="lazy"
					title="Interactive Artifact"
					class="w-full h-full border-0"
					onload={() => (isLoading = false)}
				></iframe>
			{/if}

			<!-- action bar (floating overlay, top-right) -->
			{#if tabData}
				<div
					class="absolute top-2 right-2 flex items-center gap-1 bg-background/80 backdrop-blur-sm border border-border rounded-md px-1 py-1 shadow-sm"
				>
					<!-- Download: use public signed URL + ?download=1 -->
					<a
						class="btn btn-ghost btn-xs btn-square"
						href="{tabData.html_url}?download=1"
						download="{tabData.template_name}-{tabData.artifact_id}.html"
						title="Download HTML"
					>
						<Icon icon="mdi:download" class="size-4" />
					</a>
					<!-- Open in new tab -->
					<a
						class="btn btn-ghost btn-xs btn-square"
						href={tabData.html_url}
						target="_blank"
						rel="noopener noreferrer"
						title="Open in new tab"
					>
						<Icon icon="mdi:open-in-new" class="size-4" />
					</a>
				</div>
			{/if}
		</div>
	{:else}
		<!-- empty state -->
		<div
			class="flex flex-col items-center justify-center h-full text-center text-muted-foreground/60 p-6 gap-3"
		>
			<Icon icon="mdi:web-off" class="size-12 opacity-30" />
			<p class="text-sm font-medium">No artifact to display</p>
			<p class="text-xs">Ask the agent to generate an interactive artifact.</p>
		</div>
	{/if}
</div>
