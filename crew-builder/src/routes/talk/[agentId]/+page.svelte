<script lang="ts">
  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { botsApi, type BotSummary } from '$lib/api/bots';
  import { chatApi, type AgentMessageRequest, type ChatResponse } from '$lib/api/chat';
  import { authStore } from '$lib/stores/auth.svelte.ts';
  import { saveTurn } from '$lib/utils/conversation';
  import {
    loadQuestionHistory,
    saveQuestionHistory,
    type QuestionHistoryEntry
  } from '$lib/utils/talkHistory';
  import { LoadingSpinner } from '$lib/components';

  const { data } = $props<{ data: { agentId: string } }>();
  const agentId = $derived(data.agentId);

  type ConversationItem = {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: string;
    turnId?: string;
    raw?: ChatResponse;
    mode: 'talk' | 'method';
    methodName?: string;
    outputMode?: string;
    background?: boolean;
  };

  const outputModes = ['default', 'html', 'json', 'markdown', 'yaml', 'terminal'];

  let agent: BotSummary | null = $state(null);
  let loading = $state(true);
  let sending = $state(false);
  let error = $state('');
  let messages = $state<ConversationItem[]>([]);
  let history = $state<QuestionHistoryEntry[]>([]);
  let input = $state('');
  let mode = $state<'talk' | 'method'>('talk');
  let background = $state(false);
  let outputMode = $state('');
  let followUpTurnId = $state<string | null>(null);
  let methodName = $state('');
  let methodParams = $state<Array<{ id: string; key: string; value: string }>>([
    { id: crypto.randomUUID(), key: '', value: '' }
  ]);
  let attachments = $state<File[]>([]);

  const markdownToHtml = (text: string) => {
    if (!text) return '';

    const escapeHtml = (value: string) =>
      value
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\"/g, '&quot;')
        .replace(/'/g, '&#39;');

    let html = escapeHtml(text);

    html = html.replace(/```([\s\S]*?)```/g, (_match, code) => `<pre><code>${code}</code></pre>`);
    html = html.replace(/`([^`]+)`/g, (_match, code) => `<code>${code}</code>`);
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/__([^_]+)__/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    html = html.replace(/_([^_]+)_/g, '<em>$1</em>');
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
    html = html.replace(/^### (.*)$/gim, '<h3>$1</h3>');
    html = html.replace(/^## (.*)$/gim, '<h2>$1</h2>');
    html = html.replace(/^# (.*)$/gim, '<h1>$1</h1>');
    html = html.replace(/^\s*[-*] (.*)$/gim, '<li>$1</li>');
    html = html.replace(/(?:\n)(<li>.*<\/li>(?:\n<li>.*<\/li>)*)/g, '<ul>$1</ul>');

    const paragraphs = html
      .split(/\n{2,}/)
      .map((section) => `<p>${section.replace(/\n/g, '<br />')}</p>`)
      .join('');

    return paragraphs || html;
  };

  async function loadAgent() {
    loading = true;
    error = '';
    try {
      agent = await botsApi.getBot(agentId);
    } catch (err: any) {
      console.error('Failed to load agent', err);
      error = err?.response?.data?.message || 'Unable to load the agent right now.';
    } finally {
      loading = false;
    }
  }

  function refreshHistory() {
    history = loadQuestionHistory(agentId).sort(
      (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    );
  }

  function handleParamChange(id: string, field: 'key' | 'value', value: string) {
    methodParams = methodParams.map((param) =>
      param.id === id
        ? {
            ...param,
            [field]: value
          }
        : param
    );
  }

  function addParamRow() {
    methodParams = [...methodParams, { id: crypto.randomUUID(), key: '', value: '' }];
  }

  function removeParamRow(id: string) {
    methodParams = methodParams.filter((param) => param.id !== id);
    if (methodParams.length === 0) {
      addParamRow();
    }
  }

  function handleFileChange(event: Event) {
    const target = event.target as HTMLInputElement;
    const files = target.files ? Array.from(target.files) : [];
    attachments = files;
  }

  function selectFollowUp(turnId: string) {
    followUpTurnId = turnId;
  }

  async function sendMessage() {
    if (!input.trim() || sending) return;
    if (mode === 'method' && !methodName.trim()) {
      error = 'Method name is required when calling a method.';
      return;
    }

    const text = input.trim();
    const userMessage: ConversationItem = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
      mode,
      methodName: mode === 'method' ? methodName.trim() : undefined,
      outputMode: outputMode || undefined,
      background
    };
    messages = [...messages, userMessage];
    input = '';
    sending = true;
    error = '';

    const params = methodParams.reduce<Record<string, string>>((acc, item) => {
      if (item.key.trim()) acc[item.key.trim()] = item.value;
      return acc;
    }, {});

    const payload: AgentMessageRequest = {
      query: text,
      background,
      turn_id: followUpTurnId || undefined,
      output_mode: outputMode || undefined,
      method_name: mode === 'method' ? methodName.trim() : undefined,
      params,
      attachments: mode === 'method' ? attachments : []
    };

    try {
      const response = await chatApi.sendAgentMessage(agentId, payload);
      const reply = response?.response || response?.output || 'The agent did not return a response.';
      const assistantMessage: ConversationItem = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: reply,
        timestamp: new Date().toISOString(),
        turnId: response?.turn_id,
        raw: response,
        mode,
        methodName: payload.method_name,
        outputMode: outputMode || undefined,
        background
      };
      messages = [...messages, assistantMessage];
      if (response?.turn_id) {
        saveTurn(agentId, response);
        const historyEntry: QuestionHistoryEntry = {
          turnId: response.turn_id,
          question: text,
          timestamp: new Date().toISOString(),
          mode,
          methodName: payload.method_name,
          outputMode: outputMode || undefined,
          background
        };
        saveQuestionHistory(agentId, historyEntry);
        refreshHistory();
        followUpTurnId = response.turn_id;
      }
      attachments = [];
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
    refreshHistory();
  });
</script>

<svelte:head>
  <title>Talk to Agent</title>
</svelte:head>

{#if loading}
  <div class="flex min-h-screen items-center justify-center">
    <LoadingSpinner text="Loading agent..." />
  </div>
{:else if !agent}
  <div class="flex min-h-screen flex-col items-center justify-center gap-4">
    <p class="text-lg font-semibold text-base-content/80">{error || 'Agent not found.'}</p>
    <button class="btn btn-primary" type="button" on:click={() => goto('/agents')}>Back to agents</button>
  </div>
{:else}
  <div class="min-h-screen bg-base-200/40">
    <div class="mx-auto flex max-w-7xl gap-4 p-4 lg:gap-6 lg:p-8">
      <aside class="hidden w-72 flex-shrink-0 flex-col gap-4 rounded-3xl bg-base-100 p-5 shadow-xl lg:flex">
        <div class="space-y-1">
          <p class="text-sm text-base-content/60">Talking to</p>
          <h2 class="text-2xl font-bold text-base-content">{agent.name}</h2>
          <p class="text-sm text-base-content/70">{agent.description}</p>
        </div>
        <div class="divider my-2"></div>
        <div class="flex items-center justify-between text-sm font-semibold text-base-content/80">
          <span>Previous questions</span>
          <span class="badge badge-ghost">{history.length}</span>
        </div>
        <div class="flex-1 space-y-2 overflow-y-auto pr-1">
          {#if history.length === 0}
            <p class="rounded-xl bg-base-200/70 p-3 text-sm text-base-content/70">No questions yet.</p>
          {:else}
            {#each history as entry (entry.turnId)}
              <button
                type="button"
                class={`w-full rounded-xl border p-3 text-left text-sm transition hover:border-primary/60 hover:bg-primary/5 ${
                  followUpTurnId === entry.turnId ? 'border-primary bg-primary/10' : 'border-base-200'
                }`}
                on:click={() => selectFollowUp(entry.turnId)}
              >
                <div class="flex items-center justify-between text-xs uppercase text-base-content/70">
                  <span>{entry.mode === 'method' ? 'Method' : 'Talk'}</span>
                  {#if entry.methodName}
                    <span class="font-semibold text-primary">{entry.methodName}</span>
                  {/if}
                </div>
                <p
                  class="mt-1 overflow-hidden text-base-content"
                  style="display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;"
                >
                  {entry.question}
                </p>
                <p class="mt-1 text-[11px] font-mono text-base-content/60">{entry.turnId}</p>
              </button>
            {/each}
          {/if}
        </div>
      </aside>

      <section class="flex flex-1 flex-col gap-4">
        <div class="rounded-3xl border border-base-200 bg-base-100 p-4 shadow-sm">
          <div class="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div>
              <p class="text-sm text-base-content/60">Agent</p>
              <h1 class="text-2xl font-bold">{agent.name}</h1>
            </div>
            <div class="flex items-center gap-3">
              <span class="text-sm text-base-content/70">Talk</span>
              <label class="swap">
                <input
                  type="checkbox"
                  checked={mode === 'method'}
                  on:change={(event) => (mode = (event.target as HTMLInputElement).checked ? 'method' : 'talk')}
                />
                <div class="swap-on badge badge-primary">Method</div>
                <div class="swap-off badge badge-neutral">Chat</div>
              </label>
              <span class="text-sm text-base-content/70">Method</span>
            </div>
          </div>
        </div>

        <div class="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
          <div class="flex flex-col gap-4 rounded-3xl border border-base-200 bg-base-100 p-5 shadow-lg">
            <div class="flex flex-wrap items-center gap-3">
              <label class="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  class="toggle toggle-primary"
                  checked={background}
                  on:change={(event) => (background = (event.target as HTMLInputElement).checked)}
                />
                <span>Background</span>
              </label>
              <div class="flex items-center gap-2 text-sm">
                <span>Output mode:</span>
                <select
                  class="select select-bordered select-sm"
                  value={outputMode}
                  on:change={(event) => (outputMode = (event.target as HTMLSelectElement).value)}
                >
                  <option value="">default</option>
                  {#each outputModes as modeOption}
                    <option value={modeOption} selected={outputMode === modeOption}>{modeOption}</option>
                  {/each}
                </select>
              </div>
              {#if followUpTurnId}
                <div class="badge badge-outline badge-primary flex items-center gap-2 text-xs">
                  <span>Follow-up: {followUpTurnId}</span>
                  <button
                    type="button"
                    class="ml-1 text-primary"
                    aria-label="Clear follow up"
                    on:click={() => (followUpTurnId = null)}
                  >
                    ✕
                  </button>
                </div>
              {/if}
            </div>

            {#if mode === 'method'}
              <div class="space-y-3 rounded-2xl bg-base-200/60 p-4">
                <div class="flex flex-col gap-2 md:flex-row md:items-center">
                  <label class="text-sm font-semibold md:w-40">Method name</label>
                  <input
                    type="text"
                    class="input input-bordered w-full"
                    placeholder="e.g. summarize_document"
                    value={methodName}
                    on:input={(event) => (methodName = (event.target as HTMLInputElement).value)}
                  />
                </div>
                <div class="flex flex-col gap-2 md:flex-row md:items-start">
                  <label class="text-sm font-semibold md:w-40">Parameters</label>
                  <div class="flex-1 space-y-2">
                    {#each methodParams as param (param.id)}
                      <div class="flex flex-col gap-2 rounded-xl border border-base-300/70 p-3 md:flex-row md:items-center">
                        <input
                          type="text"
                          class="input input-bordered flex-1"
                          placeholder="key"
                          value={param.key}
                          on:input={(event) => handleParamChange(param.id, 'key', (event.target as HTMLInputElement).value)}
                        />
                        <input
                          type="text"
                          class="input input-bordered flex-[2]"
                          placeholder="value"
                          value={param.value}
                          on:input={(event) => handleParamChange(param.id, 'value', (event.target as HTMLInputElement).value)}
                        />
                        <button
                          type="button"
                          class="btn btn-ghost btn-sm"
                          on:click={() => removeParamRow(param.id)}
                          aria-label="Remove parameter"
                        >
                          ✕
                        </button>
                      </div>
                    {/each}
                    <button type="button" class="btn btn-outline btn-sm" on:click={addParamRow}>Add parameter</button>
                  </div>
                </div>
                <div class="flex flex-col gap-2 md:flex-row md:items-center">
                  <label class="text-sm font-semibold md:w-40">Attachments</label>
                  <input
                    type="file"
                    multiple
                    class="file-input file-input-bordered w-full"
                    on:change={handleFileChange}
                  />
                </div>
              </div>
            {/if}

            <div class="space-y-2">
              <label class="text-sm font-semibold text-base-content/80">Message</label>
              <textarea
                class="textarea textarea-bordered min-h-[140px] w-full font-mono"
                placeholder="Write your prompt here... (supports markdown)"
                value={input}
                on:input={(event) => (input = (event.target as HTMLTextAreaElement).value)}
                on:keydown={handleKeydown}
              ></textarea>
              <div class="flex items-center justify-between text-sm text-base-content/70">
                <span>Use Shift+Enter for a new line.</span>
                <button
                  class="btn btn-primary"
                  type="button"
                  disabled={sending}
                  on:click={sendMessage}
                >
                  {sending ? 'Sending...' : mode === 'method' ? 'Call method' : 'Send message'}
                </button>
              </div>
              {#if error}
                <p class="text-sm text-error">{error}</p>
              {/if}
            </div>
          </div>

          <div class="flex flex-col gap-3 rounded-3xl border border-base-200 bg-base-100 p-5 shadow-lg">
            <h3 class="text-lg font-semibold text-base-content">Responses</h3>
            <div class="flex-1 space-y-3 overflow-y-auto pr-1">
              {#if messages.length === 0}
                <p class="rounded-xl bg-base-200/70 p-3 text-sm text-base-content/70">No messages yet.</p>
              {:else}
                {#each messages as message (message.id)}
                  <div
                    class={`rounded-2xl border p-4 shadow-sm ${
                      message.role === 'user'
                        ? 'border-primary/40 bg-primary/5'
                        : 'border-base-200 bg-base-50'
                    }`}
                  >
                    <div class="flex flex-wrap items-center justify-between gap-2 text-xs text-base-content/60">
                      <div class="flex items-center gap-2">
                        <span class="font-semibold uppercase">{message.role}</span>
                        <span>•</span>
                        <span>{new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                      </div>
                      <div class="flex items-center gap-2">
                        {#if message.turnId}
                          <span class="badge badge-outline">Turn: {message.turnId}</span>
                        {/if}
                        {#if message.mode === 'method' && message.methodName}
                          <span class="badge badge-info badge-outline">{message.methodName}</span>
                        {/if}
                        {#if message.background}
                          <span class="badge badge-warning badge-outline">Background</span>
                        {/if}
                        {#if message.outputMode}
                          <span class="badge badge-outline">{message.outputMode}</span>
                        {/if}
                      </div>
                    </div>
                    {#if message.role === 'assistant'}
                      <div class="prose prose-sm max-w-none pt-3" on:click|stopPropagation>
                        {@html markdownToHtml(message.content)}
                      </div>
                    {:else}
                      <p class="pt-3 font-mono text-sm text-base-content">{message.content}</p>
                    {/if}
                  </div>
                {/each}
              {/if}
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
{/if}
