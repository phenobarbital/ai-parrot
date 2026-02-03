<script lang="ts">
    import { userWebSocket } from '$lib/stores/websocket.svelte';
    import { notificationStore } from '$lib/stores/notifications.svelte';

    let message = $state('');
    let targetType = $state<'channel' | 'direct'>('channel');
    let target = $state('information'); // Default channel
    
    // For now, manual target entry. In future, could fetch user list.
    
    function handleSend() {
        if (!message) return;

        if (targetType === 'channel') {
            userWebSocket.send(target, message);
            notificationStore.add({
                title: `Sent to ${target}`,
                message: message,
                type: 'success',
                toast: false // Don't toast own messages
            });
        } else {
            userWebSocket.sendDirect(target, message);
            notificationStore.add({
                title: `Sent to ${target}`,
                message: message,
                type: 'success',
                toast: false
            });
        }
        
        message = '';
    }

    function handleKeyDown(e: KeyboardEvent) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    }
</script>

<div class="card bg-base-100 shadow-xl h-full flex flex-col">
    <div class="card-body flex-1 flex flex-col">
        <h2 class="card-title flex justify-between">
            Message Center
            <div class="badge {userWebSocket.status === 'authenticated' ? 'badge-success' : 'badge-warning'} gap-2">
                {userWebSocket.status}
            </div>
        </h2>
        
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div class="form-control">
                <label class="label cursor-pointer justify-start gap-4">
                    <span class="label-text font-bold">Send To:</span> 
                    <label class="label cursor-pointer gap-2">
                        <input type="radio" name="targetType" class="radio radio-primary radio-sm" value="channel" bind:group={targetType} />
                        <span class="label-text">Channel</span>
                    </label>
                    <label class="label cursor-pointer gap-2">
                        <input type="radio" name="targetType" class="radio radio-secondary radio-sm" value="direct" bind:group={targetType} />
                        <span class="label-text">User</span>
                    </label>
                </label>
            </div>
            
            <div class="form-control">
                {#if targetType === 'channel'}
                     <label class="input input-bordered flex items-center gap-2">
                        Channel
                        <input type="text" class="grow" placeholder="channel_name" bind:value={target} />
                    </label>
                    <div class="text-xs text-base-content/60 mt-1 pl-1">
                        Subscribed: {userWebSocket.channels.join(', ')}
                    </div>
                {:else}
                    <label class="input input-bordered flex items-center gap-2">
                        User
                        <input type="text" class="grow" placeholder="username" bind:value={target} />
                    </label>
                {/if}
            </div>
        </div>

        <div class="divider">Compose</div>

        <div class="flex-1 min-h-[200px]">
            <textarea 
                class="textarea textarea-bordered w-full h-full resize-none font-mono" 
                placeholder="Type your message here... (Press Enter to send)"
                bind:value={message}
                onkeydown={handleKeyDown}
            ></textarea>
        </div>

        <div class="card-actions justify-end mt-4">
            <button 
                class="btn btn-primary" 
                onclick={handleSend}
                disabled={!message || userWebSocket.status !== 'authenticated'}
            >
                Send Message
                <svg class="w-4 h-4 ml-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"></path></svg>
            </button>
        </div>
    </div>
</div>
