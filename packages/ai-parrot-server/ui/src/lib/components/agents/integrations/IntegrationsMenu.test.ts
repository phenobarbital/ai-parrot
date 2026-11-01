import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { awaitOAuthCallback, connectionsStore, disconnect, startConnect } = vi.hoisted(() => ({
  awaitOAuthCallback: vi.fn(),
  connectionsStore: {
    items: [] as Array<{ provider: string; display_name: string; connected: boolean }>,
    loading: false,
    error: null as string | null,
    refresh: vi.fn(async () => {}),
    start: vi.fn(),
  },
  disconnect: vi.fn(),
  startConnect: vi.fn(),
}));

vi.mock("$lib/api/connections", () => ({ disconnect, startConnect }));
vi.mock("$lib/oauth/popup", () => ({ awaitOAuthCallback }));
vi.mock("$lib/stores/connections.svelte", () => ({ connectionsStore }));
vi.mock("$lib/stores/toast.svelte", () => ({
  toastStore: { success: vi.fn(), error: vi.fn() },
}));

import IntegrationsMenu from "./IntegrationsMenu.svelte";

beforeEach(() => {
  vi.clearAllMocks();
  connectionsStore.items = [];
  connectionsStore.loading = false;
  connectionsStore.error = null;
  startConnect.mockResolvedValue({ auth_url: "https://safe.example/connect" });
  awaitOAuthCallback.mockResolvedValue({
    success: true,
    payload: { provider: "jira" },
  });
  disconnect.mockResolvedValue({ provider: "jira", disconnected: true });
});

describe("IntegrationsMenu", () => {
  it("opening the menu refreshes the store and lists its items", async () => {
    connectionsStore.items = [
      {
        provider: "jira",
        display_name: "Jira",
        connected: false,
      },
    ];

    render(IntegrationsMenu, { agentId: "agent-1" });
    expect(connectionsStore.start).toHaveBeenCalledTimes(1);

    await fireEvent.click(screen.getByRole("button", { name: "Open integrations menu" }));

    await waitFor(() => expect(connectionsStore.refresh).toHaveBeenCalledTimes(1));
    expect(screen.getByText("Jira")).toBeTruthy();
  });

  it("connect uses startConnect + popup, then refreshes; never calls /enable", async () => {
    connectionsStore.items = [
      {
        provider: "jira",
        display_name: "Jira",
        connected: false,
      },
    ];

    render(IntegrationsMenu, { agentId: "agent-1" });
    await fireEvent.click(screen.getByRole("button", { name: "Open integrations menu" }));
    await waitFor(() => expect(connectionsStore.refresh).toHaveBeenCalled());
    connectionsStore.refresh.mockClear();

    await fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() => expect(startConnect).toHaveBeenCalledWith("jira", window.location.origin));
    expect(awaitOAuthCallback).toHaveBeenCalledWith({
      authUrl: "https://safe.example/connect",
      allowedOrigin: window.location.origin,
    });
    await waitFor(() => expect(connectionsStore.refresh).toHaveBeenCalledTimes(1));
  });

  it("disconnect calls disconnect(provider) then refreshes", async () => {
    connectionsStore.items = [
      {
        provider: "jira",
        display_name: "Jira",
        connected: true,
      },
    ];

    render(IntegrationsMenu, { agentId: "agent-1" });
    await fireEvent.click(screen.getByRole("button", { name: "Open integrations menu" }));
    await waitFor(() => expect(connectionsStore.refresh).toHaveBeenCalled());
    connectionsStore.refresh.mockClear();

    await fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));

    await waitFor(() => expect(disconnect).toHaveBeenCalledWith("jira"));
    await waitFor(() => expect(connectionsStore.refresh).toHaveBeenCalledTimes(1));
  });
});
