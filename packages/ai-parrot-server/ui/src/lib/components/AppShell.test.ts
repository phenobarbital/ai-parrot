import { fireEvent, render } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import apiClient from "$lib/api/http";
import { navEntries } from "$lib/nav";
import { router } from "$lib/router.svelte";
import { authStore } from "$lib/stores/auth.svelte";

import AppShellHarness from "./AppShellHarness.test.svelte";

describe("AppShell", () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.pushState({}, "", "/admin/home");
    router.path = "/admin/home";
    authStore.token = "test-token";
    authStore.user = { username: "alice" };
    localStorage.setItem("ai_parrot_token", "test-token");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders every nav entry from the registry", () => {
    const { getByText } = render(AppShellHarness);
    for (const entry of navEntries) {
      expect(getByText(entry.label)).toBeTruthy();
    }
  });

  it("logout clears auth state and routes to login", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: {} });

    const { getByRole } = render(AppShellHarness);
    await fireEvent.click(getByRole("button", { name: /sign out/i }));

    await Promise.resolve();
    await Promise.resolve();

    expect(authStore.token).toBeNull();
    expect(router.path).toBe("/admin/login");
  });
});
