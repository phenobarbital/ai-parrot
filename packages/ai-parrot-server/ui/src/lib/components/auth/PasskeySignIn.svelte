<!--
  PasskeySignIn (FEAT-772, spec §3 Module 4) — passkey button + conditional UI.
  Renders NOTHING unless WebAuthn exists and POST login/options answers (one call
  per mount; that response doubles as the conditional-UI challenge). A click aborts
  the pending conditional request and fetches a fresh, username-scoped challenge.
-->
<script lang="ts">
  import { onDestroy, onMount, tick } from "svelte";

  import { fetchLoginOptions, type PasskeyLoginOptions } from "$lib/api/passkey";
  import { authStore } from "$lib/stores/auth.svelte";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import {
    credentialToJSON,
    isConditionalMediationAvailable,
    isUserCancelled,
    isWebAuthnSupported,
    toRequestOptions,
  } from "$lib/webauthn";

  interface Props {
    /** Current username field value (username-first when non-empty). */
    username: string;
    /** Called after a successful login; Login.svelte navigates to nextTarget(). */
    onSuccess: () => void;
    /** Disabled while the password form submits. */
    disabled?: boolean;
    /** Called once passkeys are confirmed available (before conditional UI starts). */
    onAvailable?: () => void;
  }

  let { username, onSuccess, disabled = false, onAvailable }: Props = $props();

  const FAILED = "Passkey sign-in failed. Use your password instead.";
  let available = $state(false);
  let busy = $state(false);
  let error = $state("");
  let pending: AbortController | null = null;

  async function runCeremony(started: PasskeyLoginOptions, mediation?: "conditional"): Promise<void> {
    const controller = new AbortController();
    pending = controller;

    try {
      const credential = await navigator.credentials.get({
        publicKey: toRequestOptions(started.publicKey),
        signal: controller.signal,
        ...(mediation ? { mediation } : {}),
      });
      if (!credential) return;

      const result = await authStore.loginWithPasskey(
        started.challenge_id,
        credentialToJSON(credential as PublicKeyCredential),
      );
      if (result.success) {
        onSuccess();
      } else {
        error = FAILED;
      }
    } catch (err: unknown) {
      if (!isUserCancelled(err)) {
        error = FAILED;
      }
    } finally {
      if (pending === controller) {
        pending = null;
        busy = false;
      }
    }
  }

  async function handleClick(): Promise<void> {
    error = "";
    pending?.abort();
    pending = null;
    busy = true;
    const started = await fetchLoginOptions(username.trim() || undefined);
    if (!started) {
      busy = false;
      error = FAILED;
      return;
    }
    await runCeremony(started);
    // Conditional UI is not re-armed after a modal attempt.
  }

  onMount(async () => {
    if (!isWebAuthnSupported()) return;
    const started = await fetchLoginOptions();
    if (!started) return;
    available = true;
    onAvailable?.();
    // Let the parent apply autocomplete="username webauthn" before conditional get().
    await tick();
    if (await isConditionalMediationAvailable()) void runCeremony(started, "conditional");
  });

  onDestroy(() => pending?.abort());
</script>

{#if available}
  <div class="flex flex-col gap-2">
    <Button
      type="button"
      variant="outline"
      class="w-full"
      data-testid="passkey-signin"
      disabled={disabled || busy}
      onclick={handleClick}
    >
      {busy ? "Waiting for passkey…" : "Sign in with a passkey"}
    </Button>
    {#if error}
      <div
        class="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        role="alert"
        data-testid="passkey-error"
      >
        {error}
      </div>
    {/if}
  </div>
{/if}
