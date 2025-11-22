<script lang="ts">
  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { authStore } from '$lib/stores/auth.svelte.ts';
  import { botsApi, type BotSummary } from '$lib/api/bots';
  import { chatApi, type ChatResponse } from '$lib/api/chat';
  import { getTurn, saveTurn, loadConversation } from '$lib/utils/conversation';
  import { ChatBubble, LoadingSpinner } from '../../../components';

  const { data } = $props<{ data: { agentId: string } }>();

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

  const agentId = $derived(data.agentId);

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

  function selectTurn(turnId: string | null | undefined) {
    if (!turnId) return;
    selectedTurnId = turnId;
    selectedTurn = getTurn(agentId, turnId);
  }

  function handleBubbleSelect(event: CustomEvent<{ turnId: string }>) {
    selectTurn(event.detail.turnId);
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
    <button class="btn btn-primary" onclick={() => goto('/agents')}>Back to agents</button>
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
              onclick={() => (selectedMenu = item)}
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
            <div class="rounded-2xl border border-error/40 bg-error/10 p-3 text-sm text-error">
              {error}
            </div>
          {/if}

          <div class="rounded-2xl border border-base-200 bg-base-100/80 p-4">
            <div class="rounded-2xl border border-base-300 bg-base-200/50">
              <textarea
                class="textarea textarea-ghost h-32 w-full resize-none border-none bg-transparent text-base focus:outline-none"
                placeholder={`Message ${agent.name}`}
                bind:value={input}
                onkeydown={handleKeydown}
              ></textarea>
            </div>
            <div class="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div class="flex gap-2 text-sm text-base-content/70">
                <button class="btn btn-ghost btn-sm" type="button" disabled>
                  <span>✨</span>
                  Templates
                </button>
                <button class="btn btn-ghost btn-sm" type="button" disabled>
                  <span>📎</span>
                  Attach
                </button>
              </div>
              <button class={`btn btn-primary ${sending ? 'loading' : ''}`} onclick={sendMessage} disabled={sending}>
                {sending ? 'Sending' : 'Send message'}
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- Insights rail -->
      <aside class="hidden w-72 flex-col gap-4 lg:flex">
        <div class="rounded-3xl border border-base-200 bg-base-100 p-5">
          <h3 class="text-lg font-semibold">Recent Turns</h3>
          <div class="mt-4 space-y-2">
            {#if storedTurnOrder.length === 0}
              <p class="text-sm text-base-content/60">Send a message to start tracking turns.</p>
            {:else}
              {#each storedTurnOrder.slice().reverse() as turnId}
                <button
                  class={`btn btn-ghost btn-sm w-full justify-between ${
                    selectedTurnId === turnId ? 'bg-primary/10 text-primary' : 'text-base-content/80'
                  }`}
                  type="button"
                  onclick={() => selectTurn(turnId)}
                >
                  <span class="truncate">Turn {turnId.slice(0, 6)}</span>
                  <span>→</span>
                </button>
              {/each}
            {/if}
          </div>
        </div>

        <div class="rounded-3xl border border-base-200 bg-base-100 p-5">
          <h3 class="text-lg font-semibold">Turn details</h3>
          {#if !selectedTurn}
            <p class="mt-2 text-sm text-base-content/60">Select a turn to inspect inputs and outputs.</p>
          {:else}
            <div class="mt-4 space-y-3 text-sm">
              <div>
                <p class="font-semibold text-base-content/70">Prompt</p>
                <p class="text-base-content">{selectedTurn.input}</p>
              </div>
              <div>
                <p class="font-semibold text-base-content/70">Response</p>
                <p class="text-base-content">{selectedTurn.output || selectedTurn.response}</p>
              </div>
              <div>
                <p class="font-semibold text-base-content/70">Turn ID</p>
                <p class="font-mono text-xs text-base-content/80">{selectedTurn.turn_id}</p>
              </div>
            </div>
          {/if}
        </div>
      </aside>
    </div>
  </div>
{/if}
