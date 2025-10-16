<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { browser } from '$app/environment';
  import { LoadingSpinner } from '$lib/components';
  import { o365 } from '$lib/api';
  import type { RemoteAuthSession, RemoteAuthSummary } from '$lib/api/o365/auth';

  let sessionId = $state('');
  let status = $state('initializing');
  let loading = $state(true);
  let polling = $state(false);
  let errorMessage = $state('');
  let authUrl = $state('');
  let deviceFlow = $state<RemoteAuthSession['device_flow'] | null>(null);
  let resultInfo = $state<RemoteAuthSummary | null>(null);
  let expiresAt = $state('');
  let pollHandle: ReturnType<typeof setInterval> | undefined;

  const statusLabel = $derived(() => {
    switch (status) {
      case 'authorized':
        return 'Authorized';
      case 'failed':
        return 'Failed';
      case 'cancelled':
        return 'Cancelled';
      case 'expired':
        return 'Expired';
      case 'pending':
        return 'Pending';
      default:
        return 'Starting';
    }
  });

  const statusBadgeClass = $derived(() => {
    switch (status) {
      case 'authorized':
        return 'badge badge-success badge-lg';
      case 'failed':
      case 'cancelled':
      case 'expired':
        return 'badge badge-error badge-lg';
      case 'pending':
        return 'badge badge-warning badge-lg';
      default:
        return 'badge badge-info badge-lg';
    }
  });

  const formattedExpiry = $derived(() => {
    if (!expiresAt) return '';
    const date = new Date(expiresAt);
    if (Number.isNaN(date.getTime())) return expiresAt;
    return date.toLocaleString();
  });

  function parseError(error: unknown): string {
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
      return error.response.data.message;
    }

    if (error instanceof Error && typeof error.message === 'string') {
      return error.message;
    }

    return 'An unexpected error occurred while processing the request.';
  }

  function stopPolling() {
    if (pollHandle) {
      clearInterval(pollHandle);
      pollHandle = undefined;
    }
    polling = false;
  }

  async function pollStatus() {
    if (!browser || !sessionId) return;

    try {
      const session = await o365.getSessionStatus(sessionId);
      status = session.status ?? status;
      if (session.auth_url && !authUrl) {
        authUrl = session.auth_url;
      }
      if (session.device_flow) {
        deviceFlow = session.device_flow;
      }
      if (session.result) {
        resultInfo = session.result;
      }
      if (session.expires_at) {
        expiresAt = session.expires_at;
      }
      if (session.error) {
        errorMessage = session.error;
      }

      if (['authorized', 'failed', 'cancelled', 'expired'].includes(status)) {
        stopPolling();
      }
    } catch (error) {
      errorMessage = parseError(error);
      stopPolling();
    }
  }

  function startPolling() {
    if (!browser || !sessionId || polling) return;
    polling = true;
    pollStatus();
    pollHandle = setInterval(pollStatus, 4000);
  }

  async function startAuthorization() {
    if (!browser) return;

    stopPolling();
    loading = true;
    errorMessage = '';
    authUrl = '';
    deviceFlow = null;
    resultInfo = null;
    expiresAt = '';
    status = 'initializing';

    try {
      const session = await o365.startInteractiveSession();
      sessionId = session.session_id;
      status = session.status ?? 'pending';
      authUrl = session.auth_url ?? '';
      deviceFlow = session.device_flow ?? null;
      resultInfo = session.result ?? null;
      expiresAt = session.expires_at ?? '';
      loading = false;
      if (session.error) {
        errorMessage = session.error;
      }
      if (sessionId) {
        startPolling();
      }
    } catch (error) {
      errorMessage = parseError(error);
      status = 'failed';
      loading = false;
    }
  }

  async function cancelAuthorization() {
    if (!browser || !sessionId) return;
    try {
      await o365.cancelSession(sessionId);
      stopPolling();
      status = 'cancelled';
    } catch (error) {
      errorMessage = parseError(error);
    }
  }

  function handleRestart() {
    startAuthorization();
  }

  onMount(() => {
    if (!browser) {
      return;
    }
    startAuthorization();
  });

  onDestroy(() => {
    stopPolling();
  });
</script>

