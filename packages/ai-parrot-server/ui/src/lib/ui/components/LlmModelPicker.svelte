<script lang="ts">
	import { listLlmClients, listLlmModels } from '$lib/api/llm';

	interface Props {
		provider: string;
		model: string;
		onchange: (value: { provider: string; model: string }) => void;
		disabled?: boolean;
		class?: string;
	}

	let { provider, model, onchange, disabled = false, class: className = '' }: Props = $props();

	let clients = $state<string[]>([]);
	let loadingClients = $state(false);
	let loadingModels = $state(false);

	// Cache: provider -> models, to avoid redundant fetches within the session.
	let modelCache = $state<Record<string, string[]>>({});

	let models = $derived(modelCache[provider] ?? []);

	async function fetchClients() {
		loadingClients = true;
		try {
			clients = await listLlmClients();
		} finally {
			loadingClients = false;
		}
	}

	async function fetchModels(client: string) {
		loadingModels = true;
		try {
			const result = await listLlmModels(client);
			modelCache = { ...modelCache, [client]: result };
		} finally {
			loadingModels = false;
		}
	}

	// Fetch providers on mount.
	$effect(() => {
		fetchClients();
	});

	// Fetch models when the provider changes (and isn't already cached).
	$effect(() => {
		if (provider && !(provider in modelCache)) {
			fetchModels(provider);
		}
	});

	// Once models load for the current provider, auto-select the first model
	// unless the current model value is already present in the list.
	$effect(() => {
		if (provider && models.length > 0 && !models.includes(model)) {
			onchange({ provider, model: models[0] });
		}
	});

	function handleProviderChange(event: Event) {
		const target = event.target as HTMLSelectElement;
		onchange({ provider: target.value, model });
	}

	function handleModelChange(event: Event) {
		const target = event.target as HTMLSelectElement;
		onchange({ provider, model: target.value });
	}

	/**
	 * Derives a human-readable display name from a raw model ID.
	 * Examples:
	 *   gemini-2.5-flash -> "Gemini 2.5 Flash"
	 *   gpt-4o-mini -> "GPT 4o Mini"
	 *   claude-sonnet-4-20250514 -> "Claude Sonnet 4"
	 *   meta-llama/llama-4-scout-17b-16e-instruct -> "Llama 4 Scout 17B 16E Instruct"
	 * Falls back to the raw ID when it can't confidently parse a segment.
	 */
	function humanizeModelId(id: string): string {
		if (!id) return id;

		const knownPrefixes: Record<string, string> = {
			gpt: 'GPT',
			claude: 'Claude',
			gemini: 'Gemini',
			llama: 'Llama',
			mistral: 'Mistral',
			grok: 'Grok'
		};

		// Drop organization/namespace prefixes (e.g. "meta-llama/llama-4-...").
		const basename = id.includes('/') ? (id.split('/').pop() ?? id) : id;

		const words = basename.split('-').filter(Boolean);

		const humanized = words
			.filter((word) => !/^\d{8}$/.test(word)) // drop date suffixes like 20250514
			.map((word) => {
				const lower = word.toLowerCase();
				if (knownPrefixes[lower]) {
					return knownPrefixes[lower];
				}
				if (/^\d+(\.\d+)?$/.test(word)) {
					// Pure numeric / version segment (e.g. "4", "2.5") — keep as-is.
					return word;
				}
				if (/^\d{2,}[a-z]+$/i.test(word)) {
					// Param/size specifiers (e.g. "17b", "16e") — uppercase fully.
					return word.toUpperCase();
				}
				// Default: capitalize the first character, preserve the rest.
				return word.charAt(0).toUpperCase() + word.slice(1);
			});

		return humanized.length > 0 ? humanized.join(' ') : id;
	}
</script>

<div class="flex flex-col gap-2 {className}">
	<div class="flex flex-col gap-1">
		<span class="text-sm font-medium text-base-content">Provider</span>
		<select
			class="select select-bordered"
			value={provider}
			disabled={disabled || loadingClients}
			onchange={handleProviderChange}
		>
			{#if loadingClients}
				<option value="" disabled>Loading providers...</option>
			{/if}
			{#each clients as client (client)}
				<option value={client}>{client}</option>
			{/each}
		</select>
	</div>

	<div class="flex flex-col gap-1">
		<span class="text-sm font-medium text-base-content">Model</span>
		<select
			class="select select-bordered"
			value={model}
			disabled={disabled || loadingModels || !provider}
			onchange={handleModelChange}
		>
			{#if loadingModels}
				<option value="" disabled>Loading models...</option>
			{/if}
			{#each models as modelId (modelId)}
				<option value={modelId}>{humanizeModelId(modelId)}</option>
			{/each}
		</select>
	</div>
</div>
