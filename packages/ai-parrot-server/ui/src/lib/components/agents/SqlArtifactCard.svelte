<script lang="ts">
  import { onMount } from "svelte";
  import { highlightElement } from "$lib/utils/highlight";
  import Icon from "@iconify/svelte";
  import { AppTooltip } from "$lib/ui/components";

  let {
    sql,
    rowCount = null,
    executionTimeMs = null,
    onSendToEditor,
  }: {
    sql: string;
    rowCount?: number | null;
    executionTimeMs?: number | null;
    onSendToEditor?: (sql: string) => void;
  } = $props();

  let codeRef = $state<HTMLElement>();
  let copied = $state(false);

  $effect(() => {
    if (codeRef && sql) {
      codeRef.textContent = sql;
      highlightElement(codeRef);
    }
  });

  async function copyToClipboard() {
    try {
      await navigator.clipboard.writeText(sql);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch (err) {
      console.error("Failed to copy SQL", err);
    }
  }
</script>

<div
  class="border-base-300 bg-base-100 rounded-box border overflow-hidden"
>
  <div
    class="border-b border-base-300 bg-base-200 px-4 py-2 flex items-center justify-between gap-2 text-sm font-medium"
  >
    <div class="flex items-center gap-2 min-w-0 flex-1">
      <Icon icon="mdi:database-search" class="size-4 text-blue-600 shrink-0" />
      <span class="truncate">SQL suggestion</span>
      {#if rowCount !== null && rowCount !== undefined && rowCount > 0}
        <span class="badge badge-sm border-none bg-blue-100 text-blue-700 shrink-0">
          {rowCount.toLocaleString()} rows
        </span>
      {/if}
      {#if executionTimeMs !== null && executionTimeMs !== undefined && executionTimeMs > 0}
        <span class="badge badge-sm border-none bg-slate-100 text-slate-700 shrink-0">
          {executionTimeMs.toFixed(1)} ms
        </span>
      {/if}
    </div>
    <div class="flex items-center gap-1 shrink-0">
      {#if onSendToEditor}
        <AppTooltip content="Send to active query editor" placement="bottom">
          <button
            class="inline-flex items-center justify-center size-7 rounded-md text-blue-700 bg-blue-50 hover:bg-blue-100 transition-colors"
            onclick={() => onSendToEditor?.(sql)}
            aria-label="Send SQL to active query editor"
          >
            <Icon icon="mdi:arrow-left" class="size-3.5" />
          </button>
        </AppTooltip>
      {/if}
      <AppTooltip content={copied ? "Copied!" : "Copy SQL"} placement="bottom">
        <button
          class="inline-flex items-center justify-center size-7 rounded-md text-slate-600 bg-slate-50 hover:bg-slate-100 transition-colors"
          onclick={copyToClipboard}
          aria-label="Copy SQL"
        >
          <Icon
            icon={copied ? "mdi:check" : "mdi:content-copy"}
            class={copied ? "size-3.5 text-emerald-600" : "size-3.5"}
          />
        </button>
      </AppTooltip>
    </div>
  </div>
  <pre class="m-0 overflow-x-auto"><code
      bind:this={codeRef}
      class="language-sql block px-4 py-3 text-xs"
    ></code></pre>
</div>
