/**
 * API client for backend chat interaction persistence.
 *
 * Wraps the /api/v1/chat/interactions endpoints backed by
 * ChatStorage (Redis hot cache + DocumentDB cold storage).
 */

import apiClient from "./http";

// --- Backend response types ---

export interface BackendConversation {
  session_id: string;
  user_id: string;
  agent_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
  last_user_message?: string;
  last_assistant_message?: string;
  model?: string;
  provider?: string;
}

export interface BackendMessage {
  message_id: string;
  session_id: string;
  user_id: string;
  agent_id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  turn_id?: string;
  output?: any;
  output_mode?: string;
  data?: any;
  code?: string | null;
  model?: string;
  provider?: string;
  response_time_ms?: number;
  tool_calls?: any[];
  sources?: any[];
  metadata?: Record<string, any>;
  tools_used?: string[];
}

interface ListConversationsResponse {
  conversations: BackendConversation[];
  count: number;
}

interface LoadMessagesResponse {
  session_id: string;
  messages: BackendMessage[];
  count: number;
  metadata: BackendConversation | null;
}

// --- API functions ---

const BASE_PATH = "/api/v1/chat/interactions";

export async function listConversations(
  agentId?: string,
  limit: number = 50,
): Promise<BackendConversation[]> {
  const params: Record<string, string> = {};
  if (agentId) params.agent_id = agentId;
  if (limit !== 50) params.limit = String(limit);

  const { data } = await apiClient.get<ListConversationsResponse>(BASE_PATH, {
    params,
  });
  return data.conversations ?? [];
}

export async function loadMessages(
  sessionId: string,
  agentId?: string,
  limit: number = 100,
  offset: number = 0,
): Promise<BackendMessage[]> {
  const params: Record<string, string> = {};
  if (agentId) params.agent_id = agentId;
  if (limit !== 100) params.limit = String(limit);
  if (offset > 0) params.offset = String(offset);

  const { data } = await apiClient.get<LoadMessagesResponse>(
    `${BASE_PATH}/${sessionId}`,
    { params },
  );
  return data.messages ?? [];
}

export async function createConversationRemote(
  sessionId: string,
  agentId: string,
  title: string = "New Conversation",
): Promise<boolean> {
  try {
    await apiClient.post(BASE_PATH, {
      session_id: sessionId,
      agent_id: agentId,
      title,
    });
    return true;
  } catch {
    console.warn("[chatInteraction] createConversationRemote failed");
    return false;
  }
}

export async function updateConversationTitleRemote(
  sessionId: string,
  title: string,
  agentId?: string,
): Promise<boolean> {
  const body: Record<string, string> = { title };
  if (agentId) body.agent_id = agentId;
  try {
    await apiClient.put(`${BASE_PATH}/${sessionId}`, body);
    return true;
  } catch {
    console.warn("[chatInteraction] updateConversationTitleRemote failed");
    return false;
  }
}

export async function deleteConversationRemote(
  sessionId: string,
  agentId?: string,
): Promise<boolean> {
  const params: Record<string, string> = {};
  if (agentId) params.agent_id = agentId;

  try {
    await apiClient.delete(`${BASE_PATH}/${sessionId}`, { params });
    return true;
  } catch {
    console.warn("[chatInteraction] deleteConversationRemote failed");
    return false;
  }
}

export async function deleteMessageRemote(
  sessionId: string,
  turnId: string,
  agentId?: string,
): Promise<boolean> {
  const body: Record<string, string> = {
    action: "delete_turn",
    turn_id: turnId,
  };
  if (agentId) body.agent_id = agentId;
  try {
    await apiClient.patch(`${BASE_PATH}/${sessionId}`, body);
    return true;
  } catch {
    console.warn("[chatInteraction] deleteMessageRemote failed");
    return false;
  }
}

export const chatInteractionApi = {
  listConversations,
  loadMessages,
  createConversation: createConversationRemote,
  updateConversationTitle: updateConversationTitleRemote,
  deleteConversation: deleteConversationRemote,
  deleteMessage: deleteMessageRemote,
};
