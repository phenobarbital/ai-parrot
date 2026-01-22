<script lang="ts">
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import '$lib/dashboards/styles.css';

	$: id = $page.params.id;

	let loading = true;
	let hasWidget = false;
	let widgetData: any = null;
	let containerEl: HTMLElement;

	onMount(async () => {
		try {
			// Check for saved widget configuration in localStorage
			const widgetKey = `widget-config-${id}`;
			const savedData = localStorage.getItem(widgetKey);

			if (savedData) {
				hasWidget = true;
				widgetData = JSON.parse(savedData);

				// Dynamically import and create the widget based on saved type
				const widgetType = widgetData.type || 'html';
				let widget;

				if (widgetType === 'iframe') {
					const { IFrameWidget } = await import('$lib/dashboards/iframe-widget.js');
					widget = new IFrameWidget(widgetData);
				} else if (widgetType === 'image') {
					const { ImageWidget } = await import('$lib/dashboards/image-widget.js');
					widget = new ImageWidget(widgetData);
				} else if (widgetType === 'youtube') {
					const { YouTubeWidget } = await import('$lib/dashboards/youtube-widget.js');
					widget = new YouTubeWidget(widgetData);
				} else if (widgetType === 'markdown') {
					const { MarkdownWidget } = await import('$lib/dashboards/markdown-widget.js');
					widget = new MarkdownWidget(widgetData);
				} else {
					const { HTMLWidget } = await import('$lib/dashboards/html-widget.js');
					widget = new HTMLWidget({
						title: widgetData.title || `Shared Widget: ${id}`,
						...widgetData
					});
				}

				if (widget && containerEl) {
					widget.el.style.position = 'relative';
					widget.el.style.width = '100%';
					widget.el.style.height = '100%';
					widget.el.style.minHeight = '400px';
					containerEl.appendChild(widget.el);
				}
			}
		} catch (e) {
			console.error('Failed to load shared widget:', e);
		} finally {
			loading = false;
		}
	});
</script>

<div class="share-page h-full w-full" bind:this={containerEl}>
	{#if loading}
		<div class="share-loading">
			<div class="spinner"></div>
			<p>Loading widget...</p>
		</div>
	{:else if !hasWidget}
		<div class="share-info-card">
			<div class="share-info-icon">🧩</div>
			<h1>Shared Widget</h1>
			<p class="share-id">ID: <code>{id}</code></p>
			<div class="share-message">
				<p>This widget has not been saved for sharing yet.</p>
				<p>To share a widget:</p>
				<ol>
					<li>Create a widget in a dashboard</li>
					<li>Open the widget settings (gear icon)</li>
					<li>Go to the Share tab and copy the URL</li>
					<li>Share this URL with others</li>
				</ol>
			</div>
			<a href="/programs" class="share-back-btn">← Go to Programs</a>
		</div>
	{/if}
</div>

<style>
	.share-page {
		min-height: 100vh;
		background: var(--db-bg, #1a1a2e);
		color: var(--db-text, #fff);
		padding: 20px;
	}

	.share-loading {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100vh;
		gap: 16px;
	}

	.spinner {
		width: 40px;
		height: 40px;
		border: 3px solid var(--db-border, rgba(255, 255, 255, 0.2));
		border-top-color: var(--db-accent, #3b82f6);
		border-radius: 50%;
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.share-info-card {
		max-width: 500px;
		margin: 80px auto;
		padding: 40px;
		background: var(--db-surface, #252542);
		border-radius: 16px;
		text-align: center;
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
	}

	.share-info-icon {
		font-size: 64px;
		margin-bottom: 16px;
	}

	.share-info-card h1 {
		margin: 0 0 8px;
		font-size: 24px;
		font-weight: 600;
	}

	.share-id {
		margin: 0 0 24px;
		color: var(--db-text-2, rgba(255, 255, 255, 0.7));
	}

	.share-id code {
		background: var(--db-surface-2, #1a1a2e);
		padding: 4px 8px;
		border-radius: 4px;
		font-family: monospace;
	}

	.share-message {
		text-align: left;
		margin-bottom: 24px;
		color: var(--db-text-2, rgba(255, 255, 255, 0.8));
	}

	.share-message ol {
		margin: 16px 0 0;
		padding-left: 20px;
	}

	.share-message li {
		margin: 8px 0;
	}

	.share-back-btn {
		display: inline-block;
		padding: 12px 24px;
		background: var(--db-accent, #3b82f6);
		color: #fff;
		text-decoration: none;
		border-radius: 8px;
		font-weight: 600;
		transition: background 0.2s;
	}

	.share-back-btn:hover {
		background: var(--db-accent-hover, #2563eb);
	}

	/* Widget styling when loaded */
	:global(.widget) {
		background: var(--db-surface, #252542);
		border: 1px solid var(--db-border, rgba(255, 255, 255, 0.1));
		border-radius: 12px;
		overflow: hidden;
	}
</style>
