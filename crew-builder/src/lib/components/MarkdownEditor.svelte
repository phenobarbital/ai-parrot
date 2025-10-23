<script lang="ts">
  import { markdownToHtml } from '$lib/utils/markdown';

  export let label = 'Question';
  export let id: string | undefined;
  export let value = '';
  export let placeholder = 'Write your prompt using Markdown...';
  export let helperText = '';
  export let disabled = false;

  const fallbackId = `markdown-editor-${Math.random().toString(36).slice(2, 10)}`;
  $: textareaId = id && id.trim() ? id : fallbackId;
  $: previewHtml = markdownToHtml(value ?? '');
</script>

<div class="space-y-2">
  {#if label}
    <label class="block text-sm font-semibold text-base-content/80" for={textareaId}>{label}</label>
  {/if}

  <div class="grid gap-4 md:grid-cols-2">
    <textarea
      bind:value
      {disabled}
      rows="12"
      class="textarea textarea-bordered w-full resize-y"
      placeholder={placeholder}
      id={textareaId}
    ></textarea>

    <div class="rounded-lg border border-base-300 bg-base-200 p-4">
      <div class="mb-2 text-xs font-semibold uppercase tracking-wide text-base-content/60">
        Preview
      </div>
      {#if previewHtml}
        <div class="space-y-2 text-sm leading-relaxed text-base-content" aria-live="polite">
          {@html previewHtml}
        </div>
      {:else}
        <p class="text-sm text-base-content/60">The rendered Markdown will appear here.</p>
      {/if}
    </div>
  </div>

  {#if helperText}
    <p class="text-xs text-base-content/60">{helperText}</p>
  {/if}
</div>
