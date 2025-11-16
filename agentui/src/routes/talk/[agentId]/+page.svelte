<script lang="ts">
  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { authStore } from '$lib/stores/auth.svelte.ts';
  import { botsApi, type BotSummary } from '$lib/api/bots';
  import { chatApi, type ChatResponse } from '$lib/api/chat';
  import { getTurn, saveTurn, loadConversation } from '$lib/utils/conversation';
  import { ChatBubble, LoadingSpinner } from '../../../components';

  export let data: { agentId: string };

  let agent: BotSummary | null = $state(null);
  type ChatMessage = {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: string;
    turnId?: string;
  };

  let messages = $state<ChatMessage[]>([]);
  let input = $state('');
  let sending = $state(false);
  let loading = $state(true);
  let error = $state('');
  let leftMenu = ['Chat', 'Content', 'Prompts', 'Playbooks'];
  let selectedMenu = $state('Chat');
  let selectedTurnId = $state<string | null>(null);
  let selectedTurn = $state<ChatResponse | null>(null);
  let storedTurnOrder = $state<string[]>([]);

  const agentId = data.agentId;

  async function loadAgent() {
    if (!browser) return;
    loading = true;
    error = '';

    try {
      agent = await botsApi.getBot(agentId);
    } catch (err: any) {
      console.error('Failed to load agent', err);
      error = err?.response?.data?.message || 'Unable to load the agent right now.';
      agent = null;
    } finally {
      loading = false;
    }
  }

  function loadStoredTurns() {
    if (!browser) return;
    const conversation = loadConversation(agentId);
    storedTurnOrder = conversation.order;
  }

  async function sendMessage() {
    if (!input.trim() || sending) return;

    const text = input.trim();
    input = '';

    const userMessage = {
      id: crypto.randomUUID(),
      role: 'user' as const,
      content: text,
      timestamp: new Date().toISOString()
    };
    messages = [...messages, userMessage];
    sending = true;
    error = '';

    try {
      const response = await chatApi.sendChat(agentId, { query: text });
      const reply = response?.response || response?.message || 'The agent did not return a response.';

      const assistantMessage = {
        id: crypto.randomUUID(),
        role: 'assistant' as const,
        content: reply,
        timestamp: new Date().toISOString(),
        turnId: response?.turn_id
      };
      messages = [...messages, assistantMessage];
      if (response?.turn_id) {
        saveTurn(agentId, response);
        loadStoredTurns();
        selectedTurnId = response.turn_id;
        selectedTurn = response;
      }
    } catch (err: any) {
      console.error('Chat failed', err);
      error = err?.response?.data?.message || err?.message || 'Chat failed. Please try again.';
      messages = messages.filter((message) => message.id !== userMessage.id);
    } finally {
      sending = false;
    }
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  }

  onMount(() => {
    if (!browser) return;
    if (!$authStore.isAuthenticated && !$authStore.loading) {
      goto('/login');
      return;
    }
    loadAgent();
    loadStoredTurns();
  });

  function handleBubbleSelect(event: CustomEvent<{ turnId: string }>) {
    const { turnId } = event.detail;
    if (!turnId) return;
    selectedTurnId = turnId;
    selectedTurn = getTurn(agentId, turnId);
  }
</script>

<svelte:head>
  <title>Chat - {agent?.name || 'Agent'}</title>
</svelte:head>

