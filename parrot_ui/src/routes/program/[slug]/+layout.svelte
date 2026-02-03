<script lang="ts">
	import { page } from '$app/stores';
	import type { Program as ProgramType, Module } from '$lib/types';
	import Program from '$lib/components/program/Program.svelte';

	// Get data from page
	const program = $derived($page.data.program as ProgramType);
	const modules = $derived(($page.data.modules as Module[]) || []);
	const client = $derived($page.data.client);
	const clientName = $derived(client?.name || 'AI Parrot');

	let { children } = $props();
</script>

<Program {program} {modules} {clientName}>
	{@render children()}
</Program>
