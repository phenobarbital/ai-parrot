import Dexie, { type Table } from "dexie";
import type { AgentConversation, AgentMessage } from "$lib/types/agent";
import { config } from "$lib/config";
import { resolveAgentSources } from "$lib/utils/bot-response-parser";
import {
  listConversations,
  loadMessages,
  createConversationRemote,
  updateConversationTitleRemote,
  deleteConversationRemote,
  deleteMessageRemote,
  type BackendConversation,
  type BackendMessage,
} from "$lib/api/chatInteraction";

/** Canvas state persisted per conversation session. */
export interface CanvasState {
  session_id: string;
  tabs: Array<{
    id: string;
    type: string; // CanvasTabType
    title: string;
    data: unknown; // CanvasBlock[] for block tabs, string for infographic, etc.
    closable: boolean;
  }>;
  activeTabId: string | null;
  updated_at: Date;
}

export class ChatDatabase extends Dexie {
  conversations!: Table<AgentConversation>;
  messages!: Table<AgentMessage>;
  canvas_state!: Table<CanvasState>;

  constructor() {
    super(config.conversationStoragePrefix || "agentui_chat_db");

    // Initial schema
    this.version(1).stores({
      conversations: "id, created_at, updated_at",
      messages: "id, metadata.session_id, timestamp",
    });

    // Version 2: Add agent_name index
    this.version(2).stores({
      conversations: "id, agent_name, created_at, updated_at",
      messages: "id, metadata.session_id, timestamp",
    });

    // Version 3: Add canvas_state table (FEAT-034)
    this.version(3).stores({
      conversations: "id, agent_name, created_at, updated_at",
      messages: "id, metadata.session_id, timestamp",
      canvas_state: "session_id",
    });
  }
}

export const db = new ChatDatabase();

// --- Mapping helpers ---

function mapBackendConversation(bc: BackendConversation): AgentConversation {
  return {
    id: bc.session_id,
    title: bc.title || "Untitled",
    created_at: new Date(bc.created_at),
    updated_at: new Date(bc.updated_at),
    agent_name: bc.agent_id,
    last_message: bc.last_user_message || bc.last_assistant_message,
  };
}

function mapBackendMessage(bm: BackendMessage): AgentMessage {
  const content = bm.content || "";
  const isHtml =
    content.trim().startsWith("<!DOCTYPE html") ||
    content.trim().startsWith("<html");

  // Build a collision-safe Dexie primary key. The backend often reuses the
  // same turn_id (and sometimes message_id) for both the user and assistant
  // messages of a turn. If both roles resolved to the same id, bulkPut would
  // silently overwrite the user record with the assistant record, causing user
  // messages to disappear from the chat history.
  //
  // Strategy: assistant messages keep the raw backend id (turn_id) so they
  // stay in sync with locally-saved assistant messages (which also use
  // result.metadata.turn_id as their id). User messages are prefixed with
  // "u_" so they always occupy a distinct Dexie row.
  const baseId = bm.message_id || bm.turn_id;
  const id = baseId
    ? bm.role === "user"
      ? `u_${baseId}`
      : baseId
    : crypto.randomUUID();

  return {
    id,
    role: bm.role,
    content,
    timestamp: new Date(bm.timestamp),
    metadata: {
      session_id: bm.session_id,
      model: bm.model || "",
      provider: bm.provider || "",
      turn_id: bm.turn_id || "",
      response_time: bm.response_time_ms ?? null,
    },
    data: bm.data,
    code: bm.code,
    // Some backend storage paths (e.g. older Redis ConversationTurn records)
    // nested these under `metadata` instead of returning them top-level.
    // Read top-level first, fall back to metadata so the SQL artifact card
    // survives a refresh on those records.
    output: bm.output ?? (bm.metadata?.output as typeof bm.output | undefined),
    output_mode:
      bm.output_mode ?? (bm.metadata?.output_mode as string | undefined),
    htmlResponse: isHtml ? content : null,
    tool_calls: bm.tool_calls?.map((tc) => ({
      name: tc.name || "unknown",
      status: tc.status || "completed",
      output: tc.output,
      arguments: tc.arguments,
    })),
    sources: resolveAgentSources(bm.sources),
  };
}

