// jsdom ships no IndexedDB implementation — Dexie needs a real (or faked)
// one to open. Polyfilled per-file (not globally) so only this suite pays
// the cost.
import "fake-indexeddb/auto";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as chatInteraction from "$lib/api/chatInteraction";
import type { AgentMessage } from "$lib/types/agent";

import { ChatService, db } from "./chat-db";

describe("ChatService (Dexie local store)", () => {
  beforeEach(() => {
    vi.spyOn(chatInteraction, "listConversations").mockResolvedValue([]);
    vi.spyOn(chatInteraction, "loadMessages").mockResolvedValue([]);
    vi.spyOn(chatInteraction, "createConversationRemote").mockResolvedValue(true);
    vi.spyOn(chatInteraction, "updateConversationTitleRemote").mockResolvedValue(true);
    vi.spyOn(chatInteraction, "deleteConversationRemote").mockResolvedValue(true);
    vi.spyOn(chatInteraction, "deleteMessageRemote").mockResolvedValue(true);
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    await db.messages.clear();
    await db.conversations.clear();
  });

  it("saves, gets and deletes a conversation + its messages per agent", async () => {
    const sessionId = "session-1";
    await ChatService.createConversation("agent-a", sessionId, "Test conversation");

    const message: AgentMessage = {
      id: "msg-1",
      role: "user",
      content: "hello",
      timestamp: new Date(),
      metadata: { session_id: sessionId, model: "", provider: "", turn_id: "t1" } as any,
    };
    await ChatService.saveMessage(message);

    const messages = await ChatService.getMessages(sessionId, "agent-a");
    expect(messages).toHaveLength(1);
    expect(messages[0].content).toBe("hello");

    const conversations = await ChatService.getConversations("agent-a");
    expect(conversations.map((c) => c.id)).toContain(sessionId);

    await ChatService.deleteConversation(sessionId, "agent-a");
    const afterDelete = await db.conversations.get(sessionId);
    expect(afterDelete).toBeUndefined();
    const messagesAfterDelete = await db.messages
      .where("metadata.session_id")
      .equals(sessionId)
      .toArray();
    expect(messagesAfterDelete).toHaveLength(0);
  });

  it("syncConversationsFromBackend merges server conversations into the local store", async () => {
    vi.spyOn(chatInteraction, "listConversations").mockResolvedValue([
      {
        session_id: "server-session",
        user_id: "u1",
        agent_id: "agent-a",
        title: "From server",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ]);

    await ChatService.syncConversationsFromBackend("agent-a");

    const stored = await db.conversations.get("server-session");
    expect(stored?.title).toBe("From server");
    expect(stored?.agent_name).toBe("agent-a");
  });

  it("degrades to an empty result when the local IndexedDB read fails", async () => {
    const spy = vi
      .spyOn(db.conversations, "orderBy")
      .mockImplementation(() => {
        throw new Error("IndexedDB unavailable");
      });

    const result = await ChatService._getLocalConversations();
    expect(result).toEqual([]);

    spy.mockRestore();
  });
});
