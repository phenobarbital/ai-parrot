<script lang="ts">
  import { theme } from '$lib/stores/theme';

  const themeOptions = ['light', 'dark', 'cupcake', 'business'];

  function handleChange(event: Event) {
    const target = event.target as HTMLSelectElement;
    theme.set(target.value);
  }
</script>

<div class="flex items-center gap-2">
  <button
    class="btn btn-sm btn-ghost"
    type="button"
    on:click={() => theme.toggle()}
    aria-label="Toggle theme"
  >
    <span class="hidden sm:inline">Toggle</span>
    <span class="sm:hidden">🌓</span>
  </button>
  <select
    class="select select-bordered select-sm"
    on:change={handleChange}
    bind:value={$theme}
    aria-label="Select theme"
  >
    {#each themeOptions as option}
      <option value={option}>{option}</option>
    {/each}
  </select>
</div>
