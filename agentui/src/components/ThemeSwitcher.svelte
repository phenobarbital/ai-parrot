<script>
  import { themeStore, THEMES } from '$lib/stores/theme.svelte.js';

  let { showLabel = true, buttonClass = 'btn-ghost' } = $props();

  let showDropdown = $state(false);
  let searchQuery = $state('');

  // Derived filtered themes
  let filteredThemes = $derived(
    searchQuery
      ? THEMES.filter((theme) => theme.toLowerCase().includes(searchQuery.toLowerCase()))
      : THEMES
  );

  let currentTheme = $state('light');

  function selectTheme(theme) {
    themeStore.setTheme(theme);
    showDropdown = false;
    searchQuery = '';
  }

  function toggleDropdown() {
    showDropdown = !showDropdown;
  }

  // Close dropdown when clicking outside
  function handleClickOutside(event) {
    if (!event.target.closest('.theme-dropdown-container')) {
      showDropdown = false;
    }
  }

  $effect(() => {
    if (typeof document === 'undefined') {
      return () => {};
    }

    if (showDropdown) {
      document.addEventListener('click', handleClickOutside);
    } else {
      document.removeEventListener('click', handleClickOutside);
    }

    return () => {
      document.removeEventListener('click', handleClickOutside);
    };
  });

  $effect(() => {
    const unsubscribe = themeStore.subscribe((value) => {
      currentTheme = value.currentTheme;
    });

    return () => unsubscribe();
  });
</script>

<div class="theme-dropdown-container relative">
  <button
    type="button"
    class="btn {buttonClass} gap-2"
    onclick={toggleDropdown}
    aria-label="Theme Selector"
  >
    <svg
      xmlns="http://www.w3.org/2000/svg"
      class="h-5 w-5"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
    >
      <path
        stroke-linecap="round"
        stroke-linejoin="round"
        stroke-width="2"
        d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01"
      />
    </svg>
    {#if showLabel}
      <span class="hidden sm:inline capitalize">{currentTheme}</span>
    {/if}
    <svg
      class="h-4 w-4 fill-current"
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 20 20"
    >
      <path d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" />
    </svg>
  </button>

  {#if showDropdown}
    <div class="absolute right-0 z-[100] mt-2 w-64 rounded-box bg-base-100 shadow-2xl">
      <div class="p-3">
        <!-- Search Input -->
        <input
          type="text"
          placeholder="Search themes..."
          class="input input-bordered input-sm w-full"
          bind:value={searchQuery}
        />
      </div>

      <!-- Themes List -->
      <ul class="menu menu-sm max-h-96 overflow-y-auto p-2">
        {#if filteredThemes.length === 0}
          <li class="disabled">
            <span class="text-base-content/50">No themes found</span>
          </li>
        {:else}
          {#each filteredThemes as theme}
            <li>
              <button
                class:active={currentTheme === theme}
                onclick={() => selectTheme(theme)}
                data-theme={theme}
              >
                <div class="flex w-full items-center justify-between">
                  <span class="capitalize">{theme}</span>
                  <div class="flex gap-1">
                    <div
                      class="h-3 w-3 rounded bg-primary"
                      data-theme={theme}
                    ></div>
                    <div
                      class="h-3 w-3 rounded bg-secondary"
                      data-theme={theme}
                    ></div>
                    <div
                      class="h-3 w-3 rounded bg-accent"
                      data-theme={theme}
                    ></div>
                  </div>
                </div>
              </button>
            </li>
          {/each}
        {/if}
      </ul>

      <!-- Quick Actions -->
      <div class="border-t border-base-300 p-2">
        <button
          class="btn btn-sm btn-block"
          onclick={() => themeStore.toggleDarkMode()}
        >
          Toggle Dark Mode
        </button>
      </div>
    </div>
  {/if}
</div>

<style>
  .theme-dropdown-container {
    position: relative;
  }
</style>
