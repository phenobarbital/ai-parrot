/**
 * Offline icon registration for `@iconify/svelte` (FEAT-476 spec §2
 * "Icons"). The vendored AgentChat tree renders icons via `@iconify/
 * svelte`'s `<Icon icon="prefix:name" />`, which by default resolves
 * unregistered icons from the public Iconify API
 * (`api.iconify.design`) — unacceptable for an air-gapped adopter.
 *
 * Instead, every icon collection actually used by the vendored tree is
 * bundled as a dependency (`@iconify-json/<prefix>`) and registered here
 * via `addCollection()` *before* the app mounts (imported once from
 * `main.ts`). As long as every icon name used resolves to a locally
 * registered prefix, `@iconify/svelte` never falls back to the network
 * API — there is no separate `disableCache`/offline toggle to flip in
 * `@iconify/svelte` v5 (verified: not exported by `dist/index.d.ts`).
 *
 * The prefix list below (`mdi`, `ph`, `svg-spinners`, `tabler`) was
 * enumerated by grepping `icon="prefix:…"` usages across the full
 * navigator AgentChat closure (components/agents, charts,
 * visualizations, ui/components) at TASK-2593 (finalized; TASK-2591
 * provisioned the same four as a placeholder). `icons.test.ts` guards
 * against any future vendored file using an unregistered prefix.
 */
import { addCollection } from "@iconify/svelte";
import { icons as mdiIcons } from "@iconify-json/mdi";
import { icons as phIcons } from "@iconify-json/ph";
import { icons as svgSpinnersIcons } from "@iconify-json/svg-spinners";
import { icons as tablerIcons } from "@iconify-json/tabler";

/** Every icon-set prefix bundled and registered offline — source of truth
 * for `icons.test.ts`'s unregistered-prefix guard. */
export const REGISTERED_PREFIXES = ["mdi", "ph", "svg-spinners", "tabler"] as const;

export function registerOfflineIcons(): void {
  addCollection(mdiIcons);
  addCollection(phIcons);
  addCollection(svgSpinnersIcons);
  addCollection(tablerIcons);
}

registerOfflineIcons();
