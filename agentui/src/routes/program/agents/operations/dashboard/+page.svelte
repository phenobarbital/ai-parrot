<script lang="ts">
	import AgentChat from '$lib/components/agents/AgentChat.svelte';
</script>

<div class="flex h-full flex-col">
	<!-- Use a specific height or flex-1 to allow correct scrolling -->
	<div class="border-base-300 bg-base-100 flex-none border-b p-4">
		<h1 class="text-2xl font-bold">Operations Agent</h1>
		<p class="text-sm opacity-50">Interact with your AI assistant using the chat below.</p>
	</div>

	<div class="flex-1 overflow-hidden">
		<AgentChat agentName="hr_agent" />
	</div>
</div>
