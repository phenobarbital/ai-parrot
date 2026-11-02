import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { startConnect, awaitOAuthCallback, connectionsStore, listeners } = vi.hoisted(() => {
  const eventListeners = new Set<(event: { kind: string; provider: string }) => void>();
  return {
    startConnect: vi.fn(),
    awaitOAuthCallback: vi.fn(),
    connectionsStore: {
      onEvent: vi.fn((listener) => {
        eventListeners.add(listener);
        return () => eventListeners.delete(listener);
      }),
    },
    listeners: eventListeners,
  };
});

vi.mock("$lib/api/connections", () => ({ startConnect }));
vi.mock("$lib/oauth/popup", () => ({ awaitOAuthCallback }));
vi.mock("$lib/stores/connections.svelte", () => ({ connectionsStore }));
vi.mock("$lib/stores/toast.svelte", () => ({
  toastStore: { success: vi.fn(), error: vi.fn() },
}));

import ConnectIntegrationPill from "./ConnectIntegrationPill.svelte";

beforeEach(() => {
  vi.clearAllMocks();
  listeners.clear();
  startConnect.mockResolvedValue({ auth_url: "https://safe.example/connect" });
  awaitOAuthCallback.mockResolvedValue({ success: true });
});

describe("ConnectIntegrationPill", () => {
  it("connects through startConnect, not the payload auth_url", async () => {
    render(ConnectIntegrationPill, {
      provider: "jira",
      message: "Connect Jira",
      agentId: "agent-1",
      scopes: ["read:jira"],
    });

    await fireEvent.click(screen.getByRole("button", { name: /connect jira/i }));

    await waitFor(() => {
      expect(startConnect).toHaveBeenCalledWith("jira", window.location.origin, ["read:jira"]);
    });
    expect(awaitOAuthCallback).toHaveBeenCalledWith({
      authUrl: "https://safe.example/connect",
      allowedOrigin: window.location.origin,
    });
  });

  it("calls onConnected once on popup success or a matching SSE completion", async () => {
    const onConnected = vi.fn();
    render(ConnectIntegrationPill, {
      provider: "jira",
      message: "Connect Jira",
      agentId: "agent-1",
      onConnected,
    });

    await fireEvent.click(screen.getByRole("button", { name: /connect jira/i }));
    await waitFor(() => expect(onConnected).toHaveBeenCalledWith("jira"));

    for (const listener of listeners) {
      listener({ kind: "connection.completed", provider: "jira" });
      listener({ kind: "connection.completed", provider: "slack" });
    }
    expect(onConnected).toHaveBeenCalledTimes(1);
  });
});
