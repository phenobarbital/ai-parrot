import { render } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import apiClient from "$lib/api/http";
import { navEntries } from "$lib/nav";
import { router } from "$lib/router.svelte";

import Home from "./Home.svelte";

describe("Home", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the server name and version from the status payload", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({
      data: { name: "ai-parrot", version: "1.2.3" },
    });

    const { findByText } = render(Home);

    expect(await findByText("Welcome to ai-parrot Admin")).toBeTruthy();
    expect(await findByText("Server version 1.2.3.")).toBeTruthy();
  });

  it("renders navigation cards for every non-Home nav entry", () => {
    router.path = "/admin/home";
    const { getByText } = render(Home);

    for (const entry of navEntries) {
      if (entry.path === "/admin/home") continue;
      expect(getByText(entry.label)).toBeTruthy();
    }
  });

  it("falls back to generic copy when the status fetch fails", async () => {
    vi.spyOn(apiClient, "get").mockRejectedValue(new Error("network down"));

    const { findByText } = render(Home);

    expect(await findByText("Manage agents, crews, and server status from one place.")).toBeTruthy();
  });
});
