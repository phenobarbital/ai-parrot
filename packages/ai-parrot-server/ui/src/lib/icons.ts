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
 * enumerated by grepping the vendored tree's `icon="prefix:…"` usages at
 * port time; TASK-2593 is the source of truth for the final list as more
 * of the tree lands.
 */
import { addCollection } from "@iconify/svelte";
import { icons as mdiIcons } from "@iconify-json/mdi";
import { icons as phIcons } from "@iconify-json/ph";
import { icons as svgSpinnersIcons } from "@iconify-json/svg-spinners";
import { icons as tablerIcons } from "@iconify-json/tabler";

export function registerOfflineIcons(): void {
  addCollection(mdiIcons);
  addCollection(phIcons);
  addCollection(svgSpinnersIcons);
  addCollection(tablerIcons);
}

registerOfflineIcons();
