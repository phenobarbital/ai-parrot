<script>
  import { goto } from '$app/navigation';
  import { browser } from '$app/environment';
  import { ThemeSwitcher, LoadingSpinner } from '../components';
  import { crew as crewApi } from '$lib/api';
  import { crewStore } from '$lib/stores/crewStore';
  import { authStore } from '$lib/stores/auth.svelte.ts';

  let redirecting = $state(false);
  let crews = $state([]);
  let crewsLoading = $state(false);
  let crewsError = $state('');
  let totalCrews = $state(0);

  $effect(() => {
    if (!browser) return;

    if (!authStore.loading && !authStore.isAuthenticated && !redirecting) {
      redirecting = true;
      goto('/login');
    }
  });

  async function fetchCrews() {
    if (!browser) return;

    crewsLoading = true;
    crewsError = '';

    try {
      const response = await crewApi.listCrews();
      crews = Array.isArray(response?.crews) ? response.crews : [];
      totalCrews = typeof response?.total === 'number' ? response.total : crews.length;
    } catch (error) {
      console.error('Failed to load crews', error);
      let responseMessage;
      if (
        typeof error === 'object' &&
        error !== null &&
        'response' in error &&
        error.response &&
        typeof error.response === 'object' &&
        'data' in error.response &&
        error.response.data &&
        typeof error.response.data === 'object' &&
        'message' in error.response.data &&
        typeof error.response.data.message === 'string'
      ) {
        responseMessage = error.response.data.message;
      }
      const fallbackMessage =
        error instanceof Error && typeof error.message === 'string'
          ? error.message
          : 'Unable to load crews at this time.';
      crewsError = responseMessage ?? fallbackMessage;
      crews = [];
      totalCrews = 0;
    } finally {
      crewsLoading = false;
    }
  }

  $effect(() => {
    if (!browser) return;

    if (!authStore.loading && authStore.isAuthenticated) {
      fetchCrews();
    }
  });

  async function handleLogout() {
    await authStore.logout();
  }

  function handleStartBuilding(event) {
    if (!browser) return;

    event?.preventDefault?.();
    crewStore.reset();
    goto('/builder');
  }

  function formatDate(dateString) {
    if (!dateString) {
      return '—';
    }

    const date = new Date(dateString);
    if (Number.isNaN(date.getTime())) {
      return dateString;
    }

    return date.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  }
</script>

<svelte:head>
  <title>Dashboard - Crew Builder</title>
</svelte:head>

