<script lang="ts">
  export let label: string | null = null;
  export let value: unknown;
  export let depth = 0;

  const isArray = Array.isArray(value);
  const isObject = value !== null && typeof value === 'object' && !isArray;
  const isExpandable = isArray || isObject;

  $: entries = (() => {
    if (isArray) {
      return (value as unknown[]).map((item, index) => ({ key: `[${index}]`, value: item }));
    }
    if (isObject) {
      return Object.entries(value as Record<string, unknown>).map(([key, entry]) => ({
        key,
        value: entry
      }));
    }
    return [];
  })();

  function describeValue(): string {
    if (isArray) {
      return `Array(${entries.length})`;
    }
    if (isObject) {
      return `Object(${entries.length})`;
    }
    if (value === null) {
      return 'null';
    }
    return typeof value;
  }

  function formatPrimitive(data: unknown): string {
    if (typeof data === 'string') {
      return `"${data}"`;
    }
    if (typeof data === 'number' || typeof data === 'boolean') {
      return String(data);
    }
    if (data === null) {
      return 'null';
    }
    if (typeof data === 'undefined') {
      return 'undefined';
    }
    return JSON.stringify(data);
  }

  const displayLabel = label ?? 'value';
</script>

<div class={`space-y-1 ${depth === 0 ? '' : 'border-l border-base-300 pl-3'}`}>
  {#if isExpandable}
    <details class="group space-y-1" open={depth < 1}>
      <summary class="cursor-pointer select-none text-sm font-semibold text-base-content">
        <span>{displayLabel}</span>
        <span class="ml-2 text-xs font-normal text-base-content/60">{describeValue()}</span>
      </summary>
      <div class="ml-3 space-y-1">
        {#each entries as entry (entry.key)}
          <svelte:self label={entry.key} value={entry.value} depth={depth + 1} />
        {/each}
      </div>
    </details>
  {:else}
    <div class="flex items-start gap-2 text-sm text-base-content">
      <span class="font-semibold text-base-content/70">{displayLabel}:</span>
      <code class="rounded bg-base-200 px-1 py-0.5 text-xs text-base-content">
        {formatPrimitive(value)}
      </code>
    </div>
  {/if}
</div>
