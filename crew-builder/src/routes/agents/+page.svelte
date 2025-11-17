<script lang="ts">
  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { authStore } from '$lib/stores/auth.svelte.ts';
  import { botsApi, type BotSummary } from '$lib/api/bots';
  import { BotCard, LoadingSpinner, ThemeSwitcher } from '../../components';
  import { config } from '$lib/config';

  let bots = $state<BotSummary[]>([]);
  let loading = $state(true);
  let error = $state('');
  let searchTerm = $state('');
  let selectedCategory = $state('All');
  let categories = $state<string[]>(['All']);

  $effect(() => {
    const uniqueCategories = Array.from(
      new Set(bots.map((bot) => bot.category?.trim() || 'Lifestyle & Wellness'))
    );
    categories = ['All', ...uniqueCategories];
  });

  $effect(() => {
    if (!categories.includes(selectedCategory)) {
      selectedCategory = 'All';
    }
  });

  async function fetchBots() {
    if (!browser) return;

    loading = true;
    error = '';

    try {
      const response = await botsApi.listBots();
      bots = response.bots || [];
    } catch (err: any) {
      console.error('Failed to load bots', err);
      error =
        err?.response?.data?.message || err?.message || 'Unable to load your agents right now.';
      bots = [];
    } finally {
      loading = false;
    }
  }

  let hasFetchedBots = false;

  const filteredBots = $derived(() => {
    let list = bots;

    if (selectedCategory !== 'All') {
      list = list.filter(
        (bot) => (bot.category || 'Lifestyle & Wellness') === selectedCategory
      );
    }

    if (searchTerm.trim()) {
      const search = searchTerm.trim().toLowerCase();
      list = list.filter(
        (bot) =>
          bot.name.toLowerCase().includes(search) ||
          bot.description?.toLowerCase().includes(search)
      );
    }

    return list;
  });

  function selectCategory(category: string) {
    selectedCategory = category;
  }

  function handleLogout() {
    authStore.logout();
  }

  const environmentLabel = config.environmentLabel;

  onMount(() => {
    if (!browser) return;

    const unsubscribe = authStore.subscribe((state) => {
      if (state.loading) return;

      if (!state.isAuthenticated) {
        hasFetchedBots = false;
        if (window.location.pathname !== '/login') {
          goto('/login');
        }
        return;
      }

      if (!hasFetchedBots) {
        hasFetchedBots = true;
        fetchBots();
      }
    });

    return () => {
      hasFetchedBots = false;
      unsubscribe();
    };
  });
</script>

<svelte:head>
  <title>Agents - Crew Builder</title>
</svelte:head>

{#if $authStore.loading}
  <div class="flex min-h-screen items-center justify-center">
    <LoadingSpinner text="Loading your workspace..." />
  </div>
{:else}
  <div class="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(79,70,229,0.08),_transparent)]">
    <div class="flex min-h-screen">
      <!-- Sidebar -->
      <aside class="hidden w-64 flex-shrink-0 flex-col border-r border-base-200 bg-base-100/80 p-6 lg:flex">
        <div class="mb-8 flex items-center gap-3">
          <div class="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary/10 text-lg font-semibold text-primary">
            🦜
          </div>
          <div>
            <p class="text-xs uppercase tracking-[0.2em] text-base-content/60">AI Parrot</p>
            <h1 class="text-xl font-semibold">Agents</h1>
          </div>
        </div>

        <nav class="space-y-2">
          <p class="text-xs font-semibold uppercase tracking-wide text-base-content/60">Workspace</p>
          <a class="btn btn-ghost btn-sm justify-start gap-3 text-base-content" href="/builder">
            <span class="rounded-full bg-primary/10 px-2 py-1 text-xs font-semibold text-primary">New</span>
            Create agent
          </a>
          <a class="btn btn-ghost btn-sm justify-start gap-3 text-base-content" href="/agents">Browse agents</a>
        </nav>

        <div class="mt-8 space-y-3">
          <p class="text-xs font-semibold uppercase tracking-wide text-base-content/60">Categories</p>
          {#each categories as category}
            <button
              class={`btn btn-ghost btn-sm w-full justify-between ${
                selectedCategory === category ? 'bg-primary/10 text-primary' : 'text-base-content/80'
              }`}
              type="button"
              onclick={() => selectCategory(category)}
            >
              <span>{category}</span>
              {#if selectedCategory === category}
                <span class="text-xs font-semibold">●</span>
              {/if}
            </button>
          {/each}
        </div>

        <div class="mt-auto rounded-2xl bg-gradient-to-br from-primary to-indigo-600 p-5 text-primary-content">
          <p class="text-sm font-semibold">Need help?</p>
          <p class="text-sm opacity-80">Our team is one click away.</p>
          <button class="btn btn-sm mt-4 border-none bg-white/20 text-white">Contact us</button>
        </div>
      </aside>

      <!-- Main content -->
      <main class="flex-1 p-6 lg:p-10">
        <div class="mb-8 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p class="text-sm text-base-content/70">All assistants for specific tasks</p>
            <h2 class="text-3xl font-bold">Agents</h2>
            {#if environmentLabel}
              <div class="badge badge-outline badge-sm mt-2 uppercase tracking-wide">
                {environmentLabel}
              </div>
            {/if}
          </div>
          <div class="flex items-center gap-3">
            <ThemeSwitcher showLabel={false} buttonClass="btn btn-sm btn-ghost" />
            <button class="btn btn-outline btn-sm" type="button" onclick={handleLogout}>Logout</button>
          </div>
        </div>

        <div class="mb-8 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div class="flex items-center gap-3 rounded-2xl border border-base-200 bg-base-100 px-4 py-3 shadow-sm">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              class="h-5 w-5 text-base-content/60"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              class="flex-1 bg-transparent text-sm outline-none"
              placeholder="Search agents"
              bind:value={searchTerm}
            />
          </div>
          <div class="flex gap-3">
            <button class="btn btn-primary" type="button" onclick={() => goto('/builder')}>
              Create AI agent
            </button>
            <div class="join">
              {#each categories.slice(0, 3) as quickCategory}
                <button
                  class={`btn btn-ghost btn-sm ${
                    selectedCategory === quickCategory ? 'btn-active text-primary' : 'text-base-content/70'
                  }`}
                  type="button"
                  onclick={() => selectCategory(quickCategory)}
                >
                  {quickCategory}
                </button>
              {/each}
            </div>
          </div>
        </div>

        {#if loading}
          <div class="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3">
            {#each Array(6) as _, index}
              <div class="h-48 animate-pulse rounded-3xl bg-base-200/80" aria-hidden="true"></div>
            {/each}
          </div>
        {:else if error}
          <div class="rounded-3xl border border-error/30 bg-error/10 p-8 text-center text-error">
            <p class="text-lg font-semibold">{error}</p>
            <button class="btn btn-error mt-4" onclick={fetchBots}>Retry</button>
          </div>
        {:else if filteredBots.length === 0}
          <div class="rounded-3xl border border-base-200 bg-base-100 p-10 text-center text-base-content/70">
            <p class="text-lg font-semibold">No agents match your filters.</p>
            <p class="mt-2">Try adjusting your search or categories.</p>
          </div>
        {:else}
          <div class="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3">
            {#each filteredBots as bot (bot.chatbot_id)}
              <BotCard {bot} />
            {/each}
          </div>
        {/if}
      </main>
    </div>
  </div>
{/if}