{#if loading}
  <div class="flex min-h-screen items-center justify-center">
    <LoadingSpinner text="Loading agent..." />
  </div>
{:else if !agent}
  <div class="flex min-h-screen flex-col items-center justify-center gap-4">
    <p class="text-lg font-semibold text-base-content/80">{error || 'Agent not found.'}</p>
    <button class="btn btn-primary" on:click={() => goto('/')}>Back to agents</button>
  </div>
{:else}
  <div class="min-h-screen bg-base-200/40">
    <div class="mx-auto flex min-h-screen max-w-[1400px] gap-6 p-4 lg:p-8">
      <!-- Left rail -->
      <aside class="hidden w-56 flex-col rounded-3xl bg-base-100 p-6 shadow-xl lg:flex">
        <div class="mb-6">
          <p class="text-sm font-semibold text-base-content/60">{agent.category || 'Agent'}</p>
          <h2 class="text-2xl font-bold">{agent.name}</h2>
          <p class="text-sm text-base-content/70">{agent.description}</p>
        </div>
        <nav class="space-y-2">
          {#each leftMenu as item}
            <button
              class={`btn btn-ghost w-full justify-start ${
                selectedMenu === item ? 'bg-primary/10 text-primary' : 'text-base-content/80'
              }`}
              type="button"
              on:click={() => (selectedMenu = item)}
            >
              {item}
            </button>
          {/each}
        </nav>
        <div class="mt-auto rounded-2xl bg-gradient-to-br from-primary to-indigo-600 p-4 text-sm text-primary-content">
          <p class="font-semibold">Coming soon</p>
          <p class="opacity-80">Quick access to prompts, automations, and knowledge.</p>
        </div>
      </aside>

      <!-- Chat area -->
      <section class="flex flex-1 flex-col gap-4">
        <div class="rounded-3xl border border-base-200 bg-base-100 p-4 shadow-sm">
          <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p class="text-sm text-base-content/60">Chat with</p>
              <h1 class="text-2xl font-bold">{agent.name}</h1>
            </div>
            <div class="flex items-center gap-2 text-sm text-success">
              <span class="h-2 w-2 rounded-full bg-success"></span>
              Available
            </div>
          </div>
        </div>

        <div class="flex flex-1 flex-col gap-4 rounded-3xl border border-base-200 bg-base-100 p-6 shadow-lg">
          <div class="flex-1 space-y-4 overflow-y-auto pr-2">
            {#if messages.length === 0}
              <div class="rounded-2xl bg-base-200/60 p-6 text-center text-base-content/70">
                Say hello to start the conversation.
              </div>
            {:else}
              {#each messages as message (message.id)}
                <ChatBubble
                  role={message.role}
                  content={message.content}
                  timestamp={message.timestamp}
                  turnId={message.turnId}
                  selectable={message.role === 'assistant'}
                  selected={message.turnId ? message.turnId === selectedTurnId : false}
                  on:select={handleBubbleSelect}
                />
              {/each}
            {/if}
          </div>

          {#if error}
            <div class="alert alert-error">
              <span>{error}</span>
            </div>
          {/if}

          <div class="rounded-2xl border border-base-200 bg-base-100 p-4 shadow-inner">
            <textarea
              class="textarea textarea-ghost min-h-[120px] w-full resize-none text-base"
              placeholder={`Ask ${agent.name} anything...`}
              bind:value={input}
              on:keydown={handleKeydown}
            ></textarea>
            <div class="mt-3 flex items-center justify-between">
              <div class="flex gap-2 text-sm text-base-content/60">
                <button class="btn btn-ghost btn-sm" type="button">➕ Attachment</button>
                <button class="btn btn-ghost btn-sm" type="button">📎 Reference</button>
              </div>
              <button class="btn btn-primary" type="button" disabled={sending} on:click={sendMessage}>
                {#if sending}
                  <LoadingSpinner size="sm" text="Asking..." center={false} />
                {:else}
                  Send
                {/if}
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- Right sidebar -->
      <aside class="hidden w-80 flex-shrink-0 flex-col gap-4 rounded-3xl bg-base-100 p-6 shadow-xl xl:flex">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-base-content/60">Agent details</p>
          <h3 class="text-xl font-semibold">{agent.name}</h3>
          <p class="text-sm text-base-content/70">{agent.description || 'No description available.'}</p>
        </div>
        <div class="space-y-3 rounded-2xl bg-base-200/70 p-4 text-sm">
          <div class="flex items-center justify-between">
            <span class="text-base-content/70">Owner</span>
            <span class="font-semibold">{agent.owner || 'N/A'}</span>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-base-content/70">Category</span>
            <span class="font-semibold">{agent.category || 'General'}</span>
          </div>
        </div>

        <div class="rounded-2xl border border-base-200 p-4 text-sm">
          <div class="flex items-center justify-between">
            <div>
              <p class="text-xs font-semibold uppercase tracking-wide text-base-content/60">Turn inspector</p>
              <p class="text-sm text-base-content/70">Click any assistant bubble to inspect the payload.</p>
            </div>
            {#if selectedTurnId}
              <span class="badge badge-outline badge-sm">{selectedTurnId.slice(0, 8)}…</span>
            {/if}
          </div>

          <details class="mt-3" open={!!selectedTurn}>
            <summary class="cursor-pointer font-semibold">Response payload</summary>
            {#if selectedTurn}
              <pre class="mt-3 max-h-80 overflow-auto rounded-2xl bg-base-300/40 p-3 text-xs">
{JSON.stringify(selectedTurn, null, 2)}
              </pre>
            {:else}
              <p class="mt-3 text-xs text-base-content/60">Select a turn to reveal the JSON response.</p>
            {/if}
          </details>

          {#if storedTurnOrder.length > 0}
            <div class="mt-4 space-y-1 text-xs">
              <p class="font-semibold text-base-content">Stored turns</p>
              {#each storedTurnOrder.slice().reverse() as turn}
                <button
                  type="button"
                  class={`btn btn-ghost btn-xs w-full justify-between ${
                    selectedTurnId === turn ? 'text-primary' : 'text-base-content/70'
                  }`}
                  on:click={() => {
                    selectedTurnId = turn;
                    selectedTurn = getTurn(agentId, turn);
                  }}
                >
                  <span>{turn.slice(0, 8)}…</span>
                  <span>Inspect</span>
                </button>
              {/each}
            </div>
          {/if}
        </div>
      </aside>
    </div>
  </div>
{/if}
