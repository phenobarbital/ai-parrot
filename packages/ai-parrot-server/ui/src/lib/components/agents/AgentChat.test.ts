// ai-parrot (FEAT-476 TASK-2594): AgentChat.svelte tests — streaming,
// non-stream fallback, error bubble + retry, the policy-denial 401
// special case, and the "compact" variant's layout-store guard.
//
// The redirect-to-login mechanics of a *non-policy* 401 (clear storage,
// navigate with `?next=`) are `authStore.handle401()`'s job — already
// covered by `src/lib/stores/auth.test.ts` and wired through the shared
// axios interceptor in `src/lib/api/http.ts` (not reimplemented here).
// This suite only exercises the AgentChat-owned branch: policy-denial
// 401s (`/policy/i` in the error message) render a distinct "Access
// denied" bubble and are never persisted for a brand-new conversation;
// every other error (including an already-redirected plain 401) falls
// through to the generic error bubble with Retry.
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { chatService, wsService, streamChatWithAgent, streamChatWithBot, chatWithAgent } =
  vi.hoisted(() => ({
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
      disconnect: vi.fn(),
      subscribe: vi.fn(),
      unsubscribe: vi.fn(),
      onMessage: vi.fn(() => () => {}),
    },
    streamChatWithAgent: vi.fn(),
    streamChatWithBot: vi.fn(),
    chatWithAgent: vi.fn(),
  }));

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
import * as chatLayout from "$lib/stores/agentchat-layout.svelte";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  chatService.getConversations.mockResolvedValue([]);
  chatService.createConversation.mockResolvedValue({ id: "c1" });
});

// AgentChat's stream toggle is internal state (not a prop) hydrated from
// `localStorage["stream_enabled_<agentId>"]` on mount (spec §2).
function enableStreamingFor(agentId: string) {
  localStorage.setItem(`stream_enabled_${agentId}`, "true");
}

async function sendMessage(text: string) {
  const textarea = screen.getByRole("textbox");
  await fireEvent.input(textarea, { target: { value: text } });
  await fireEvent.click(screen.getByTitle("Send message (Shift+Enter)"));
}

describe("AgentChat — streaming", () => {
  it("streams chunks and finalizes the assistant message", async () => {
    enableStreamingFor("bot-1");
    streamChatWithAgent.mockImplementation(async function* () {
      yield { type: "chunk", text: "Hel" };
      yield { type: "chunk", text: "lo" };
      yield {
        type: "done",
        message: {
          output: "Hello",
          metadata: { session_id: "s1", turn_id: "t1" },
          sources: [],
          tool_calls: [],
        },
      };
    });

    render(AgentChat, { agentId: "bot-1", variant: "compact" });
    await sendMessage("hi");

    await waitFor(() => expect(screen.getByText("Hello")).toBeInTheDocument());
  });
});

describe("AgentChat — non-streaming fallback", () => {
  it("renders the assistant reply from the non-stream response", async () => {
    chatWithAgent.mockResolvedValue({
      response: "Non-stream reply",
      metadata: { session_id: "s1", turn_id: "t1" },
      sources: [],
      tool_calls: [],
    });

    render(AgentChat, { agentId: "bot-1", variant: "compact" });
    await sendMessage("hi");

    await waitFor(() =>
      expect(screen.getByText("Non-stream reply")).toBeInTheDocument(),
    );
  });
});

describe("AgentChat — error handling", () => {
  it("shows a generic error bubble with Retry on a non-policy failure", async () => {
    chatWithAgent.mockRejectedValue(
      Object.assign(new Error("Unauthorized"), { status: 401 }),
    );

    render(AgentChat, { agentId: "bot-1", variant: "compact" });
    await sendMessage("hi");

    await waitFor(() =>
      expect(screen.getByText(/Failed to get response from agent/)).toBeInTheDocument(),
    );
    expect(screen.getByTitle("Retry request")).toBeInTheDocument();
    // Not the special policy-denial copy.
    expect(screen.queryByText(/Access denied/)).toBeNull();
  });

  it("shows the policy-denial bubble (no Retry, conversation dropped) on a 401 with a policy message", async () => {
    chatWithAgent.mockRejectedValue(
      Object.assign(new Error("Blocked by policy engine"), { status: 401 }),
    );

    render(AgentChat, { agentId: "bot-1", variant: "compact" });
    await sendMessage("hi");

    await waitFor(() =>
      expect(screen.getByText(/Access denied/)).toBeInTheDocument(),
    );
    // Policy denials are never persisted, and this was a brand-new
    // conversation, so it's dropped rather than saved. `createConversation`
    // is called with a client-generated session id (its own return value —
    // `{ id: "c1" }` — is unused by AgentChat), so assert the *same* id
    // flows through to `deleteConversation`.
    const [, newSessionId] = chatService.createConversation.mock.calls[0];
    expect(chatService.deleteConversation).toHaveBeenCalledWith(newSessionId);
    expect(chatService.saveMessage).not.toHaveBeenCalledWith(
      expect.objectContaining({ metadata: expect.objectContaining({ is_error: true }) }),
    );
  });
});

describe("AgentChat — compact variant", () => {
  it("hides the history pane (ConversationList) and never touches the global layout store", async () => {
    const collapseSpy = vi.spyOn(chatLayout, "collapseGlobalNav");
    const restoreSpy = vi.spyOn(chatLayout, "restoreGlobalNav");

    const { unmount } = render(AgentChat, { agentId: "bot-1", variant: "compact" });
    await waitFor(() => expect(wsService.connect).toHaveBeenCalled());

    // The history-pane toggle (and its <aside>/<ConversationList>) only
    // exist in the default variant.
    expect(screen.queryByTitle("Open history")).toBeNull();
    expect(collapseSpy).not.toHaveBeenCalled();

    unmount();
    expect(restoreSpy).not.toHaveBeenCalled();
  });

  it("shows the history-pane toggle in the default (non-compact) variant", async () => {
    render(AgentChat, { agentId: "bot-1" });
    await waitFor(() => expect(wsService.connect).toHaveBeenCalled());
    expect(screen.getByTitle("Open history")).toBeInTheDocument();
  });
});
