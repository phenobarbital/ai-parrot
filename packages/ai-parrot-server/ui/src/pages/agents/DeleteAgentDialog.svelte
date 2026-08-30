<!--
  DeleteAgentDialog (TASK-2588, FEAT-475) — typed-name confirmation before
  DELETE /api/v1/bots/{name}. Database agents only (never rendered for a
  registry row from AgentsList, but the 403 a repo registry agent returns
  server-side — e.g. a row that was database-backed a moment ago and
  isn't anymore — is still surfaced verbatim, not swallowed).
-->
<script lang="ts">
  import { deleteAgent } from "$lib/api/agents";
  import { ApiError } from "$lib/api/http";
  import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
  } from "$lib/ui/internal/shadcn/ui/dialog/index.js";
  import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
  import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";

  let {
    agent,
    open = $bindable(false),
    ondeleted,
  }: {
    agent: BotAgentItem | null;
    open?: boolean;
    ondeleted?: () => void;
  } = $props();

  let typedName = $state("");
  let deleting = $state(false);
  let error = $state<string | null>(null);

  const canDelete = $derived(!!agent && typedName === agent.name && !deleting);

  // Reset local state whenever the dialog opens for a (possibly
  // different) agent, so a stale confirmation/error never leaks in.
  $effect(() => {
    if (open) {
      typedName = "";
      error = null;
    }
  });

  async function confirmDelete(): Promise<void> {
    if (!agent || typedName !== agent.name) return;
    deleting = true;
    error = null;
    try {
      await deleteAgent(agent.name);
      open = false;
      ondeleted?.();
    } catch (err) {
      error = err instanceof ApiError ? err.message : "Failed to delete agent";
    } finally {
      deleting = false;
    }
  }
</script>

<Dialog bind:open>
  <DialogContent data-testid="delete-agent-dialog">
    {#if agent}
      <DialogHeader>
        <DialogTitle>Delete "{agent.name}"?</DialogTitle>
        <DialogDescription>
          This permanently deletes the agent. Type <strong>{agent.name}</strong> to confirm.
        </DialogDescription>
      </DialogHeader>

      <div class="flex flex-col gap-1.5">
        <Label for="delete-confirm-name">Agent name</Label>
        <Input
          id="delete-confirm-name"
          value={typedName}
          oninput={(e) => (typedName = e.currentTarget.value)}
          data-testid="delete-agent-confirm-input"
        />
      </div>

      {#if error}
        <p class="text-destructive text-sm" data-testid="delete-agent-error">{error}</p>
      {/if}

      <DialogFooter>
        <Button
          type="button"
          variant="outline"
          onclick={() => (open = false)}
          disabled={deleting}
          data-testid="delete-agent-cancel"
        >
          Cancel
        </Button>
        <Button
          type="button"
          variant="destructive"
          disabled={!canDelete}
          onclick={confirmDelete}
          data-testid="delete-agent-confirm"
        >
          {deleting ? "Deleting…" : "Delete"}
        </Button>
      </DialogFooter>
    {/if}
  </DialogContent>
</Dialog>
