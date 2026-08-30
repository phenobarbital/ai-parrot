import type { AxiosInstance } from "axios";
import apiClient from "./http";
import type { AgentChatRequest, AgentChatResponse } from "$lib/types/agent";
import type {
  DatasetEntry,
  DatasetListResponse,
  DatasetAddRequest,
  DatasetAddResponse,
} from "$lib/types/dataset";

const BASE_PATH = "/api/v1/agents/chat";
const VOICE_PATH = "/api/v1/agents/voice";

export interface VoiceNoteOptions {
  /** File name for the audio part — MUST carry a valid extension (.webm, .ogg,
   *  .wav, …) as a fallback to MIME-type detection on the server. */
  filename?: string;
  /** Conversation id — keeps the voice turn in the same thread. */
  sessionId?: string;
  /** Client-generated message id (used as turn_id for dedup). */
  messageId?: string;
  /** Optional STT/TTS/format selectors (opt-in; require server extras). */
  sttBackend?: string;
  ttsBackend?: string;
  /** Desired output container, e.g. "audio/wav". Server returns the REAL one. */
  audioFormat?: string;
  /**
   * When true, this voice note also drives the LiveAvatar (FEAT-169).
   * Appends avatar=true to the form so the backend routes the audio through
   * the avatar pipeline. Callers MUST NOT play audio_base64 in this mode —
   * the room delivers audio via LiveKit tracks.
   */
  avatar?: boolean;
  /**
   * Tenant identifier forwarded to the avatar pipeline (FEAT-169).
   * Value: clientStore.getClient()?.slug. Omit when undefined.
   */
  tenantId?: string;
}

/**
 * Send a voice note to the AgentTalk Voice endpoint (FEAT-231).
 *
 * Round-trip REST: audio → STT → text agent → TTS → JSON envelope. The response
 * is the standard `AgentChatResponse` envelope plus `audio_base64`/`audio_format`
 * when TTS succeeds. NEVER send `query` alongside the audio — text wins and the
 * audio is discarded (answer comes back text-only).
 *
 * Route is registered under an optional server guard: a 404 means the voice
 * stack isn't installed — treat it as feature detection and hide the mic UI.
 */
export const sendVoiceNote = async (
  agentName: string,
  audio: Blob,
  options: VoiceNoteOptions = {},
  client?: AxiosInstance,
  signal?: AbortSignal,
): Promise<AgentChatResponse> => {
  const http = client ?? apiClient;
  const form = new FormData();
  form.append("audio", audio, options.filename ?? "voice-note.webm");
  if (options.sessionId) form.append("session_id", options.sessionId);
  if (options.messageId) form.append("message_id", options.messageId);
  if (options.sttBackend) form.append("stt_backend", options.sttBackend);
  if (options.ttsBackend) form.append("tts_backend", options.ttsBackend);
  if (options.audioFormat) form.append("audio_format", options.audioFormat);
  // FEAT-169: avatar pipeline fields (no-op when absent — purely additive)
  if (options.avatar) form.append("avatar", "true");
  if (options.tenantId) form.append("tenant_id", options.tenantId);

  const response = await http.post<AgentChatResponse>(
    `${VOICE_PATH}/${agentName}`,
    form,
    {
      headers: { "Content-Type": "multipart/form-data" },
      signal,
    },
  );
  return response.data;
};

/**
 * Feature-detect the AgentTalk Voice endpoint without any side effects.
 *
 * The voice route is registered only when the server has the voice stack
 * installed (`ai-parrot-integrations[voice]`); otherwise the path doesn't exist
 * and the server returns `404`. We probe with a `HEAD` request: since the route
 * only accepts `POST`, an existing route answers `405 Method Not Allowed` (or
 * another non-404 status), while a missing route answers `404`. No audio is
 * sent, no transcription runs, no message is created.
 *
 * Returns `true` when voice is available (show the mic), `false` on `404` or any
 * inconclusive/network error (hide the mic — conservative default).
 */
export const checkVoiceSupport = async (
  agentName: string,
  client?: AxiosInstance,
  signal?: AbortSignal,
): Promise<boolean> => {
  const http = client ?? apiClient;
  try {
    await http.head(`${VOICE_PATH}/${agentName}`, { signal });
    return true; // 2xx (unlikely for HEAD on a POST route) — route exists
  } catch (err: any) {
    if (err?.code === "ERR_CANCELED") return false;
    const status = err?.response?.status ?? err?.status;
    // 404 ⇒ route not registered ⇒ voice unavailable. Any other status
    // (405, 401, 403, 200…) means the route EXISTS ⇒ voice is available.
    return status !== undefined && status !== 404;
  }
};

export const chatWithAgent = async (
  agentName: string,
  request: AgentChatRequest,
  client?: AxiosInstance,
  signal?: AbortSignal,
): Promise<AgentChatResponse> => {
  const http = client ?? apiClient;
  const response = await http.post<AgentChatResponse>(
    `${BASE_PATH}/${agentName}`,
    { ...request, output_format: "json" },
    { signal },
  );
  return response.data;
};

