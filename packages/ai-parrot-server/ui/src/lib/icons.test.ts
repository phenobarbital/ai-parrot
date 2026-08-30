import { it, expect, vi } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { REGISTERED_PREFIXES, registerOfflineIcons } from "./icons";

function* walk(d: string): Generator<string> {
  for (const f of readdirSync(d)) {
    const p = join(d, f);
    statSync(p).isDirectory() ? (yield* walk(p)) : p.endsWith(".svelte") && (yield p);
  }
}

it("every icon prefix is bundled", () => {
  const used = new Set<string>();
  for (const f of walk("src")) {
    for (const m of readFileSync(f, "utf8").matchAll(/icon=["']([a-z0-9-]+):/g)) {
      used.add(m[1]);
    }
  }
  for (const p of used) expect(REGISTERED_PREFIXES, `prefix ${p}`).toContain(p);
});

it("registers the bundled collections without ever calling the Iconify API", () => {
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  registerOfflineIcons();
  const iconifyCalls = fetchSpy.mock.calls.filter((args) =>
    String(args[0]).includes("api.iconify.design"),
  );
  expect(iconifyCalls).toHaveLength(0);
  fetchSpy.mockRestore();
});
