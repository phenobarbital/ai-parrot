import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import { disconnect, startConnect } from "$lib/api/connections";
import { awaitOAuthCallback } from "$lib/oauth/popup";
import { connectionsStore } from "$lib/stores/connections.svelte";

import ConnectionsPanel from "./ConnectionsPanel.svelte";

vi.mock("$lib/api/connections", () => ({
  disconnect: vi.fn(),
  listConnections: vi.fn(),
  openConnectionEvents: vi.fn(),
  startConnect: vi.fn(),
}));

vi.mock("$lib/oauth/popup", () => ({ awaitOAuthCallback: vi.fn() }));

describe("ConnectionsPanel", () => {
  afterEach(() => {
    connectionsStore.items = [];
    connectionsStore.loading = false;
    vi.restoreAllMocks();
  });

  it("renders status, account, scopes, expiry, and channels", () => {
    connectionsStore.items = [
      {
        provider: "slack",
        display_name: "Slack",
        display_account_name: "Acme workspace",
        email: null,
        status: "needs_reconnect",
        connected: false,
        scopes_granted: ["chat:write", "users:read"],
        expires_at: 1_800_000_000,
        channels: ["web", "slack"],
      },
    ];

    const { getByTestId, getByText } = render(ConnectionsPanel);

    expect(getByText("Slack")).toBeTruthy();
    expect(getByTestId("status-slack").textContent).toContain("needs_reconnect");
    expect(getByText("Acme workspace")).toBeTruthy();
    expect(getByText("chat:write, users:read")).toBeTruthy();
    expect(getByText("web, slack")).toBeTruthy();
    expect(getByTestId("connection-slack").textContent).toContain("/");
  });

  it("connects through the OAuth popup and refreshes, then disconnects and refreshes", async () => {
    const refresh = vi.spyOn(connectionsStore, "refresh").mockResolvedValue();
    vi.mocked(startConnect).mockResolvedValue({ auth_url: "https://slack.example/oauth" });
    vi.mocked(awaitOAuthCallback).mockResolvedValue({
      success: true,
      payload: { provider: "slack" },
    });
    vi.mocked(disconnect).mockResolvedValue({ provider: "slack", disconnected: true });
    connectionsStore.items = [
      {
        provider: "slack",
        display_name: "Slack",
        status: "connected",
        connected: true,
        scopes_granted: [],
        channels: [],
      },
    ];

    const { getByRole } = render(ConnectionsPanel);
    await fireEvent.click(getByRole("button", { name: "Reconnect" }));

    await waitFor(() => expect(startConnect).toHaveBeenCalledWith("slack", window.location.origin));
    expect(awaitOAuthCallback).toHaveBeenCalledWith({
      authUrl: "https://slack.example/oauth",
      allowedOrigin: window.location.origin,
    });
    expect(refresh).toHaveBeenCalledTimes(1);

    await fireEvent.click(getByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(disconnect).toHaveBeenCalledWith("slack"));
    expect(refresh).toHaveBeenCalledTimes(2);
  });
});
