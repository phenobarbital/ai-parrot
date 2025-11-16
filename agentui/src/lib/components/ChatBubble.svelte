<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { marked } from 'marked';
  import DOMPurify from 'isomorphic-dompurify';

  const props = $props<{
    role?: 'user' | 'assistant';
    content?: string;
    timestamp?: string;
    turnId?: string;
    selectable?: boolean;
    selected?: boolean;
  }>();

  const role = $derived(props.role ?? 'user');
  const content = $derived(props.content ?? '');
  const timestamp = $derived(props.timestamp ?? '');
  const turnId = $derived(props.turnId);
  const selectable = $derived(props.selectable ?? false);
  const selected = $derived(props.selected ?? false);

  const dispatch = createEventDispatcher<{ select: { turnId: string } }>();

  const sanitizedHtml = $derived(() => {
    const raw = marked.parse(content || '');
    return DOMPurify.sanitize(raw);
  });

  function handleClick() {
    if (selectable && turnId) {
      dispatch('select', { turnId });
    }
  }
</script>

<div
  class={`flex ${role === 'user' ? 'justify-end' : 'justify-start'}`}
  on:click={handleClick}
>
  <div
    class={`max-w-3xl rounded-3xl border ${
      role === 'user'
        ? 'bg-primary text-primary-content border-primary/20'
        : 'bg-base-200/70 text-base-content border-base-300'
    } p-4 text-sm shadow-sm transition ${selectable ? 'cursor-pointer hover:ring-2 hover:ring-primary/40' : ''} ${
      selected ? 'ring-2 ring-primary' : ''
    }`}
  >
    <div class="mb-2 flex items-center gap-2 text-xs opacity-70">
      <span class="font-semibold capitalize">{role}</span>
      <span>•</span>
      <span>{new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
    </div>

    {#if role === 'assistant'}
      <div class="chat-markdown" on:click|stopPropagation>
        {@html sanitizedHtml}
      </div>
    {:else}
      <p class="whitespace-pre-wrap">{content}</p>
    {/if}
  </div>
</div>
