<script lang="ts">
  import { marked } from 'marked';
  import DOMPurify from 'isomorphic-dompurify';

  interface Props {
    role?: 'user' | 'assistant';
    content?: string;
    timestamp?: string;
    turnId?: string;
    selectable?: boolean;
    selected?: boolean;
    onSelect?: (turnId: string) => void;
  }

  let {
    role = 'user',
    content = '',
    timestamp = '',
    turnId,
    selectable = false,
    selected = false,
    onSelect
  }: Props = $props();

  const sanitizedHtml = $derived.by(() => {
    const raw = marked.parse(content || '');
    return DOMPurify.sanitize(raw as string);
  });

  function handleClick() {
    if (selectable && turnId && onSelect) {
      onSelect(turnId);
    }
  }
</script>

<div
  class={`flex ${role === 'user' ? 'justify-end' : 'justify-start'}`}
  onclick={handleClick}
  role={selectable ? 'button' : undefined}
  tabindex={selectable ? 0 : undefined}
  onkeydown={(e) => e.key === 'Enter' && handleClick()}
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
      <div class="chat-markdown" onclick={(e) => e.stopPropagation()}>
        {@html sanitizedHtml}
      </div>
    {:else}
      <p class="whitespace-pre-wrap">{content}</p>
    {/if}
  </div>
</div>
