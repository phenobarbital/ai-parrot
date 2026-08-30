// ai-parrot (FEAT-476 TASK-2596): voice-note degradation — the mount-time
// `checkVoiceSupport()` HEAD-request preflight (TASK-2594) can pass even
// when the real upload route 404s; the first such failure during an
// actual send must hide the mic and toast once, per spec §3 Module 6.
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { chatService, wsService, sendVoiceNote, checkVoiceSupport, toastStore } =
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
    sendVoiceNote: vi.fn(),
    checkVoiceSupport: vi.fn(async () => true),
    toastStore: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
  }));

vi.mock("$lib/services/chat-db", () => ({ ChatService: chatService }));
vi.mock("$lib/services/websocket-service", () => ({ wsService }));
vi.mock("$lib/api/stream", () => ({
  streamChatWithAgent: vi.fn(),
  streamChatWithBot: vi.fn(),
}));
vi.mock("$lib/api/agent", () => ({
  chatWithAgent: vi.fn(),
  callAgentMethod: vi.fn(),
  sendVoiceNote,
  checkVoiceSupport,
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
vi.mock("$lib/stores/toast.svelte", () => ({ toastStore }));
vi.mock("$lib/stores/notifications.svelte", () => ({
  notificationStore: { add: vi.fn(), remove: vi.fn() },
}));

// Bypass the real MediaRecorder-backed VoiceRecorder — ChatInput
// instantiates `new VoiceRecorder()` directly, so the whole module is
// replaced with a fake that "records" instantly.
vi.mock("$lib/utils/voice-recorder", () => ({
  isVoiceRecordingSupported: () => true,
  VoiceRecorder: class {
    async start() {}
    async stop() {
      return {
        blob: new Blob(["x"], { type: "audio/webm" }),
        mimeType: "audio/webm",
        extension: "webm",
        durationMs: 1000,
      };
    }
    cancel() {}
  },
}));

import AgentChat from "./AgentChat.svelte";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  checkVoiceSupport.mockResolvedValue(true);
  chatService.getConversations.mockResolvedValue([]);
  chatService.createConversation.mockResolvedValue({ id: "c1" });
});

async function sendVoiceNoteViaUi() {
  await fireEvent.click(screen.getByLabelText("Record a voice note"));
  await fireEvent.click(await screen.findByLabelText("Send voice note"));
}

describe("voice-gating", () => {
  it("hides the mic and toasts once after the first 404 from the voice endpoint", async () => {
    sendVoiceNote.mockRejectedValue(
      Object.assign(new Error("Not Found"), { status: 404 }),
    );

    render(AgentChat, {
      agentId: "bot-1",
      variant: "compact",
      enableVoiceNotes: true,
    });
    await waitFor(() => expect(checkVoiceSupport).toHaveBeenCalled());
    await screen.findByLabelText("Record a voice note");

    await sendVoiceNoteViaUi();

    await waitFor(() =>
      expect(screen.queryByLabelText("Record a voice note")).toBeNull(),
    );
    // The in-chat "Voice unavailable" bubble AND a one-time toast both fire.
    expect(await screen.findByText(/Voice unavailable/)).toBeInTheDocument();
    expect(toastStore.error).toHaveBeenCalledTimes(1);
  });

  it("never shows the mic when the mount-time preflight itself fails", async () => {
    checkVoiceSupport.mockResolvedValue(false);
    render(AgentChat, {
      agentId: "bot-1",
      variant: "compact",
      enableVoiceNotes: true,
    });
    await waitFor(() => expect(checkVoiceSupport).toHaveBeenCalled());
    expect(screen.queryByLabelText("Record a voice note")).toBeNull();
  });
});
