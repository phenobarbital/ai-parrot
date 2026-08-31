<!--
  AgentForm (TASK-2587, FEAT-475) — owns one `AgentFormState`, renders the
  six-tab wizard + sticky footer, and drives Save/Cancel + the
  unsaved-changes guard. Create and edit share this component; `mode`
  drives defaults vs. `load()`, PUT vs. POST, full payload vs. diff (spec
  §7 "Create/edit share one component").

  All state lives in `AgentFormState`, not component-local `$state` — so
  every tab's fields stay validated (`tabErrors`) even while a different
  tab panel is the one actually mounted-visible (spec §7 "Tabs must keep
  all panels' state mounted"). (The local class instance is named
  `formState`, not `state` — Svelte 5 treats a local binding literally
  named `state` as ambiguous with the `$state` rune.)
-->
<script lang="ts">
  import { untrack } from "svelte";

  import { createAgent, updateAgent } from "$lib/api/agents";
  import { ApiError } from "$lib/api/http";
  import type { TabId } from "$lib/agents/fields";
  import { config } from "$lib/config";
  import { router } from "$lib/router.svelte";
  import { AgentFormState } from "$lib/stores/agent-form.svelte";
  import type { AdminCatalog } from "$lib/types/generated/AdminCatalog";
  import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";
  import type { ToolInfo } from "$lib/types/generated/ToolsListResponse";
  import { Badge } from "$lib/ui/internal/shadcn/ui/badge/index.js";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
  } from "$lib/ui/internal/shadcn/ui/dialog/index.js";
  import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
  } from "$lib/ui/internal/shadcn/ui/tabs/index.js";

  import FormFooter from "./form/FormFooter.svelte";
  import TabsAdvanced from "./form/TabsAdvanced.svelte";
  import TabsAI from "./form/TabsAI.svelte";
  import TabsBehavior from "./form/TabsBehavior.svelte";
  import TabsCapabilities from "./form/TabsCapabilities.svelte";
  import TabsDataMemory from "./form/TabsDataMemory.svelte";
  import TabsGeneral from "./form/TabsGeneral.svelte";

  let {
    mode,
    agent = null,
    catalog,
    tools,
  }: {
    mode: "create" | "edit";
    agent?: BotAgentItem | null;
    catalog: AdminCatalog;
    tools: Record<string, ToolInfo>;
  } = $props();

  const formState = new AgentFormState();
  // One-time initialization from props, deliberately not reactive: the
  // caller (AgentFormPage) wraps this component in `{#key name}`, which
  // already forces a full remount (a fresh `formState`) whenever the
  // target agent changes — `untrack` documents that this read is
  // intentionally not meant to re-run `load()` on a later `agent` write.
  untrack(() => {
    if (mode === "edit" && agent) {
      formState.load(agent);
    }
  });

  let activeTab = $state<TabId>("general");
  let renameNotice = $state<string | null>(null);
  let confirmNavigateOpen = $state(false);
  let pendingNavigateResolve: ((allowed: boolean) => void) | null = null;

  // Keep `formState.errors`/`tabErrors` live as the user types, so Save is
  // disabled and the per-tab badge appears immediately, not only after a
  // submit attempt.
  $effect(() => {
    formState.validate();
  });

  const canSave = $derived(!formState.saving && Object.keys(formState.errors).length === 0);

  const TABS: { id: TabId; label: string }[] = [
    { id: "general", label: "General" },
    { id: "behavior", label: "Behavior" },
    { id: "ai", label: "AI" },
    { id: "capabilities", label: "Capabilities" },
    { id: "data_memory", label: "Data & Memory" },
    { id: "advanced", label: "Advanced" },
  ];

  function cancel(): void {
    router.navigate("/admin/agents");
  }

  async function save(): Promise<void> {
    if (!formState.validate()) return;
    formState.saving = true;
    formState.serverError = null;
    try {
      if (mode === "create") {
        const response = await createAgent(formState.payload());
        if (formState.values.name && response.name !== formState.values.name) {
          renameNotice = `Saved as "${response.name}" (adjusted from "${formState.values.name}").`;
        }
        router.navigate(`/admin/agents/${encodeURIComponent(response.name)}`, {
          replace: true,
        });
      } else {
        const name = formState.values.name;
        if (!name) return;
        await updateAgent(name, formState.diff());
        // Reset the baseline to what was just saved so `dirty` clears and
        // the next diff() is relative to the persisted state.
        formState.original = { ...formState.values };
      }
    } catch (err) {
      formState.serverError = err instanceof ApiError ? err.message : "Failed to save agent";
    } finally {
      formState.saving = false;
    }
  }

  /**
   * Unsaved-changes guard consulted by `router.navigate()` (TASK-2585).
   * Bypassed for the forced login redirect (`config.loginPath`) so a 401
   * is never stuck behind a confirm dialog.
   */
  function beforeNavigate(to: string): boolean | Promise<boolean> {
    if (!formState.dirty) return true;
    if (to.startsWith(config.loginPath)) return true;
    return new Promise<boolean>((resolve) => {
      pendingNavigateResolve = resolve;
      confirmNavigateOpen = true;
    });
  }

  function confirmDiscard(): void {
    confirmNavigateOpen = false;
    pendingNavigateResolve?.(true);
    pendingNavigateResolve = null;
  }

  function cancelDiscard(): void {
    confirmNavigateOpen = false;
    pendingNavigateResolve?.(false);
    pendingNavigateResolve = null;
  }

  function handleBeforeUnload(e: BeforeUnloadEvent): void {
    if (formState.dirty) {
      e.preventDefault();
      e.returnValue = "";
    }
  }

  $effect(() => {
    router.beforeNavigate = beforeNavigate;
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      router.beforeNavigate = null;
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  });
</script>