<svelte:head>
  <title>Office 365 Authorization - Crew Builder</title>
</svelte:head>

<div class="min-h-screen bg-base-200 py-10">
  <div class="mx-auto max-w-4xl px-4">
    <div class="mb-6">
      <h1 class="text-3xl font-bold">Authorize Office 365 Tools</h1>
      <p class="text-base-content/70">
        Complete the Microsoft 365 authentication flow to enable delegated access for Parrot tools.
      </p>
    </div>

    <div class="card bg-base-100 shadow-xl">
      <div class="card-body space-y-6">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 class="card-title">Interactive Login Session</h2>
            <p class="text-sm text-base-content/70">
              Follow the steps below to sign in with your Microsoft account. Tokens are stored securely on the server.
            </p>
          </div>
          <span class={statusBadgeClass}>{statusLabel}</span>
        </div>

        {#if loading && status === 'initializing'}
          <LoadingSpinner text="Preparing interactive login..." />
        {:else}
          {#if errorMessage}
            <div class="alert alert-error shadow">
              <span>{errorMessage}</span>
            </div>
          {/if}

          {#if status === 'authorized'}
            <div class="alert alert-success">
              <span>
                Authorization complete. {resultInfo?.user?.name || resultInfo?.user?.preferred_username || 'Microsoft account'}
                is now connected.
              </span>
            </div>
          {/if}

          {#if authUrl}
            <div class="space-y-3 rounded-lg border border-base-300 bg-base-200/50 p-4">
              <h3 class="text-lg font-semibold">Sign in with your browser</h3>
              <p class="text-sm text-base-content/70">
                Click the button below to open the Microsoft sign-in window. Complete the login and return to this page.
              </p>
              <a class="btn btn-primary w-full sm:w-auto" href={authUrl} target="_blank" rel="noopener noreferrer">
                Open Microsoft Login
              </a>
              <div class="text-xs text-base-content/60">
                Session ID: <span class="font-mono">{sessionId}</span>
              </div>
              {#if formattedExpiry}
                <div class="text-xs text-base-content/60">Expires: {formattedExpiry}</div>
              {/if}
            </div>
          {/if}

          {#if deviceFlow}
            <div class="space-y-3 rounded-lg border border-dashed border-base-300 bg-base-200/40 p-4">
              <h3 class="text-lg font-semibold">Use device login</h3>
              <p class="text-sm text-base-content/70">Visit the verification URL and enter the code below:</p>
              <div class="flex flex-col gap-2 sm:flex-row sm:items-center">
                <code class="badge badge-accent badge-lg text-xl">{deviceFlow.user_code}</code>
                <a
                  class="link link-primary break-all"
                  href={deviceFlow.verification_uri_complete || deviceFlow.verification_uri}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {deviceFlow.verification_uri_complete || deviceFlow.verification_uri}
                </a>
              </div>
              {#if deviceFlow.message}
                <div class="rounded-md bg-base-100 p-3 text-sm text-base-content/70">
                  {#each deviceFlow.message.split('\n') as line (line)}
                    <div>{line}</div>
                  {/each}
                </div>
              {/if}
            </div>
          {/if}

          {#if !authUrl && !deviceFlow && status === 'pending'}
            <LoadingSpinner text="Waiting for Microsoft login URL..." />
          {/if}

          {#if resultInfo && status === 'authorized'}
            <div class="rounded-lg bg-success/10 p-4 text-sm">
              {#if resultInfo.user}
                <div><strong>User:</strong> {resultInfo.user.name || resultInfo.user.preferred_username}</div>
              {/if}
              {#if resultInfo.account?.username}
                <div><strong>Account:</strong> {resultInfo.account.username}</div>
              {/if}
              {#if resultInfo.scope}
                <div><strong>Granted scopes:</strong> {resultInfo.scope}</div>
              {/if}
            </div>
          {/if}

          <div class="divider"></div>

          <div class="flex flex-wrap gap-3">
            <button class="btn btn-primary" onclick={handleRestart}>Restart authorization</button>
            {#if status === 'pending'}
              <button class="btn btn-outline" onclick={cancelAuthorization}>Cancel session</button>
            {/if}
          </div>
        {/if}
      </div>
    </div>
  </div>
</div>
