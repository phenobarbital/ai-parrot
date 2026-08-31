/**
 * Shim for SvelteKit's `$app/navigation` module.
 *
 * Resolved via `vite.config.ts`'s `resolve.alias` (FEAT-476 spec §2
 * "Shims") so the vendored navigator tree's `import { goto } from
 * "$app/navigation"` sites keep working verbatim against the Admin UI's
 * own hand-rolled router (`$lib/router.svelte`) instead of SvelteKit's
 * client-side router.
 *
 * ai-parrot: navigator's `goto` accepts a `replaceState` option;
 * `router.navigate` accepts `replace` — this shim maps one to the other.
 */
import { router } from "$lib/router.svelte";

export async function goto(
  path: string,
  opts?: { replaceState?: boolean },
): Promise<void> {
  router.navigate(path, { replace: opts?.replaceState ?? false });
}