<div class="flex flex-col gap-4 pb-4" data-testid="agent-form">
  {#if renameNotice}
    <div class="bg-accent text-accent-foreground rounded-md p-3 text-sm" data-testid="rename-notice">
      {renameNotice}
    </div>
  {/if}

  <Tabs bind:value={activeTab}>
    <TabsList>
      {#each TABS as tab (tab.id)}
        <TabsTrigger value={tab.id} data-testid={`tab-trigger-${tab.id}`}>
          {tab.label}
          {#if (formState.tabErrors[tab.id] ?? 0) > 0}
            <Badge variant="destructive" data-testid={`tab-badge-${tab.id}`}>
              {formState.tabErrors[tab.id]}
            </Badge>
          {/if}
        </TabsTrigger>
      {/each}
    </TabsList>

    <TabsContent value="general"><TabsGeneral state={formState} /></TabsContent>
    <TabsContent value="behavior"><TabsBehavior state={formState} /></TabsContent>
    <TabsContent value="ai"><TabsAI state={formState} {catalog} /></TabsContent>
    <TabsContent value="capabilities">
      <TabsCapabilities state={formState} {catalog} {tools} />
    </TabsContent>
    <TabsContent value="data_memory"><TabsDataMemory state={formState} {catalog} /></TabsContent>
    <TabsContent value="advanced"><TabsAdvanced state={formState} /></TabsContent>
  </Tabs>
</div>

<FormFooter
  dirty={formState.dirty}
  saving={formState.saving}
  {canSave}
  serverError={formState.serverError}
  onsave={save}
  oncancel={cancel}
/>

<Dialog bind:open={confirmNavigateOpen}>
  <DialogContent data-testid="unsaved-changes-dialog">
    <DialogHeader>
      <DialogTitle>Discard unsaved changes?</DialogTitle>
      <DialogDescription>
        You have unsaved changes to this agent. Leaving now will discard them.
      </DialogDescription>
    </DialogHeader>
    <DialogFooter>
      <Button type="button" variant="outline" onclick={cancelDiscard} data-testid="unsaved-changes-stay">
        Stay
      </Button>
      <Button
        type="button"
        variant="destructive"
        onclick={confirmDiscard}
        data-testid="unsaved-changes-discard"
      >
        Discard
      </Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