export const callAgentMethod = async (
  agentName: string,
  methodName: string,
  request: AgentChatRequest,
  client?: AxiosInstance,
  signal?: AbortSignal,
): Promise<AgentChatResponse> => {
  const http = client ?? apiClient;
  const response = await http.post<AgentChatResponse>(
    `${BASE_PATH}/${agentName}/${methodName}`,
    { ...request, output_format: "json" },
    { signal },
  );
  return response.data;
};

export const refreshAgentData = async (
  agentName: string,
  client?: AxiosInstance,
): Promise<any> => {
  const http = client ?? apiClient;
  const response = await http.patch(`${BASE_PATH}/${agentName}`);
  return response.data;
};

export const uploadAgentData = async (
  agentName: string,
  formData: FormData,
  client?: AxiosInstance,
): Promise<any> => {
  const http = client ?? apiClient;
  const response = await http.put(`${BASE_PATH}/${agentName}`, formData, {
    headers: {
      "Content-Type": "multipart/form-data",
    },
  });
  return response.data;
};

export const addAgentQuery = async (
  agentName: string,
  slug: string,
  client?: AxiosInstance,
): Promise<any> => {
  const http = client ?? apiClient;
  const response = await http.put(`${BASE_PATH}/${agentName}`, { slug });
  return response.data;
};

export const sendAgentFeedback = async (
  feedbackData: any,
  client?: AxiosInstance,
): Promise<any> => {
  const http = client ?? apiClient;
  const response = await http.post(`/api/v1/bot_feedback`, feedbackData);
  return response.data;
};

// --- MCP Server Management ---

export interface MCPServerEntry {
  name: string;
  url?: string;
  transport?: string;
  auth_type?: string;
  auth_config?: Record<string, string>;
  headers?: Record<string, string>;
  allowed_tools?: string[] | null;
  blocked_tools?: string[] | null;
  description?: string;
  // Read-only runtime fields (from GET)
  connected?: boolean;
  tool_count?: number;
}

export const getAgentMCPServers = async (
  agentName: string,
  client?: AxiosInstance,
): Promise<{ agent: string; mcp_servers: MCPServerEntry[] }> => {
  const http = client ?? apiClient;
  const response = await http.get(`${BASE_PATH}/${agentName}/mcp_servers`);
  return response.data;
};

export const saveAgentMCPServers = async (
  agentName: string,
  mcpServers: MCPServerEntry[],
  client?: AxiosInstance,
): Promise<unknown> => {
  const http = client ?? apiClient;
  const response = await http.patch(`${BASE_PATH}/${agentName}`, {
    mcp_servers: mcpServers,
  });
  return response.data;
};

// --- Dataset Management (DatasetManagerHandler) ---

const DATASET_PATH = "/api/v1/agents/datasets";

/** List all datasets for an agent */
export const listDatasets = async (
  agentId: string,
  client?: AxiosInstance,
): Promise<DatasetListResponse> => {
  const http = client ?? apiClient;
  const response = await http.get<DatasetListResponse>(
    `${DATASET_PATH}/${agentId}`,
  );
  return response.data;
};

/** Activate or deactivate a dataset */
export const toggleDataset = async (
  agentId: string,
  name: string,
  is_active: boolean,
  client?: AxiosInstance,
): Promise<{ success: boolean }> => {
  const http = client ?? apiClient;
  const response = await http.patch<{ success: boolean }>(
    `${DATASET_PATH}/${agentId}`,
    { name, is_active },
  );
  return response.data;
};

/** Upload a CSV or Excel file as a new dataset */
export const uploadDataset = async (
  agentId: string,
  formData: FormData,
  client?: AxiosInstance,
): Promise<DatasetEntry> => {
  const http = client ?? apiClient;
  const response = await http.put<DatasetEntry>(
    `${DATASET_PATH}/${agentId}`,
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return response.data;
};

/** Add a dataset from query slug, SQL, or datasource config (table, smartsheet, etc.) */
export const addQueryDataset = async (
  agentId: string,
  payload: DatasetAddRequest,
  client?: AxiosInstance,
): Promise<DatasetAddResponse> => {
  const http = client ?? apiClient;
  const response = await http.post<DatasetAddResponse>(
    `${DATASET_PATH}/${agentId}`,
    payload,
  );
  return response.data;
};

/** Delete a dataset by name */
export const deleteDataset = async (
  agentId: string,
  name: string,
  client?: AxiosInstance,
): Promise<{ success: boolean }> => {
  const http = client ?? apiClient;
  const response = await http.delete<{ success: boolean }>(
    `${DATASET_PATH}/${agentId}`,
    { data: { name } },
  );
  return response.data;
};
