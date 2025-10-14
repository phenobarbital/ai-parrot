<script>
  import { themeStore, THEMES } from '$lib/stores/theme.svelte.js';

  const themeOptions = THEMES;
  let selectedTheme = $state(themeStore.currentTheme);

  $effect(() => {
    selectedTheme = themeStore.currentTheme;
  });

  function handleChange(event) {
    const target = event.target;
    themeStore.setTheme(target.value);
  }

  function handleToggle() {
    themeStore.toggleDarkMode();
  }
</script>

<div class="flex items-center gap-2">
  <button class="btn btn-sm btn-ghost" type="button" onclick={handleToggle} aria-label="Toggle theme">
    <span class="hidden sm:inline">Toggle</span>
    <span class="sm:hidden">🌓</span>
  </button>
  <select
    class="select select-bordered select-sm"
    bind:value={selectedTheme}
    onchange={handleChange}
    aria-label="Select theme"
  >
    {#each themeOptions as option}
      <option value={option}>{option}</option>
    {/each}
  </select>
</div>
