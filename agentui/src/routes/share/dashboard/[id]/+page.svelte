<script lang="ts">
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import '$lib/dashboards/styles.css';

	$: id = $page.params.id;

	let loading = true;
	let hasDashboard = false;
	let dashboardData: any = null;
	let containerEl: HTMLElement;

	onMount(async () => {
		try {
			// Check for saved dashboard config in localStorage
			const configKey = `dashboard-config-${id}`;
			const configData = localStorage.getItem(configKey);

			// Also check for saved layout
			const gridKey = `grid-layout-${id}`;
			const freeKey = `free-layout-${id}`;
			const dockKey = `dock-layout-${id}`;

			const gridData = localStorage.getItem(gridKey);
			const freeData = localStorage.getItem(freeKey);
			const dockData = localStorage.getItem(dockKey);

			if (configData || gridData || freeData || dockData) {
				hasDashboard = true;

				// Parse config if available
				const config = configData ? JSON.parse(configData) : {};
				dashboardData = {
					title: config.title || `Shared Dashboard: ${id}`,
					icon: config.icon || '📊',
					layoutMode: config.layoutMode || (gridData ? 'grid' : freeData ? 'free' : 'dock')
				};

				// Dynamically import and create the dashboard
				const { DashboardView } = await import('$lib/dashboards/dashboard');
				const dashboard = new DashboardView(id, dashboardData.title, dashboardData.icon, {
					layoutMode: dashboardData.layoutMode
				});

				// Load saved layout
				dashboard.loadLayout();

				// Append to container
				if (containerEl) {
					containerEl.appendChild(dashboard.el);
				}
			}
		} catch (e) {
			console.error('Failed to load shared dashboard:', e);
		} finally {
			loading = false;
		}
	});
</script>

<div class="share-page h-full w-full" bind:this={containerEl}>
	{#if loading}
		<div class="share-loading">
			<div class="spinner"></div>
			<p>Loading dashboard...</p>
		</div>
	{:else if !hasDashboard}
		<div class="share-info-card">
			<div class="share-info-icon">📊</div>
			<h1>Shared Dashboard</h1>
			<p class="share-id">ID: <code>{id}</code></p>
			<div class="share-message">
				<p>This dashboard has not been created yet or no layout has been saved.</p>
				<p>To share a dashboard:</p>
				<ol>
					<li>Create a dashboard in the application</li>
					<li>Add widgets and configure the layout</li>
					<li>Save the layout from Dashboard Settings</li>
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

	/* Dashboard view styling when loaded */
	:global(.dashboard-view) {
		height: 100% !important;
		display: flex;
		flex-direction: column;
		min-height: 100vh;
	}

	:global(.dashboard-main) {
		flex: 1;
		overflow: hidden;
		position: relative;
	}
</style>
