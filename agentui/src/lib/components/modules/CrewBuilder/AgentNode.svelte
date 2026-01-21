<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';

	let { data, selected = false } = $props();

	const truncate = (value = '', max = 60) => {
		if (!value) return '';
		return value.length > max ? `${value.slice(0, max - 1)}…` : value;
	};

	let agentName = $derived(data.name || 'Unnamed Agent');
	let agentId = $derived(data.agent_id || 'unknown');
	let model = $derived(data.config?.model || 'Not configured');
	let hasTools = $derived(data.tools && data.tools.length > 0);
	let promptPreview = $derived(truncate(data.system_prompt || '', 80));
	const getTemperatureLabel = (raw: any) => {
		if (typeof raw === 'number' && !Number.isNaN(raw)) return raw.toFixed(1);
		if (typeof raw === 'string' && raw.trim().length > 0) return raw;
		return '—';
	};
	let temperatureLabel = $derived.by(() => getTemperatureLabel(data.config?.temperature));
</script>

<div class={`cb-node-card ${selected ? 'active' : ''}`}>
	<div class="cb-node-header">
		<div class="cb-node-icon">🤖</div>
		<div>
			<p class="cb-node-title">{agentName}</p>
			<p class="cb-node-subtitle">{agentId}</p>
		</div>
	</div>

	<div class="cb-node-summary">
		<div class="cb-node-summary-row">
			<p class="cb-node-label">Model</p>
			<p class="cb-node-value">{model}</p>
		</div>
		{#if hasTools}
			<div class="cb-node-summary-row">
				<p class="cb-node-label">Tools</p>
				<p class="cb-node-value">{data.tools.length} tool(s)</p>
			</div>
		{/if}
		<div class="cb-node-summary-row">
			<p class="cb-node-label">Temperature</p>
			<p class="cb-node-value">{temperatureLabel}</p>
		</div>
	</div>

	{#if promptPreview}
		<div class="cb-node-meta">
			<span>{promptPreview}</span>
		</div>
	{/if}
</div>

<Handle class="cb-node-handle" type="target" position={Position.Left} />
<Handle class="cb-node-handle" type="source" position={Position.Right} />

<style>
	.cb-node-card {
		--cb-node-bg: #ffffff;
		--cb-node-border: rgba(15, 23, 42, 0.08);
		--cb-node-active-border: rgba(59, 130, 246, 0.8);
		--cb-node-active-shadow: rgba(59, 130, 246, 0.22);
		--cb-node-text: #0f172a;
		--cb-node-muted: #64748b;
		--cb-node-summary-bg: #f8fafc;
		--cb-node-summary-border: rgba(15, 23, 42, 0.05);
		--cb-node-pill-bg: rgba(59, 130, 246, 0.08);
		--cb-node-pill-text: #1d4ed8;
		width: 260px;
		border-radius: 18px;
		border: 1px solid var(--cb-node-border);
		background: var(--cb-node-bg);
		box-shadow: 0 8px 26px rgba(15, 23, 42, 0.1);
		padding: 18px 20px;
		font-family: 'Inter', system-ui;
		transition:
			border-color 0.2s ease,
			box-shadow 0.2s ease,
			transform 0.2s ease;
		color: var(--cb-node-text);
	}

	.cb-node-card.active {
		border-color: var(--cb-node-active-border);
		box-shadow: 0 12px 32px var(--cb-node-active-shadow);
		transform: translateY(-2px);
	}

	.cb-node-header {
		display: flex;
		gap: 10px;
		align-items: center;
		margin-bottom: 12px;
	}

	.cb-node-icon {
		width: 40px;
		height: 40px;
		display: grid;
		place-items: center;
		border-radius: 12px;
		background: linear-gradient(135deg, rgba(59, 130, 246, 0.12), rgba(167, 139, 250, 0.15));
		font-size: 22px;
	}

	.cb-node-title {
		margin: 0;
		font-size: 15px;
		font-weight: 700;
	}

	.cb-node-subtitle {
		margin: 2px 0 0;
		font-size: 12px;
		color: var(--cb-node-muted);
		font-family: 'JetBrains Mono', monospace;
		letter-spacing: 0.01em;
	}

	.cb-node-summary {
		background: var(--cb-node-summary-bg);
		border: 1px solid var(--cb-node-summary-border);
		border-radius: 14px;
		padding: 12px 14px;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.cb-node-summary-row {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.cb-node-label {
		margin: 0;
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--cb-node-muted);
	}

	.cb-node-value {
		margin: 0;
		font-size: 14px;
		font-weight: 600;
		color: var(--cb-node-text);
		word-break: break-word;
	}

	.cb-node-meta {
		margin-top: 10px;
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.cb-node-meta span {
		font-size: 11px;
		background: var(--cb-node-pill-bg);
		color: var(--cb-node-pill-text);
		border-radius: 9999px;
		padding: 2px 10px;
	}

	.cb-node-handle {
		width: 12px;
		height: 12px;
		border-radius: 9999px;
		background: #fff;
		border: 2px solid rgba(59, 130, 246, 0.85);
		box-shadow: 0 4px 10px rgba(15, 23, 42, 0.25);
	}

	:global(html.dark) .cb-node-card {
		--cb-node-bg: rgba(15, 23, 42, 0.92);
		--cb-node-border: rgba(148, 163, 184, 0.25);
		--cb-node-active-border: rgba(59, 130, 246, 0.85);
		--cb-node-active-shadow: rgba(59, 130, 246, 0.3);
		--cb-node-text: #e2e8f0;
		--cb-node-muted: #94a3b8;
		--cb-node-summary-bg: rgba(15, 23, 42, 0.65);
		--cb-node-summary-border: rgba(148, 163, 184, 0.35);
		--cb-node-pill-bg: rgba(14, 165, 233, 0.18);
		--cb-node-pill-text: #bae6fd;
	}
</style>
