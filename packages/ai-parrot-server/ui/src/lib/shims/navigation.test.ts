import { vi, it, expect } from "vitest";

vi.mock("$lib/router.svelte", () => ({ router: { navigate: vi.fn() } }));

import { router } from "$lib/router.svelte";
import { goto } from "./navigation";

it("delegates to router.navigate", async () => {
  await goto("/admin/agents/x/chat", { replaceState: true });
  expect(router.navigate).toHaveBeenCalledWith("/admin/agents/x/chat", { replace: true });
});

it("defaults replace to false when replaceState is omitted", async () => {
  await goto("/admin/agents/y/chat");
  expect(router.navigate).toHaveBeenCalledWith("/admin/agents/y/chat", { replace: false });
});
