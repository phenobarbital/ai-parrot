<script lang="ts">
  import type { PasskeyCredentialSummary } from "$lib/api/passkey";
  import { Badge } from "$lib/ui/internal/shadcn/ui/badge/index.js";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import * as Dialog from "$lib/ui/internal/shadcn/ui/dialog/index.js";
  import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
  import { Skeleton } from "$lib/ui/internal/shadcn/ui/skeleton/index.js";

  interface Props {
    items: PasskeyCredentialSummary[];
    loading: boolean;
    onRename: (id: string, label: string) => Promise<void>;
    onDelete: (id: string) => Promise<void>;
  }

  let { items, loading, onRename, onDelete }: Props = $props();

  let editingId = $state<string | null>(null);
  let draft = $state("");
  let confirmId = $state<string | null>(null);

  const deviceLabel = (type: string | null): string =>
    type === "multi_device" ? "Synced" : type === "single_device" ? "This device only" : "Unknown device";
  const when = (iso: string | null): string => (iso ? new Date(iso).toLocaleString() : "Never");

  function beginRename(item: PasskeyCredentialSummary): void {
    editingId = item.id;
    draft = item.label ?? "";
  }

  async function saveRename(): Promise<void> {
    const id = editingId;
    const label = draft.trim();
    if (id === null || label.length < 1 || label.length > 128) return;

    await onRename(id, label);
    editingId = null;
  }

  async function confirmDelete(): Promise<void> {
    const id = confirmId;
    if (id === null) return;

    try {
      await onDelete(id);
    } finally {
      confirmId = null;
    }
  }
</script>

<div class="flex flex-col gap-3" data-testid="passkey-list">
  {#if loading}
    <Skeleton class="h-12 w-full" />
    <Skeleton class="h-12 w-full" />
  {:else}
    {#each items as item (item.id)}
      <div class="border-border flex flex-col gap-3 rounded-md border p-4" data-testid="passkey-row">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="flex min-w-0 flex-col gap-1">
            {#if editingId === item.id}
              <div class="flex flex-wrap items-center gap-2">
                <Input
                  class="w-56"
                  aria-label="Passkey name"
                  maxlength={128}
                  bind:value={draft}
                />
                <Button size="sm" disabled={!draft.trim() || draft.trim().length > 128} onclick={saveRename}>
                  Save
                </Button>
                <Button size="sm" variant="outline" onclick={() => (editingId = null)}>Cancel</Button>
              </div>
            {:else}
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-medium">{item.label || "Unnamed passkey"}</span>
                <span class="text-muted-foreground text-sm">{deviceLabel(item.device_type)}</span>
                {#if item.backed_up}
                  <Badge variant="secondary">Synced</Badge>
                {/if}
              </div>
            {/if}
            <span class="text-muted-foreground text-sm">Relying party: {item.rp_id}</span>
            <span class="text-muted-foreground text-sm">Added {when(item.created_at)}</span>
            <span class="text-muted-foreground text-sm">Last used {when(item.last_used_at)}</span>
          </div>

          {#if editingId !== item.id}
            <div class="flex gap-2">
              <Button size="sm" variant="outline" onclick={() => beginRename(item)}>Rename</Button>
              <Button size="sm" variant="destructive" onclick={() => (confirmId = item.id)}>Delete</Button>
            </div>
          {/if}
        </div>
      </div>
    {/each}
  {/if}
</div>

<Dialog.Root open={confirmId !== null} onOpenChange={(open) => !open && (confirmId = null)}>
  <Dialog.Content>
    <Dialog.Header>
      <Dialog.Title>Delete this passkey?</Dialog.Title>
      <Dialog.Description>You will no longer be able to sign in with it.</Dialog.Description>
    </Dialog.Header>
    <Dialog.Footer>
      <Button variant="outline" onclick={() => (confirmId = null)}>Cancel</Button>
      <Button variant="destructive" data-testid="passkey-confirm-delete" onclick={confirmDelete}>Delete</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
