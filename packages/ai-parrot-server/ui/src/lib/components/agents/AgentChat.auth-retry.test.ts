import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  chatService,
  wsService,
  streamChatWithAgent,
  streamChatWithBot,
  chatWithAgent,
  startConnect,
  awaitOAuthCallback,
  connectionsStore,
  listeners,
} = vi.hoisted(() => {
  const eventListeners = new Set<(event: { kind: string; provider: string }) => void>();
  return {
    chatService: {
      getConversations: vi.fn(async () => []),
      getMessages: vi.fn(async () => []),
      saveMessage: vi.fn(async () => {}),
      createConversation: vi.fn(async () => ({ id: "c1" })),
      updateConversationTitle: vi.fn(async () => {}),
      deleteConversation: vi.fn(async () => {}),
    },
    wsService: {
      connect: vi.fn(async () => {}),
      subscribe: vi.fn(),
      unsubscribe: vi.fn(),
      onMessage: vi.fn(() => () => {}),
    },
    streamChatWithAgent: vi.fn(),
    streamChatWithBot: vi.fn(),
    chatWithAgent: vi.fn(),
    startConnect: vi.fn(),
    awaitOAuthCallback: vi.fn(),
    connectionsStore: {
      items: [] as Array<{ provider: string; connected: boolean; scopes_granted?: string[] }>,
      start: vi.fn(),
      stop: vi.fn(),
      refresh: vi.fn(async () => {}),
      onEvent: vi.fn((listener) => {
        eventListeners.add(listener);
        return () => eventListeners.delete(listener);
      }),
    },
    listeners: eventListeners,
  };
});