{#if authStore.loading}
  <div class="flex min-h-screen items-center justify-center">
    <LoadingSpinner text="Loading your workspace..." />
  </div>
{:else}
  <div class="drawer lg:drawer-open">
    <input id="main-drawer" type="checkbox" class="drawer-toggle" />
    <div class="drawer-content flex flex-col">
      <!-- Navbar -->
      <div class="navbar sticky top-0 z-30 bg-base-100 shadow-md">
        <div class="flex-none lg:hidden">
          <label for="main-drawer" class="btn btn-square btn-ghost">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              class="inline-block h-6 w-6 stroke-current"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M4 6h16M4 12h16M4 18h16"
              ></path>
            </svg>
          </label>
        </div>
        <div class="flex-1">
          <h1 class="px-4 text-xl font-bold">Crew Builder</h1>
        </div>
        <div class="flex-none gap-2">
          <!-- Theme Selector -->
          <ThemeSwitcher showLabel={false} buttonClass="btn-ghost btn-square" />

          <!-- User Menu -->
          <div class="dropdown dropdown-end">
            <button class="btn btn-circle btn-ghost">
              <div class="avatar placeholder">
                <div class="w-10 rounded-full bg-primary text-primary-content">
                  <span class="text-xs">
                    {authStore.user?.username?.[0]?.toUpperCase() || 'U'}
                  </span>
                </div>
              </div>
            </button>
            <ul
              class="menu dropdown-content menu-sm z-[1] mt-3 w-52 rounded-box bg-base-100 p-2 shadow"
            >
              <li class="menu-title">
                <span>{authStore.user?.username || 'User'}</span>
              </li>
              <li><a href="/profile">Profile</a></li>
              <li><a href="/settings">Settings</a></li>
              <li><button onclick={handleLogout}>Logout</button></li>
            </ul>
          </div>
        </div>
      </div>

      <!-- Page Content -->
      <div class="flex-1 p-6">
        <div class="mb-6">
          <h2 class="text-3xl font-bold">Welcome back, {authStore.user?.username || 'User'}!</h2>
          <p class="text-base-content/70">Build and manage your AI agent crews</p>
        </div>

        <!-- Quick Stats -->
        <div class="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div class="stat bg-base-100 shadow">
            <div class="stat-figure text-primary">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                class="inline-block h-8 w-8 stroke-current"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"
                />
              </svg>
            </div>
            <div class="stat-title">Total Crews</div>
            <div class="stat-value text-primary">{crewsLoading ? '…' : totalCrews}</div>
            <div class="stat-desc">Active agent crews</div>
          </div>

          <div class="stat bg-base-100 shadow">
            <div class="stat-figure text-secondary">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                class="inline-block h-8 w-8 stroke-current"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M13 10V3L4 14h7v7l9-11h-7z"
                />
              </svg>
            </div>
            <div class="stat-title">Executions</div>
            <div class="stat-value text-secondary">0</div>
            <div class="stat-desc">Total runs</div>
          </div>

          <div class="stat bg-base-100 shadow">
            <div class="stat-figure text-accent">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                class="inline-block h-8 w-8 stroke-current"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z"
                />
              </svg>
            </div>
            <div class="stat-title">Success Rate</div>
            <div class="stat-value text-accent">100%</div>
            <div class="stat-desc">Last 30 days</div>
          </div>

          <div class="stat bg-base-100 shadow">
            <div class="stat-figure text-info">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                class="inline-block h-8 w-8 stroke-current"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
            </div>
            <div class="stat-title">Avg Duration</div>
            <div class="stat-value text-info">0s</div>
            <div class="stat-desc">Per execution</div>
          </div>
        </div>

        <!-- Action Cards -->
        <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div class="card bg-base-100 shadow-xl">
            <div class="card-body">
              <h2 class="card-title">Create New Crew</h2>
              <p>Design a new agent crew using our visual workflow builder.</p>
              <div class="card-actions justify-end">
                <a href="/builder" class="btn btn-primary" onclick={handleStartBuilding}>Start Building</a>
              </div>
            </div>
          </div>

          <div class="card bg-base-100 shadow-xl">
            <div class="card-body">
              <h2 class="card-title">Import Crew</h2>
              <p>Import an existing crew configuration from a JSON file.</p>
              <div class="card-actions justify-end">
                <button class="btn btn-secondary">Import JSON</button>
              </div>
            </div>
          </div>

          <div class="card bg-base-100 shadow-xl">
            <div class="card-body">
              <h2 class="card-title">Authorize Office 365</h2>
              <p>Grant delegated Microsoft 365 access for Parrot tools.</p>
              <div class="card-actions justify-end">
                <a class="btn btn-accent" href="/integrations/o365">Open Authorization</a>
              </div>
            </div>
          </div>

          <div class="card bg-base-100 shadow-xl">
            <div class="card-body">
              <h2 class="card-title">Talk to Agents</h2>
              <p>Browse existing agents and start chatting without leaving Crew Builder.</p>
              <div class="card-actions justify-end">
                <a class="btn btn-info" href="/agents">Open Agents</a>
              </div>
            </div>
          </div>
        </div>

        <!-- Recent Crews -->
        <div class="mt-6">
          <h3 class="mb-4 text-2xl font-bold">My Crews</h3>
          <div class="overflow-x-auto bg-base-100 shadow-xl">
            <table class="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Agents</th>
                  <th>Execution Mode</th>
                  <th>Created</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {#if crewsLoading}
                  <tr>
                    <td colspan="5" class="text-center text-base-content/70">
                      Loading crews...
                    </td>
                  </tr>
                {:else if crewsError}
                  <tr>
                    <td colspan="5" class="text-center text-error">
                      {crewsError}
                    </td>
                  </tr>
                {:else if !crews.length}
                  <tr>
                    <td colspan="5" class="text-center text-base-content/70">
                      No crews yet. Create your first crew to get started!
                    </td>
                  </tr>
                {:else}
                  {#each crews as crewItem (crewItem.crew_id)}
                    <tr>
                      <td>
                        <div class="flex flex-col">
                          <span class="font-semibold capitalize">{crewItem.name}</span>
                          <span class="text-sm text-base-content/70">{crewItem.description}</span>
                        </div>
                      </td>
                      <td>{crewItem.agent_count ?? '—'}</td>
                      <td class="capitalize">{crewItem.execution_mode || '—'}</td>
                      <td>{formatDate(crewItem.created_at)}</td>
                      <td>
                        <div class="flex gap-2">
                          <a class="btn btn-ghost btn-xs" href={`/builder?crew_id=${crewItem.crew_id}`}>
                            View
                          </a>
                          <a class="btn btn-primary btn-xs" href={`/crew/ask?crew_id=${crewItem.crew_id}`}>
                            Ask
                          </a>
                        </div>
                      </td>
                    </tr>
                  {/each}
                {/if}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- Sidebar -->
    <div class="drawer-side">
      <label for="main-drawer" aria-label="close sidebar" class="drawer-overlay"></label>
      <aside class="flex min-h-screen w-64 flex-col bg-base-200">
        <!-- Logo -->
        <div class="flex h-16 items-center gap-2 px-4">
          <div class="avatar">
            <div class="w-10 rounded-lg bg-primary text-primary-content">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                class="h-6 w-6 stroke-current"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M13 10V3L4 14h7v7l9-11h-7z"
                />
              </svg>
            </div>
          </div>
          <span class="text-lg font-bold">AI-Parrot</span>
        </div>

        <!-- Navigation Menu -->
        <ul class="menu flex-1 p-4">
          <li class="menu-title">
            <span>Main</span>
          </li>
          <li>
            <a href="/" class="active">
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
                  d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"
                />
              </svg>
              Dashboard
            </a>
          </li>
          <li>
            <a href="/builder" onclick={handleStartBuilding}>
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
                  d="M14 10l-2 1m0 0l-2-1m2 1v2.5M20 7l-2 1m2-1l-2-1m2 1v2.5M14 4l-2-1-2 1M4 7l2-1M4 7l2 1M4 7v2.5M12 21l-2-1m2 1l2-1m-2 1v-2.5M6 18l-2-1v-2.5M18 18l2-1v-2.5"
                />
              </svg>
              Crew Builder
            </a>
          </li>
          <li>
            <a href="/crew/ask">
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
                  d="M7 8h10M7 12h6m-5 8l-4 4v-4H4a3 3 0 01-3-3V5a3 3 0 013-3h16a3 3 0 013 3v10a3 3 0 01-3 3H9z"
                />
              </svg>
              Ask a Crew
            </a>
          </li>
          <li>
            <a href="/agents">
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
                  d="M8 10h.01M12 10h.01M16 10h.01M9 16h6m2 5a2 2 0 002-2V6a2 2 0 00-2-2H7a2 2 0 00-2 2v13l3-3h10z"
                />
              </svg>
              Agents
            </a>
          </li>
          <li>
            <a href="/crews">
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
                  d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"
                />
              </svg>
              My Crews
            </a>
          </li>
          <li class="menu-title">
            <span>Resources</span>
          </li>
          <li>
            <a href="/templates">
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
                  d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
                />
              </svg>
              Templates
            </a>
          </li>
          <li>
            <a href="/docs">
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
                  d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"
                />
              </svg>
              Documentation
            </a>
          </li>
        </ul>
      </aside>
    </div>
  </div>
{/if}
