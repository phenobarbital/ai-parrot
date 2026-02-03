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

    let expanded = $state(false);
    
    const quickQuestions = [
        "What is the total revenue for last month?",
        "Show me the top performing stores",
        "Analyze the current cash flow",
        "Identify any anomalies in expenses"
    ];

    onMount(() => {
        // Initialize with a default tab if none
        if (container.tabList.length === 0) {
            container.createTab({
                title: 'Agent Results',
                icon: '🤖',
                layoutMode: 'grid' // or free
            });
        }
    });

    function toggleConnect() {
        expanded = !expanded;
    }

    function handleQuickQuestion(q: string) {
        handleSend(q);
    }

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

<div class="agent-dashboard h-full flex flex-col relative overflow-hidden bg-base-100">
    <!-- Top Collapsible Section -->
    <div class="border-b border-base-200 bg-base-100 relative z-20">
        <!-- Collapsible Header -->
        <button 
            class="w-full flex items-center justify-between px-4 py-2 hover:bg-base-200/50 transition-colors text-sm font-medium text-base-content/70"
            onclick={toggleConnect}
        >
            <div class="flex items-center gap-2">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="w-4 h-4">
                    <circle cx="11" cy="11" r="8"></circle>
                    <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
                <span>Ask a question...</span>
            </div>
            <svg 
                xmlns="http://www.w3.org/2000/svg" 
                width="16" 
                height="16" 
                viewBox="0 0 24 24" 
                fill="none" 
                stroke="currentColor" 
                stroke-width="2" 
                stroke-linecap="round" 
                stroke-linejoin="round" 
                class="w-4 h-4 transition-transform duration-200 {expanded ? 'rotate-180' : ''}"
            >
                <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
        </button>

        <!-- Collapsible Content -->
        {#if expanded}
            <div class="px-4 pb-4 border-t border-base-200 bg-base-50/50">
                <div class="w-full pt-4">
                    <ChatInput 
                        onSend={handleSend}
                        {isLoading}
                        text=""
                    />
                    
                    <!-- Quick Question Bubbles -->
                    <div class="flex flex-wrap gap-2 mt-3 pl-1">
                        {#each quickQuestions as q}
                            <button 
                                class="btn btn-sm bg-base-100 border-base-300 shadow-sm hover:shadow-md group rounded-full font-normal normal-case hover:border-blue-400 hover:text-blue-600 transition-all gap-2 h-auto py-1"
                                onclick={() => handleQuickQuestion(q)}
                            >
                                <svg xmlns="http://www.w3.org/2000/svg" aria-hidden="true" role="img" class="h-4 w-4 text-gray-400 transition-colors group-hover:text-blue-600 dark:text-gray-500 dark:group-hover:text-blue-400" width="1em" height="1em" viewBox="0 0 24 24"><path fill="currentColor" d="M12 21.154q-.69 0-1.201-.463t-.607-1.152h3.616q-.096.69-.607 1.152T12 21.154m-3.5-3.385v-1h7v1zM8.558 15q-1.417-.929-2.238-2.356T5.5 9.5q0-2.721 1.89-4.61T12 3t4.61 1.89T18.5 9.5q0 1.717-.82 3.144T15.442 15z"></path></svg>
                                <span class="text-xs text-base-content/70 group-hover:text-blue-600 transition-colors">{q}</span>
                            </button>
                        {/each}
                    </div>
                </div>
            </div>
        {/if}
    </div>

    <!-- Main Dashboard Area -->
    <div class="flex-1 min-h-0 relative bg-base-200/50">
        <DashboardContainerView {container} />
    </div>
</div>

<style>
    .agent-dashboard {
        width: 100%;
        height: 100%;
    }
</style>
