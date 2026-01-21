<!-- src/lib/navauth/components/LoginForm.svelte -->
<script lang="ts">
  import type { NavAuthStore } from '../store.svelte';

  interface Props {
    auth: NavAuthStore;
    onSuccess?: () => void;
    onError?: (error: string) => void;
    showForgotPassword?: boolean;
    forgotPasswordHref?: string;
  }

  let {
    auth,
    onSuccess,
    onError,
    showForgotPassword = false,
    forgotPasswordHref = '/forgot-password'
  }: Props = $props();

  let username = $state('');
  let password = $state('');
  let showPassword = $state(false);
  let loading = $state(false);
  let error = $state('');

  async function handleSubmit(e: Event) {
    e.preventDefault();
    error = '';
    loading = true;

    const result = await auth.loginBasic(username, password);
    loading = false;

    if (result.success) {
      onSuccess?.();
    } else {
      error = result.error || 'Login failed';
      onError?.(error);
    }
  }

  function togglePassword() {
    showPassword = !showPassword;
  }
</script>

<form onsubmit={handleSubmit} class="flex flex-col gap-4">
  {#if error}
    <div class="alert alert-error">
      <span>{error}</span>
    </div>
  {/if}

  <div class="form-control">
    <label class="label" for="username">
      <span class="label-text">Email or Username</span>
    </label>
    <input
      id="username"
      type="text"
      class="input input-bordered w-full"
      bind:value={username}
      disabled={loading}
      required
      autocomplete="username"
    />
  </div>

  <div class="form-control">
    <label class="label" for="password">
      <span class="label-text">Password</span>
    </label>
    <div class="relative">
      <input
        id="password"
        type={showPassword ? 'text' : 'password'}
        class="input input-bordered w-full pr-12"
        bind:value={password}
        disabled={loading}
        required
        autocomplete="current-password"
      />
      <button
        type="button"
        class="btn btn-ghost btn-sm absolute right-1 top-1/2 -translate-y-1/2"
        onclick={togglePassword}
        tabindex="-1"
        aria-label={showPassword ? 'Hide password' : 'Show password'}
      >
        {#if showPassword}
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.542 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
          </svg>
        {:else}
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
          </svg>
        {/if}
      </button>
    </div>
    {#if showForgotPassword}
      <label class="label">
        <a href={forgotPasswordHref} class="label-text-alt link link-hover">
          Forgot password?
        </a>
      </label>
    {/if}
  </div>

  <button type="submit" class="btn btn-primary w-full" disabled={loading}>
    {#if loading}
      <span class="loading loading-spinner loading-sm"></span>
    {/if}
    Sign In
  </button>
</form>
