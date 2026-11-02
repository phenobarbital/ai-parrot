<!-- Account › Security (FEAT-772, spec §3 Module 5). Route /account/security (registered by the nav task). -->
<script lang="ts">
  import { onMount } from "svelte";

  import { ApiError } from "$lib/api/http";
  import {
    deletePasskey,
    listPasskeys,
    passkeyErrorMessage,
    renamePasskey,
    type PasskeyCredentialSummary,
  } from "$lib/api/passkey";
  import AddPasskeyDialog from "$lib/components/account/AddPasskeyDialog.svelte";
  import PasskeyList from "$lib/components/account/PasskeyList.svelte";
  import { authStore } from "$lib/stores/auth.svelte";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "$lib/ui/internal/shadcn/ui/card/index.js";

  const LAST_METHOD = "You can't delete your only way to sign in. Set a password or add another passkey first.";

  let items = $state<PasskeyCredentialSummary[]>([]);
  let loading = $state(true);
  let error = $state("");
  let adding = $state(false);

  async function refresh(): Promise<void> {
    loading = true;
    try {
      items = await listPasskeys();
      error = "";
    } catch (err) {
      error = passkeyErrorMessage(err);
    } finally {
      loading = false;
    }
  }

  async function handleRename(id: string, label: string): Promise<void> {
    let mutationError = "";
    try {
      await renamePasskey(id, label);
    } catch (err) {
      mutationError = passkeyErrorMessage(err);
    }
    await refresh();
    if (mutationError) error = mutationError;
  }

  async function handleDelete(id: string): Promise<void> {
    let mutationError = "";
    try {
      await deletePasskey(id);
    } catch (err) {
      mutationError = err instanceof ApiError && err.status === 409 ? LAST_METHOD : passkeyErrorMessage(err);
    }
    await refresh();
    if (mutationError) error = mutationError;
  }

  onMount(refresh);
</script>

<div class="flex max-w-3xl flex-col gap-6">
  <Card>
    <CardHeader>
      <CardTitle>Session</CardTitle>
      <CardDescription>Your current sign-in method.</CardDescription>
    </CardHeader>
    <CardContent>
      <p data-testid="session-method">
        {authStore.authMethod === "passkey" ? "Signed in with a passkey" : "Signed in with a password"}
      </p>
    </CardContent>
  </Card>

  <Card>
    <CardHeader class="flex flex-row items-start justify-between gap-4">
      <div class="flex flex-col gap-1.5">
        <CardTitle>Passkeys</CardTitle>
        <CardDescription>Passkeys let you sign in securely using your device instead of a password.</CardDescription>
      </div>
      <Button data-testid="passkey-add" onclick={() => (adding = true)}>Add a passkey</Button>
    </CardHeader>
    <CardContent class="flex flex-col gap-4">
      {#if error}
        <p class="text-destructive text-sm" role="alert">{error}</p>
      {/if}
      {#if !loading && items.length === 0}
        <p class="text-muted-foreground text-sm" data-testid="passkey-empty">
          You have no passkeys yet. Add one to sign in securely without a password.
        </p>
      {/if}
      <PasskeyList {items} {loading} onRename={handleRename} onDelete={handleDelete} />
    </CardContent>
  </Card>
</div>

<AddPasskeyDialog open={adding} onClose={() => (adding = false)} onRegistered={refresh} />
