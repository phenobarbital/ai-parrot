<script lang="ts">
    import { onMount, tick } from 'svelte';
    import { DashboardContainer } from '$lib/dashboard/domain/dashboard-container.svelte.js';
    import DashboardContainerView from '$lib/dashboard/components/dashboard/dashboard-container.svelte';
    import ChatInput from '$lib/components/agents/ChatInput.svelte';
    import { chatWithAgent } from '$lib/api/agent';
    import type { AgentChatRequest } from '$lib/types/agent';
    import { toastStore } from '$lib/stores/toast.svelte';

    let { agentId = 'troc_finance' } = $props<{ agentId?: string }>();

    // Local scoped container for this dashboard
    const container = new DashboardContainer();
    let isLoading = $state(false);
    let currentSessionId = $state(crypto.randomUUID());

    onMount(() => {
        // Initialize with a default tab if none
        if (container.tabList.length === 0) {
            container.createTab({
                title: 'Agent Results',
                icon: '🤖',
                layoutMode: 'free' // or grid
            });
        }
    });

    async function handleSend(text: string, methodName?: string, outputMode?: string) {
        if (!text.trim()) return;
        isLoading = true;

        try {
            // Prepare payload
            const payload: AgentChatRequest = {
                query: text,
                session_id: currentSessionId,
                output_mode: outputMode
            };

            const result = await chatWithAgent(agentId, payload);
            
            // Create widget from response
            container.createWidgetFromAgentResponse(result);

        } catch (error: any) {
            console.error('Agent Chat Error:', error);
            toastStore.error(`Error: ${error.message}`);
        } finally {
            isLoading = false;
        }
    }
</script>

<div class="agent-dashboard h-full flex flex-col relative overflow-hidden">
    <!-- Main Dashboard Area -->
    <div class="flex-1 min-h-0 relative">
        <DashboardContainerView {container} />
    </div>

    <!-- Floating Chat Input (Bottom) -->
    <div class="p-4 z-20 bg-base-100/90 backdrop-blur-sm border-t border-base-200">
        <div class="max-w-4xl mx-auto w-full">
             <ChatInput 
                onSend={handleSend}
                {isLoading}
                text=""
            />
        </div>
    </div>
</div>

<style>
    .agent-dashboard {
        width: 100%;
        height: 100%;
    }
</style>
