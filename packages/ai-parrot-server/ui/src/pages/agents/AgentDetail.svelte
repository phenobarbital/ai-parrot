<!--
  AgentDetail (TASK-2530) — read-only detail panel for a single
  `BotAgentItem`. Built on the vendored bits-ui-backed Dialog primitive
  (Codebase Contract: "dialog or side sheet from vendored primitives").
  Renders every field the payload happens to carry (labeled) plus a raw
  JSON view — deliberately generic since `BotAgentItem` only pins down
  `name`/`source` (registry agents without `bot_config` carry a much
  smaller field set; database agents carry the full BotModel dump).

  NO mutating affordances — read-only by design (next spec owns CRUD).
-->
<script lang="ts">
  import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";
  import { Badge } from "$lib/ui/internal/shadcn/ui/badge/index.js";
  import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
  } from "$lib/ui/internal/shadcn/ui/dialog/index.js";
  import { Separator } from "$lib/ui/internal/shadcn/ui/separator/index.js";

  let {
    agent = null,
    open = $bindable(false),
  }: {
    agent: BotAgentItem | null;
    open?: boolean;
  } = $props();

  /** Every field except `name`/`source`, which the header already shows. */
  const entries = $derived(
    agent ? Object.entries(agent).filter(([key]) => key !== "name" && key !== "source") : [],
  );

  function formatValue(value: unknown): string {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }
</script>

<Dialog bind:open>
  <DialogContent class="max-h-[85vh] overflow-y-auto sm:max-w-2xl" data-testid="agent-detail-dialog">
    {#if agent}
      <DialogHeader>
        <DialogTitle>{agent.name}</DialogTitle>
        <DialogDescription>
          <Badge variant={agent.source === "database" ? "default" : "secondary"}>
            {agent.source}
          </Badge>
        </DialogDescription>
      </DialogHeader>

      <div class="flex flex-col gap-2 text-sm">
        {#each entries as [key, value] (key)}
          <div class="flex items-start justify-between gap-4">
            <span class="text-muted-foreground font-medium">{key}</span>
            <span class="text-right break-all">{formatValue(value)}</span>
          </div>
        {/each}
        {#if entries.length === 0}
          <p class="text-muted-foreground">No additional fields.</p>
        {/if}
      </div>

      <Separator />

      <div>
        <p class="text-muted-foreground mb-1 text-xs font-medium tracking-wide uppercase">
          Raw JSON
        </p>
        <pre
          class="bg-muted overflow-x-auto rounded-md p-3 text-xs"
          data-testid="agent-detail-raw-json">{JSON.stringify(agent, null, 2)}</pre>
      </div>
    {/if}
  </DialogContent>
</Dialog>
