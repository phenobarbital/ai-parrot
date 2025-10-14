<script>
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { authStore } from '$lib/stores/auth.svelte.ts';
  import { toastStore } from '$lib/stores/toast.svelte';
  import { LoadingSpinner } from '../../components';

  let username = $state('');
  let password = $state('');
  let error = $state('');
  let loading = $state(false);
  let showPassword = $state(false);

  // Redirect if already authenticated
  onMount(() => {
    if (authStore.isAuthenticated) {
      goto('/');
    }
  });

  async function handleSubmit(event) {
    event.preventDefault();
    error = '';
    loading = true;

    const result = await authStore.login(username, password);

    if (!result.success) {
      error = result.error;
      loading = false;

      // Show toast notification for better UX
      toastStore.error(result.error, 5000);
    } else {
      // Success - redirect happens in authStore.login
      toastStore.success('Login successful! Redirecting...', 2000);
    }
  }

  function togglePasswordVisibility() {
    showPassword = !showPassword;
  }
</script>

<svelte:head>
  <title>Login - Crew Builder</title>
</svelte:head>

<div class="flex min-h-screen items-center justify-center bg-base-200 px-4 py-12">
  <div class="w-full max-w-md">
    <!-- Logo/Title -->
    <div class="mb-8 text-center">
      <h1 class="mb-2 text-4xl font-bold text-primary">AI-Parrot</h1>
      <p class="text-base-content/70">Crew Builder</p>
    </div>

    <!-- Login Card -->
    <div class="card bg-base-100 shadow-xl">
      <div class="card-body">
        <h2 class="card-title justify-center text-2xl">Welcome Back</h2>
        <p class="text-center text-sm text-base-content/70">Sign in to your account</p>

        {#if error}
          <div class="alert alert-error mt-4">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              class="h-6 w-6 shrink-0 stroke-current"
              fill="none"
              viewBox="0 0 24 24"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <span>{error}</span>
          </div>
        {/if}

        <form onsubmit={handleSubmit} class="mt-4 space-y-4">
          <!-- Username -->
          <div class="form-control">
            <label class="label" for="username">
              <span class="label-text">Username or Email</span>
            </label>
            <input
              id="username"
              type="text"
              placeholder="Enter your username or email"
              class="input input-bordered w-full"
              bind:value={username}
              disabled={loading}
              required
              autocomplete="username"
            />
          </div>

          <!-- Password -->
          <div class="form-control">
            <label class="label" for="password">
              <span class="label-text">Password</span>
            </label>
            <div class="relative">
              <input
                id="password"
                type={showPassword ? 'text' : 'password'}
                placeholder="Enter your password"
                class="input input-bordered w-full pr-12"
                bind:value={password}
                disabled={loading}
                required
                autocomplete="current-password"
              />
              <button
                type="button"
                class="btn btn-ghost btn-sm absolute right-1 top-1"
                onclick={togglePasswordVisibility}
                tabindex="-1"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {#if showPassword}
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
                      d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.542 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"
                    />
                  </svg>
                {:else}
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
                      d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                    />
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                    />
                  </svg>
                {/if}
              </button>
            </div>
            <label class="label">
              <a href="/forgot-password" class="link-hover link label-text-alt">
                Forgot password?
              </a>
            </label>
          </div>

          <!-- Submit Button -->
          <button type="submit" class="btn btn-primary w-full" disabled={loading}>
            {#if loading}
              <LoadingSpinner size="sm" text="Signing in..." center={false} />
            {:else}
              Sign In
            {/if}
          </button>
        </form>

        <!-- Divider -->
        <div class="divider">OR</div>

        <!-- Register Link -->
        <div class="text-center">
          <p class="text-sm">
            Don't have an account?
            <a href="/register" class="link-hover link link-primary">Sign up</a>
          </p>
        </div>
      </div>
    </div>

    <!-- Footer -->
    <div class="mt-8 text-center text-sm text-base-content/60">
      <p>© 2025 AI-Parrot Crew Builder. All rights reserved.</p>
    </div>
  </div>
</div>
