// src/lib/stores/client.svelte.ts

// ai-parrot: trimmed to the single accessor `AgentChat.svelte` actually
// uses — `clientStore.getClient()?.slug` (tenantId for the avatar/voice
// pipeline, FEAT-169). Navigator's full client/program/module/submodule
// navigation hierarchy (`Client`, `Program`, `Module`, `Submodule`,
// `NavigationContext` from `$lib/types`, backed by `$lib/data/
// manual-data`) is a multi-tenant content-registry concept with no
// equivalent in ai-parrot's Admin UI, and both `$lib/types` (only
// re-exporting the dropped `hierarchy`/`agentsflow`/`scraping` type
// modules) and `$lib/data/manual-data` are on the Module 3 drop list
// (spec §3 Module 3 / §6 "Does NOT Exist"). `getClient()` always returns
// `null` here, so `tenantId` degrades to `undefined` — the avatar
// pipeline works without a tenant identifier (spec §7 "Known Risks":
// backend gaps degrade gracefully in the UI).

export interface ClientSlug {
  slug: string;
}

function createClientStore() {
  return {
    getClient: (): ClientSlug | null => null,
  };
}

export const clientStore = createClientStore();
export type ClientStore = ReturnType<typeof createClientStore>;
