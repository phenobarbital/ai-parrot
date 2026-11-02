<!-- Account › Link channel (FEAT-777 M5, D2). Preview on load; write only on explicit Confirm. -->
<script lang="ts">
  import { onMount } from "svelte";
  import { ApiError } from "$lib/api/http";
  import { confirmChannelLink, previewChannelLink } from "$lib/api/connections";
  import { router } from "$lib/router.svelte";
  import type { ChannelLinkPreview } from "$lib/types/generated/ChannelLinkPreview";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
  } from "$lib/ui/internal/shadcn/ui/card/index.js";

  let token = $state("");
  let preview = $state<ChannelLinkPreview | null>(null);
  let state = $state<"loading" | "ready" | "confirming" | "linked" | "conflict" | "expired" | "error">("loading");

  function classify(err: unknown): "conflict" | "expired" | "error" {
    const status = err instanceof ApiError ? err.status : undefined;
    return status === 409 ? "conflict" : status === 410 ? "expired" : "error";
  }

  onMount(async () => {
    token = new URLSearchParams(window.location.search).get("token") ?? "";
    if (!token) {
      state = "expired";
      return;
    }
    try {
      preview = await previewChannelLink(token);
      state = "ready";
    } catch (err: unknown) {
      state = classify(err);
    }
  });

  async function confirm(): Promise<void> {
    if (state !== "ready") return;
    state = "confirming";
    try {
      await confirmChannelLink(token);
      state = "linked";
    } catch (err: unknown) {
      state = classify(err);
    }
  }

  function cancel(): void {
    router.navigate("/account/connections");
  }

  function errorCopy(): string {
    if (state === "conflict") return "This Slack account is already linked to another Navigator account. Please contact an administrator.";
    if (state === "expired") return "This link has expired. Run /login in Slack again to create a new link.";
    return "We couldn't load this link. Please try again or contact an administrator.";
  }
</script>

<div class="flex max-w-2xl flex-col gap-6">
  <Card>
    <CardHeader>
      <CardTitle>Link Slack account</CardTitle>
      <CardDescription>Review the Slack identity before linking it to your Navigator account.</CardDescription>
    </CardHeader>
    <CardContent class="flex flex-col gap-4">
      {#if state === "loading"}
        <p class="text-muted-foreground text-sm" data-testid="link-loading">Loading link preview…</p>
      {:else if state === "ready" && preview}
        <dl class="grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt class="font-medium">Slack team ID</dt>
            <dd data-testid="slack-team-id">{preview.team_id}</dd>
          </div>
          <div>
            <dt class="font-medium">Slack user ID</dt>
            <dd data-testid="slack-user-id">{preview.channel_user_id}</dd>
          </div>
          <div>
            <dt class="font-medium">Navigator account</dt>
            <dd data-testid="navigator-user-id">{preview.nav_user_id}</dd>
          </div>
        </dl>
        <p>This Slack account will be able to use your connections.</p>
        <div class="flex gap-2">
          <Button onclick={confirm} disabled={state !== "ready"}>Confirm</Button>
          <Button variant="outline" onclick={cancel} disabled={state !== "ready"}>Cancel</Button>
        </div>
      {:else if state === "confirming"}
        <p aria-live="polite">Linking your Slack account…</p>
        <div class="flex gap-2">
          <Button disabled>Confirm</Button>
          <Button variant="outline" disabled>Cancel</Button>
        </div>
      {:else if state === "linked"}
        <p role="status">Your Slack account is linked to your Navigator account.</p>
        <Button onclick={cancel}>Continue</Button>
      {:else}
        <p class="text-destructive text-sm" role="alert">{errorCopy()}</p>
        <Button variant="outline" onclick={cancel}>Back to connections</Button>
      {/if}
    </CardContent>
  </Card>
</div>
