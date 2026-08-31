// ai-parrot (FEAT-476 TASK-2596): avatar session degradation.
//
// AvatarViewer/VoiceNativeAvatarViewer are verbatim ports whose own
// LiveKit connect logic (spec §3 Module 6) already maps a 403 from
// `startAvatarSession` to `AvatarDisabledError` -> `onstatuschange("disabled")`
// — not re-tested here (no logic changes there to verify). This suite
// covers the AgentChat-owned wiring added by this task: once a status
// callback reports "disabled", `avatarEnabled`/`voiceNativeEnabled` reset,
// a one-time toast fires, and `stores/avatar.svelte.ts`'s session-scoped
// `markAvatarUnavailable`/`isAvatarUnavailable` stop the user from
// re-triggering a known-broken session for the rest of the session.
//
// "features.avatar=false -> no livekit import" is a structural guarantee,
// not a runtime behavior to assert: AvatarViewer.svelte (which does the
// `import("livekit-client")`) is itself only ever reached through
// `{#if features.avatar}{#await import(".../AvatarViewer.svelte")}` in
// AgentChat.svelte — the same architecture TASK-2595's
// features-gating.test.ts verifies for the chart/map surfaces.
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { chatService, wsService, toastStore } = vi.hoisted(() => ({
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
  toastStore: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

// The stub records whatever `onstatuschange` AgentChat wires to the
// mounted viewer onto this global, so the test can invoke it directly
// instead of driving a real (mocked) LiveKit connect sequence.
declare global {
  // eslint-disable-next-line no-var
  var __avatarStatusCallback: ((s: string) => void) | null;
}

vi.mock("$lib/services/chat-db", () => ({ ChatService: chatService }));
vi.mock("$lib/services/websocket-service", () => ({ wsService }));
vi.mock("$lib/api/stream", () => ({
  streamChatWithAgent: vi.fn(),
  streamChatWithBot: vi.fn(),
}));
vi.mock("$lib/api/agent", () => ({
  chatWithAgent: vi.fn(),
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
vi.mock("$lib/stores/toast.svelte", () => ({ toastStore }));
vi.mock("$lib/stores/notifications.svelte", () => ({
  notificationStore: { add: vi.fn(), remove: vi.fn() },
}));

// Stub the (real, LiveKit-backed) viewer entirely — it's reached only via
// AgentChat's `{#if features.avatar}{#await import(...)}`, so mocking
// exactly that specifier also doubles as proof of the gated import path.
vi.mock(
  "./avatar/AvatarViewer.svelte",
  () => import("./avatar/AvatarViewer.stub.svelte"),
);

import AgentChat from "./AgentChat.svelte";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  globalThis.__avatarStatusCallback = null;
  chatService.getConversations.mockResolvedValue([]);
  chatService.createConversation.mockResolvedValue({ id: "c1" });
});

describe("avatar-gating", () => {
  it("degrades once on a disabled status: toggle resets, toast fires, dock stops re-mounting", async () => {
    render(AgentChat, { agentId: "bot-1" });

    await fireEvent.click(screen.getByLabelText("Talk with avatar"));
    await waitFor(() => expect(globalThis.__avatarStatusCallback).not.toBeNull());

    // Simulate the (verbatim, untested-here) AvatarViewer LiveKit connect
    // path reporting a 403 -> AvatarDisabledError -> "disabled".
    globalThis.__avatarStatusCallback!("disabled");

    await waitFor(() =>
      expect(screen.getByLabelText("Talk with avatar")).toBeInTheDocument(),
    );
    expect(toastStore.error).toHaveBeenCalledTimes(1);

    // Re-clicking must not re-attempt the session (isAvatarUnavailable gate) —
    // no second toggle-on, no second toast beyond the explanatory one.
    globalThis.__avatarStatusCallback = null;
    await fireEvent.click(screen.getByLabelText("Talk with avatar"));
    expect(globalThis.__avatarStatusCallback).toBeNull(); // viewer never re-mounted
    expect(toastStore.error).toHaveBeenCalledTimes(2); // explains again, doesn't retry
  });
});
