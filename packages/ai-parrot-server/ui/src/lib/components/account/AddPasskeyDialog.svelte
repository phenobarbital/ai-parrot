<script lang="ts">
  import { fetchRegisterOptions, passkeyErrorMessage, verifyRegistration } from "$lib/api/passkey";
  import { ApiError } from "$lib/api/http";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import * as Dialog from "$lib/ui/internal/shadcn/ui/dialog/index.js";
  import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
  import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";
  import { credentialToJSON, isUserCancelled, isWebAuthnSupported, toCreationOptions } from "$lib/webauthn";

  interface Props {
    open: boolean;
    onClose: () => void;
    onRegistered: () => void;
  }

  let { open, onClose, onRegistered }: Props = $props();

  let step = $state<"ceremony" | "label">("ceremony");
  let label = $state("");
  let error = $state("");
  let credential = $state<ReturnType<typeof credentialToJSON> | null>(null);

  const ORIGIN_HINT =
    "This site is not configured for passkeys — ask your administrator to add its origin to PASSKEY_RELYING_PARTIES.";

  async function start(): Promise<void> {
    if (!isWebAuthnSupported()) {
      error = "Your browser does not support passkeys.";
      return;
    }

    try {
      const json = await fetchRegisterOptions();
      const created = await navigator.credentials.create({ publicKey: toCreationOptions(json) });
      if (!created) {
        error = "Passkey request failed";
        return;
      }
      credential = credentialToJSON(created as PublicKeyCredential);
      step = "label";
    } catch (err) {
      if (isUserCancelled(err)) {
        onClose();
        return;
      }
      error = err instanceof ApiError && err.status !== undefined && err.status >= 400 && err.status < 500
        ? ORIGIN_HINT
        : passkeyErrorMessage(err);
    }
  }

  async function finish(): Promise<void> {
    if (!credential) return;

    try {
      await verifyRegistration(credential, label.trim() || undefined);
      onRegistered();
      onClose();
    } catch (err) {
      error = err instanceof ApiError && err.status === 409
        ? "This device is already registered."
        : passkeyErrorMessage(err);
    }
  }

  $effect(() => {
    if (open) {
      step = "ceremony";
      label = "";
      error = "";
      credential = null;
      void start();
    }
  });
</script>

<Dialog.Root {open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
  <Dialog.Content>
    <Dialog.Header>
      <Dialog.Title>Add a passkey</Dialog.Title>
      <Dialog.Description>
        {#if step === "ceremony"}
          Follow your browser's prompt to create a passkey.
        {:else}
          Give this passkey a name so you can recognize it later.
        {/if}
      </Dialog.Description>
    </Dialog.Header>

    {#if error}
      <p class="text-destructive text-sm" role="alert">{error}</p>
    {/if}

    {#if step === "label"}
      <div class="flex flex-col gap-2">
        <Label for="passkey-label">Name (optional)</Label>
        <Input id="passkey-label" maxlength={128} bind:value={label} placeholder="e.g. Work laptop" />
      </div>
      <Dialog.Footer>
        <Button variant="outline" onclick={onClose}>Cancel</Button>
        <Button data-testid="passkey-save" onclick={finish}>Save</Button>
      </Dialog.Footer>
    {/if}
  </Dialog.Content>
</Dialog.Root>