// Service functions
export const ChatService = {
  async createConversation(
    agentName: string,
    id: string,
    initialTitle: string = "New Conversation",
  ): Promise<string> {
    console.log("[ChatService] Creating conversation:", {
      agentName,
      id,
      initialTitle,
    });
    const conversation: AgentConversation = {
      id,
      title: initialTitle,
      created_at: new Date(),
      updated_at: new Date(),
      agent_name: agentName,
    };
    try {
      await db.conversations.put(conversation);
      console.log("[ChatService] Conversation created successfully");
    } catch (error) {
      console.error("[ChatService] Failed to create conversation:", error);
      throw error;
    }
    // Persist to backend (fire-and-forget)
    createConversationRemote(id, agentName, initialTitle).catch((err) => {
      console.warn("[ChatService] Backend create failed:", err);
    });
    return id;
  },

  async updateConversationTitle(id: string, title: string, agentName?: string) {
    await db.conversations.update(id, { title, updated_at: new Date() });
    // The DynamoDB-backed handler needs agent_id to build the partition
    // key. Prefer the explicit value from the caller (component already
    // knows it); fall back to the Dexie record only if not provided.
    let agentId = agentName;
    if (!agentId) {
      const existing = await db.conversations.get(id);
      agentId = existing?.agent_name;
    }
    if (!agentId) {
      console.warn(
        "[ChatService] updateConversationTitle: missing agent_name for",
        id,
      );
    }
    updateConversationTitleRemote(id, title, agentId).catch((err) => {
      console.warn("[ChatService] Backend title update failed:", err);
    });
  },

  /**
   * Fetch conversations from backend and upsert into Dexie.
   * Called on mount / refresh to hydrate local cache from DocumentDB.
   */
  async syncConversationsFromBackend(agentName?: string): Promise<void> {
    try {
      const backendConvs = await listConversations(agentName);
      if (backendConvs.length > 0) {
        console.log(
          `[ChatService] Synced ${backendConvs.length} conversations from backend`,
        );
        // The list endpoint omits agent_id per conversation, but we
        // already filtered by it server-side. Fall back to the queried
        // agentName so Dexie's agent_name index has a value to match.
        const mapped = backendConvs.map((bc) => {
          const conv = mapBackendConversation(bc);
          if (!conv.agent_name && agentName) {
            conv.agent_name = agentName;
          }
          return conv;
        });
        await db.conversations.bulkPut(mapped);
      }
    } catch (error) {
      console.warn("[ChatService] Backend conversation sync failed:", error);
    }
  },

  /**
   * Fetch messages from backend and upsert into Dexie.
   * Called when selecting a conversation to ensure messages are hydrated.
   */
  async syncMessagesFromBackend(
    sessionId: string,
    agentId?: string,
    limit?: number,
  ): Promise<void> {
    try {
      const backendMsgs = await loadMessages(sessionId, agentId, limit);
      if (backendMsgs.length > 0) {
        console.log(
          `[ChatService] Synced ${backendMsgs.length} messages from backend for ${sessionId}`,
        );
        const mapped = backendMsgs.map(mapBackendMessage);
        const cleaned = mapped.map((m) => {
          const c = JSON.parse(JSON.stringify(m));
          if (c.timestamp) c.timestamp = new Date(c.timestamp);

          // The backend may omit session_id from individual message objects
          // (treating it as implicit from the request URL). Without it, Dexie
          // cannot index the record under the 'metadata.session_id' keypath,
          // making it invisible to the where().equals() query used in getMessages.
          // Always stamp the known sessionId so every synced message is queryable.
          if (c.metadata && !c.metadata.session_id) {
            c.metadata.session_id = sessionId;
          }

          return c;
        });

        // Deduplicate: remove local-only messages that match incoming
        // backend messages by role + content but have a different ID.
        // This happens because optimistic saves use a client UUID while
        // the backend assigns its own message_id/turn_id.
        const backendIds = new Set(cleaned.map((m) => m.id));
        const localMsgs = await db.messages
          .where("metadata.session_id")
          .equals(sessionId)
          .toArray();

        // Rich fields that the backend's /chat/interactions endpoint doesn't persist.
        // When the local Dexie record has them but the backend doesn't, keep the local
        // value so features like "Show Data", inline charts, and iframes survive a sync.
        const RICH_FIELDS = [
          "data",
          "output",
          "code",
          "htmlResponse",
          "tool_calls",
          "sources",
          "documents",
        ] as const;
        const isBackendMissing = (v: unknown): boolean =>
          v == null || (Array.isArray(v) && v.length === 0);
        const mergeRichFields = (
          target: AgentMessage,
          source: AgentMessage,
        ) => {
          for (const field of RICH_FIELDS) {
            const tv = target[field];
            const sv = source[field];
            if (isBackendMissing(tv) && sv != null) {
              (target as unknown as Record<string, unknown>)[field] = sv;
            }
          }
        };

        // Pass 1: same-ID records (assistant messages keyed by turn_id). The
        // bulkPut below overwrites them, so carry forward rich fields first.
        const localById = new Map(localMsgs.map((m) => [m.id, m]));
        for (const c of cleaned) {
          const local = localById.get(c.id);
          if (local) mergeRichFields(c as AgentMessage, local);
        }

        // Pass 2: content-match dedup (different IDs). Carry rich fields into
        // the backend record before deleting the local one.
        const usedBackendIds = new Set<string>();
        const toDelete: string[] = [];

        for (const local of localMsgs) {
          if (backendIds.has(local.id)) continue; // already handled in Pass 1

          // Match by role + content only.
          // The timestamp is intentionally excluded: the backend may record
          // message timestamps at turn-start (before the AI generates a response),
          // so assistant messages can differ by many seconds from our local
          // `new Date()` snapshot. A strict time window causes the local copy
          // to survive alongside the backend copy, producing duplicate bubbles.
          const matchingBackend = cleaned.find(
            (backend) =>
              !usedBackendIds.has(backend.id) &&
              backend.role === local.role &&
              backend.content === local.content,
          );

          // Only delete the local copy when there is an indexable replacement
          // in the backend payload (session_id was stamped above, so this
          // guard catches any edge case where stamping was skipped).
          if (matchingBackend?.metadata?.session_id) {
            mergeRichFields(matchingBackend as AgentMessage, local);
            toDelete.push(local.id);
            usedBackendIds.add(matchingBackend.id);
          }
        }

        if (toDelete.length > 0) {
          await db.messages.bulkDelete(toDelete);
        }

        await db.messages.bulkPut(cleaned);
      }
    } catch (error) {
      console.warn("[ChatService] Backend message sync failed:", error);
    }
  },

  /**
   * Read conversations from Dexie (local cache).
   * Used by liveQuery for reactive updates.
   */
  async _getLocalConversations(
    agentName?: string,
  ): Promise<AgentConversation[]> {
    try {
      if (agentName) {
        try {
          return await db.conversations
            .where("agent_name")
            .equals(agentName)
            .reverse()
            .sortBy("updated_at");
        } catch {
          const all = await db.conversations
            .orderBy("updated_at")
            .reverse()
            .toArray();
          return all.filter((c) => c.agent_name === agentName);
        }
      }
      return await db.conversations.orderBy("updated_at").reverse().toArray();
    } catch (error) {
      console.error("[ChatService] Error getting local conversations:", error);
      return [];
    }
  },

  /**
   * Get conversations — backend-first with Dexie fallback.
   * Prefer using syncConversationsFromBackend + _getLocalConversations for liveQuery compat.
   */
  async getConversations(agentName?: string): Promise<AgentConversation[]> {
    await this.syncConversationsFromBackend(agentName);
    return this._getLocalConversations(agentName);
  },

  /**
   * Get messages — backend-first with Dexie fallback.
   * @param limit - if provided, only sync and return the last N messages (for pagination)
   */
  async getMessages(
    sessionId: string,
    agentId?: string,
    limit?: number,
  ): Promise<AgentMessage[]> {
    await this.syncMessagesFromBackend(sessionId, agentId, limit);
    const msgs = await db.messages
      .where("metadata.session_id")
      .equals(sessionId)
      .sortBy("timestamp");
    // Multi-level sort to fix interleaving of same-second backend messages:
    // 1. Primary: timestamp ascending
    // 2. Secondary: turn_id ascending (keeps same-turn messages adjacent)
    // 3. Tertiary: role order (user=0, assistant=1) as final tiebreaker
    const roleOrder: Record<string, number> = { user: 0, assistant: 1 };
    const sorted = msgs.sort((a, b) => {
      const ta = new Date(a.timestamp).getTime();
      const tb = new Date(b.timestamp).getTime();
      if (ta !== tb) return ta - tb;
      // Secondary: turn_id — group messages from the same turn together
      const tidA = (a as AgentMessage & { turn_id?: string }).turn_id ?? "";
      const tidB = (b as AgentMessage & { turn_id?: string }).turn_id ?? "";
      if (tidA && tidB && tidA !== tidB) {
        return tidA < tidB ? -1 : 1;
      }
      // Tertiary: role order
      return (roleOrder[a.role] ?? 0) - (roleOrder[b.role] ?? 0);
    });
    if (limit && sorted.length > limit) {
      return sorted.slice(-limit);
    }
    return sorted;
  },

  async saveMessage(message: AgentMessage) {
    if (!message.metadata?.session_id) {
      console.warn("Cannot save message without session_id", message);
      return;
    }
    // Sanitize to ensure no proxies or non-clonable types (Svelte 5 + Dexie)
    const cleanMessage = JSON.parse(JSON.stringify(message));
    if (cleanMessage.timestamp) {
      cleanMessage.timestamp = new Date(cleanMessage.timestamp);
    }

    try {
      await db.messages.put(cleanMessage);
    } catch (error) {
      console.error("Failed to save message to DB:", error, message);
      return;
    }

    // Update conversation timestamp and last message snippet
    await db.conversations.update(message.metadata.session_id, {
      updated_at: new Date(),
      last_message: message.content.substring(0, 100),
    });
  },

  async deleteConversation(id: string, agentName?: string) {
    let agentId = agentName;
    if (!agentId) {
      const existing = await db.conversations.get(id);
      agentId = existing?.agent_name;
    }
    // Delete from Dexie
    await db.transaction("rw", db.conversations, db.messages, async () => {
      await db.messages.where("metadata.session_id").equals(id).delete();
      await db.conversations.delete(id);
    });
    // Also delete from backend (fire-and-forget). DynamoDB needs agent_id
    // to build the partition key.
    deleteConversationRemote(id, agentId).catch((err) => {
      console.warn("[ChatService] Backend delete failed:", err);
    });
  },

  async deleteMessage(
    sessionId: string,
    turnId: string,
    messageId: string,
    agentName?: string,
  ) {
    let agentId = agentName;
    if (!agentId) {
      const conv = await db.conversations.get(sessionId);
      agentId = conv?.agent_name;
    }
    // Delete from Dexie by message ID
    try {
      await db.messages.delete(messageId);
      console.log("[ChatService] Message deleted from local DB:", messageId);
    } catch (error) {
      console.error(
        "[ChatService] Failed to delete message from local DB:",
        error,
      );
    }
    // Delete from backend (fire-and-forget)
    if (turnId) {
      deleteMessageRemote(sessionId, turnId, agentId).catch((err) => {
        console.warn("[ChatService] Backend message delete failed:", err);
      });
    }
  },

  async clearHistory() {
    await db.messages.clear();
    await db.conversations.clear();
  },
};
