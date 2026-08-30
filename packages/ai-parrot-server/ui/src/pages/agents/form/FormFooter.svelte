<!--
  FormFooter (TASK-2587, FEAT-475) — sticky Save/Cancel bar shared by
  create and edit. Save is disabled while the form is invalid or a save
  request is in flight; server errors (ApiError.message, e.g. a 400/409
  from ChatbotHandler) render above the actions without discarding input.
-->
<script lang="ts">
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";

  let {
    dirty,
    saving,
    canSave,
    serverError,
    onsave,
    oncancel,
  }: {
    dirty: boolean;
    saving: boolean;
    canSave: boolean;
    serverError: string | null;
    onsave: () => void;
    oncancel: () => void;
  } = $props();
</script>

<div
  class="bg-background border-border sticky bottom-0 z-10 flex flex-col gap-2 border-t px-4 py-3"
  data-testid="form-footer"
>
  {#if serverError}
    <p class="text-destructive text-sm" data-testid="form-footer-server-error">
      {serverError}
    </p>
  {/if}
  <div class="flex items-center justify-between gap-3">
    <span class="text-muted-foreground text-xs" data-testid="form-footer-dirty">
      {dirty ? "Unsaved changes" : "No changes"}
    </span>
    <div class="flex gap-2">
      <Button
        type="button"
        variant="outline"
        onclick={oncancel}
        disabled={saving}
        data-testid="form-footer-cancel"
      >
        Cancel
      </Button>
      <Button
        type="button"
        onclick={onsave}
        disabled={!canSave || saving}
        data-testid="form-footer-save"
      >
        {saving ? "Saving…" : "Save"}
      </Button>
    </div>
  </div>
</div>