vi.mock("$lib/services/chat-db", () => ({ ChatService: chatService }));
vi.mock("$lib/services/websocket-service", () => ({ wsService }));
vi.mock("$lib/api/stream", () => ({ streamChatWithAgent, streamChatWithBot }));
vi.mock("$lib/api/agent", () => ({
  chatWithAgent,
  callAgentMethod: vi.fn(),
  sendVoiceNote: vi.fn(),
  checkVoiceSupport: vi.fn(async () => false),
}));
vi.mock("$lib/api/botChat", () => ({ chatWithBot: vi.fn() }));
vi.mock("$lib/api/connections", () => ({ startConnect }));
vi.mock("$lib/oauth/popup", () => ({ awaitOAuthCallback }));
vi.mock("$lib/stores/connections.svelte", () => ({ connectionsStore }));
vi.mock("$lib/stores/prompt-library.svelte", () => ({
  loadPrompts: vi.fn(async () => {}),
  getPrompts: () => [],
  getPublicPrompts: () => [],
  getUserPrompts: () => [],
  getStarterPrompts: () => [],
  isLoadingPrompts: () => false,
  getError: () => null,
  getCanAddMore: () => true,
  getPromptCount: () => 0,
  getCurrentAgentId: () => null,
  getChatbotId: () => null,
}));
vi.mock("$lib/stores/toast.svelte", () => ({
  toastStore: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));
vi.mock("$lib/stores/notifications.svelte", () => ({
  notificationStore: { add: vi.fn(), remove: vi.fn() },
}));

import AgentChat from "./AgentChat.svelte";

function enableStreaming(): void {
  localStorage.setItem("stream_enabled_agent-1", "true");
}

async function sendMessage(text = "need Jira"): Promise<void> {
  await fireEvent.input(screen.getByRole("textbox"), { target: { value: text } });
  await fireEvent.click(screen.getByTitle("Send message (Shift+Enter)"));
}

function authStream(retrySafe?: boolean): () => AsyncGenerator<unknown> {
  let turn = 0;
  return async function* () {
    turn += 1;
    yield {
      type: "done",
      message: {
        output: "Need authorization",
        metadata: { session_id: "s1", turn_id: `t${turn}` },
        sources: [],
        tool_calls: [],
      },
    };
    yield {
      type: "auth_required",
      payload: { provider: "jira", message: "Connect Jira", scopes: ["read:jira"] },
      ...(retrySafe === undefined ? {} : { retry_safe: retrySafe }),
    };
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  listeners.clear();
  chatService.getConversations.mockResolvedValue([]);
  chatService.createConversation.mockResolvedValue({ id: "c1" });
  connectionsStore.items = [{ provider: "jira", connected: true, scopes_granted: ["read:jira"] }];
  startConnect.mockResolvedValue({ auth_url: "https://safe.example/connect" });
  awaitOAuthCallback.mockResolvedValue({ success: true });
  streamChatWithAgent.mockImplementation(authStream(true));
});

describe("AgentChat auth retry", () => {
  it("streaming: renders the pill from an auth_required chunk", async () => {
    enableStreaming();
    render(AgentChat, { agentId: "agent-1", variant: "compact" });
    await sendMessage();
    expect(await screen.findByRole("button", { name: /connect jira/i })).toBeInTheDocument();
  });

  it("non-streaming: renders the pill from an auth_required response", async () => {
    chatWithAgent.mockResolvedValue({
      type: "auth_required",
      message: "Connect Jira",
      provider: "jira",
      scopes: ["read:jira"],
    });
    render(AgentChat, { agentId: "agent-1", variant: "compact" });
    await sendMessage();
    expect(await screen.findByRole("button", { name: /connect jira/i })).toBeInTheDocument();
  });

  it("auto-retries once when retry_safe and scopes are ready (popup + SSE race)", async () => {
    enableStreaming();
    render(AgentChat, { agentId: "agent-1", variant: "compact" });
    await sendMessage();
    await fireEvent.click(await screen.findByRole("button", { name: /connect jira/i }));
    for (const listener of listeners) listener({ kind: "connection.completed", provider: "jira" });
    await waitFor(() => expect(streamChatWithAgent).toHaveBeenCalledTimes(2));
    expect(connectionsStore.refresh).toHaveBeenCalledTimes(1);
  });

  it("a duplicate connected while the auto-retry is in flight shows no manual-retry warning", async () => {
    enableStreaming();
    let releaseRefresh: () => void = () => {};
    connectionsStore.refresh.mockImplementationOnce(
      () => new Promise<void>((resolve) => (releaseRefresh = resolve)),
    );
    render(AgentChat, { agentId: "agent-1", variant: "compact" });
    await sendMessage();
    await fireEvent.click(await screen.findByRole("button", { name: /connect jira/i }));
    await waitFor(() => expect(connectionsStore.refresh).toHaveBeenCalledTimes(1));
    // SSE reports the same connection while the popup's auto-retry is still refreshing.
    for (const listener of listeners) listener({ kind: "connection.completed", provider: "jira" });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByText(/Retrying may repeat actions that already completed/)).not.toBeInTheDocument();
    releaseRefresh();
    await waitFor(() => expect(streamChatWithAgent).toHaveBeenCalledTimes(2));
  });

  it("repeated auth failure on the retried turn does not resend again", async () => {
    enableStreaming();
    render(AgentChat, { agentId: "agent-1", variant: "compact" });
    await sendMessage();
    await fireEvent.click(await screen.findByRole("button", { name: /connect jira/i }));
    await waitFor(() => expect(streamChatWithAgent).toHaveBeenCalledTimes(2));
    await fireEvent.click(await screen.findByRole("button", { name: /connect jira/i }));
    await waitFor(() => expect(startConnect).toHaveBeenCalledTimes(2));
    expect(streamChatWithAgent).toHaveBeenCalledTimes(2);
    // A new pill for an already auto-retried turn still asks for a manual retry.
    expect(await screen.findByText(/Retrying may repeat actions that already completed/)).toBeInTheDocument();
  });

  it("no auto-retry when retry_safe is false or absent; manual Retry warns", async () => {
    enableStreaming();
    streamChatWithAgent.mockImplementation(authStream());
    render(AgentChat, { agentId: "agent-1", variant: "compact" });
    await sendMessage();
    await fireEvent.click(await screen.findByRole("button", { name: /connect jira/i }));
    expect(await screen.findByText(/Retrying may repeat actions that already completed/)).toBeInTheDocument();
    expect(streamChatWithAgent).toHaveBeenCalledTimes(1);
  });

  it("no auto-retry when scopes are missing", async () => {
    enableStreaming();
    connectionsStore.items = [{ provider: "jira", connected: true, scopes_granted: [] }];
    render(AgentChat, { agentId: "agent-1", variant: "compact" });
    await sendMessage();
    await fireEvent.click(await screen.findByRole("button", { name: /connect jira/i }));
    await waitFor(() => expect(connectionsStore.refresh).toHaveBeenCalled());
    expect(streamChatWithAgent).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/Retrying may repeat actions that already completed/)).toBeInTheDocument();
  });

  it("does not auto-retry when a newer user message exists", async () => {
    enableStreaming();
    render(AgentChat, { agentId: "agent-1", variant: "compact" });
    await sendMessage();
    const originalConnect = await screen.findByRole("button", { name: /connect jira/i });
    await sendMessage("newer request");
    await waitFor(() => expect(streamChatWithAgent).toHaveBeenCalledTimes(2));
    await fireEvent.click(originalConnect);
    await waitFor(() => expect(startConnect).toHaveBeenCalled());
    expect(streamChatWithAgent).toHaveBeenCalledTimes(2);
    expect(await screen.findByText(/Retrying may repeat actions that already completed/)).toBeInTheDocument();
  });
});
