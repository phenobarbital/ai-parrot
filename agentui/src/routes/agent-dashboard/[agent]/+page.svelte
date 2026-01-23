<script lang="ts">
	import { page } from '$app/stores';
	import AgentDashboard from '$lib/components/agents/AgentDashboard.svelte';

	// Get agent name from URL param
	let agentName = $derived($page.params.agent);
</script>

<div class="h-full w-full overflow-hidden">
	<AgentDashboard {agentName} />
</div>
