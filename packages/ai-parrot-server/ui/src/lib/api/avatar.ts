/**
 * Avatar API client — FEAT-169 LiveAvatar Integration
 *
 * Typed HTTP layer for the three avatar backend calls:
 *   POST /api/v1/agents/avatar/{id}/start
 *   POST /api/v1/agents/avatar/{id}/stop
 *   POST /api/v1/agents/voice/{id}   (avatar=true text turn)
 *
 * Auth is injected by the http.ts interceptor — never set Authorization manually.
 * Never reads agent_token / ws_url / session_token (server secrets).
 */

import type { AxiosInstance } from "axios";
import apiClient from "./http";
import type {
  AgentChatResponse,
  AgentMessage,
  AgentToolCall,
} from "$lib/types/agent";

const AVATAR_PATH = "/api/v1/agents/avatar";
const VOICE_PATH = "/api/v1/agents/voice";
const VIEWER_PATH = "/api/v1/avatar";

// ── Data Models ───────────────────────────────────────────────────────────────

/**
 * Response of POST /api/v1/agents/avatar/{agent_id}/start
 * Contains viewer credentials ONLY — never agent_token, ws_url, or session_token.
 */
export interface AvatarStartResponse {
  livekit_url: string; // wss://<project>.livekit.cloud
  client_token: string; // JWT, subscribe-only — safe to expose to the client
  session_id: string; // echoes the AgentChat session_id
}

/**
 * Response of POST /api/v1/agents/avatar/{agent_id}/voice-native/start (Phase C).
 *
 * Unlike {@link AvatarStartResponse}, the `token` here is **publish(microphone)
 * + subscribe** — it lets the browser publish its mic so the server-side LiveKit
 * Agents worker can run STT/VAD/turn-detection. Never carries server secrets.
 */
export interface VoiceNativeStartResponse {
  livekit_url: string; // wss://<project>.livekit.cloud
  token: string; // JWT, publish(microphone)+subscribe
  session_id: string; // echoes the AgentChat session_id (room + WS channel key)
}

/**
 * Structured output pushed over the AgentChat WS (`/ws/userinfo`) on the channel
 * keyed by `session_id` during a Phase C voice-native turn. Mirrors the backend
 * `StructuredOutputMessage.model_dump()` (FEAT-243). Voice-only turns emit
 * NOTHING here — the user just hears the avatar.
 */
export interface StructuredOutputMessage {
  /** Discriminator: "tool_call" | "canvas" | "data" | <output_mode> (chart/map/table/…). */
  type: string;
  session_id: string;
  payload: {
    response: string | null;
    data: unknown; // already JSON-safe (frames → records)
    code: string | null;
    artifact_id: string | null;
    output_mode: string | null;
    tool_calls: string[]; // tool names only
  };
  turn_id: string | null; // currently == artifact_id
}

/**
 * A subscribe-only viewer token for a LITE avatar room (Mode C multi-viewer).
 * Returned by {@link mintViewerTokens} from POST /api/v1/avatar/{id}/viewers.
 */
export interface ViewerToken {
  identity: string; // unique identity in the LiveKit room
  livekit_url: string; // wss://<project>.livekit.cloud
  client_token: string; // JWT, subscribe-only — safe to expose to the client
}

/** Thrown on 403 (tenant has no avatar opt-in). Hosts degrade to text/voice. */
export class AvatarDisabledError extends Error {
  constructor(message = "Avatar not enabled for this tenant") {
    super(message);
    this.name = "AvatarDisabledError";
  }
}

/** Thrown on 503 (stack/env unavailable). Hosts show a soft "unavailable" fallback. */
export class AvatarUnavailableError extends Error {
  constructor(message = "Avatar stack unavailable") {
    super(message);
    this.name = "AvatarUnavailableError";
  }
}

/**
 * Thrown when the avatar provider (LiveAvatar SaaS) refuses to start the session
 * because the account has no available credits.
 *
 * The backend surfaces the upstream LiveAvatar error
 * `403 {code:4033, message:"No credits available for start session"}`.
 * Hosts should show a clear "avatar unavailable — no credits" message and fall
 * back to a non-avatar transport (Voice · WS).
 */
export class AvatarNoCreditsError extends Error {
  constructor(message = "The avatar service has no available credits") {
    super(message);
    this.name = "AvatarNoCreditsError";
  }
}

export type AvatarStatus =
  | "idle"
  | "connecting"
  | "live"
  | "disabled"
  | "error";

// ── Error helpers ───────────────────────────────────────────────────────────────

/**
 * Extract a human-readable message from an axios/ApiError body, when present.
 * Tolerates string bodies and the common `{message}` / `{detail}` /
 * `{data:{message}}` JSON envelopes the backend may forward from upstream.
 */
function extractErrorMessage(err: any): string | undefined {
  const data = err?.response?.data ?? err?.data;
  if (!data) return undefined;
  if (typeof data === "string") return data;
  if (typeof data === "object") {
    const d = data as Record<string, any>;
    return (
      (typeof d.message === "string" && d.message) ||
      (typeof d.detail === "string" && d.detail) ||
      (d.data && typeof d.data.message === "string" && d.data.message) ||
      undefined
    );
  }
  return undefined;
}

/**
 * True when an error represents the LiveAvatar "no credits" condition.
 * Detected by an explicit `402` status, or by the upstream LiveAvatar code
 * `4033` / "No credits available …" message forwarded in the body (works even
 * when the backend wraps it in a generic 500, as long as the message survives).
 */
export function isNoCreditsError(err: any): boolean {
  const status = err?.status ?? err?.response?.status;
  if (status === 402) return true;
  const msg = (extractErrorMessage(err) ?? "").toLowerCase();
  return (
    msg.includes("no credits") ||
    msg.includes("4033") ||
    (msg.includes("credit") && msg.includes("session"))
  );
}

// ── API Functions ─────────────────────────────────────────────────────────────

/**
 * Start an avatar session for the given agent.
 *
 * POSTs to /api/v1/agents/avatar/{agentId}/start with the session_id and
 * optional tenant_id. Returns { livekit_url, client_token, session_id }.
 *
 * Error mapping:
 *   403 → AvatarDisabledError   (tenant has no opt-in)
 *   503 → AvatarUnavailableError (stack/env unavailable)
 *   other non-2xx → generic Error
 */
export async function startAvatarSession(
  agentId: string,
  sessionId: string,
  tenantId?: string,
  client?: AxiosInstance,
  signal?: AbortSignal,
  avatar?: boolean,
): Promise<AvatarStartResponse> {
  const http = client ?? apiClient;
  try {
    const body: Record<string, unknown> = { session_id: sessionId };
    if (tenantId) body.tenant_id = tenantId;
    // FEAT-256: when the host turns the avatar OFF, tell the backend so it skips
    // LiveAvatar and publishes the bot's audio directly (no avatar, no credits).
    // Omitted → backend defaults to avatar-on (back-compat).
    if (avatar !== undefined) body.avatar = avatar;

    const res = await http.post(`${AVATAR_PATH}/${agentId}/start`, body, {
      signal,
    });
    return res.data as AvatarStartResponse;
  } catch (err: any) {
    // http.ts interceptor converts HTTP errors to ApiError with .status field
    const status = err?.status ?? err?.response?.status;
    // No-credits is checked first: it may arrive as a 403/500 carrying the
    // upstream LiveAvatar message, which must NOT be mistaken for "disabled".
    if (isNoCreditsError(err)) throw new AvatarNoCreditsError();
    if (status === 403) throw new AvatarDisabledError();
    if (status === 503) throw new AvatarUnavailableError();
    throw err;
  }
}

/**
 * Start a voice-native (Phase C) avatar session for the given agent.
 *
 * POSTs to /api/v1/agents/avatar/{agentId}/voice-native/start. The backend mints
 * a publish(microphone)+subscribe token AND dispatches the LiveKit Agents worker
 * into the room. Returns { livekit_url, token, session_id }.
 *
 * Error mapping mirrors {@link startAvatarSession}:
 *   403 → AvatarDisabledError   (tenant has no opt-in)
 *   503 → AvatarUnavailableError (stack/env/dispatch unavailable)
 *   other non-2xx → generic Error
 */
export async function startVoiceNativeSession(
  agentId: string,
  sessionId: string,
  tenantId?: string,
  client?: AxiosInstance,
  signal?: AbortSignal,
): Promise<VoiceNativeStartResponse> {
  const http = client ?? apiClient;
  try {
    const body: Record<string, string> = { session_id: sessionId };
    if (tenantId) body.tenant_id = tenantId;

    const res = await http.post(
      `${AVATAR_PATH}/${agentId}/voice-native/start`,
      body,
      { signal },
    );
    return res.data as VoiceNativeStartResponse;
  } catch (err: any) {
    const status = err?.status ?? err?.response?.status;
    if (status === 403) throw new AvatarDisabledError();
    if (status === 503) throw new AvatarUnavailableError();
    throw err;
  }
}

/**
 * Narrow an arbitrary AgentChat WS frame to a Phase C {@link StructuredOutputMessage}.
 *
 * The shared `/ws/userinfo` socket carries control frames (auth_success,
 * subscribed, …) and other chat events. A structured output is recognised by a
 * matching `session_id` plus the fixed `payload` shape produced by the backend.
 */
export function isStructuredOutputMessage(
  msg: unknown,
  sessionId: string,
): msg is StructuredOutputMessage {
  if (!msg || typeof msg !== "object") return false;
  const m = msg as Record<string, unknown>;
  if (m.session_id !== sessionId) return false;
  if (typeof m.type !== "string") return false;
  const p = m.payload;
  return (
    !!p &&
    typeof p === "object" &&
    "output_mode" in (p as object) &&
    "tool_calls" in (p as object)
  );
}

/**
 * Adapt a Phase C {@link StructuredOutputMessage} into an {@link AgentMessage}
 * so it can be rendered by the existing ChatBubble artifact pipeline.
 *
 * The backend payload (P4-provisional) carries `data` but no separate `output`
 * field. ChatBubble gates chart/map renderers on `message.output`, so we surface
 * `data` as `output` ONLY when it is a config-like object (not an array of rows);
 * tabular modes render from `data` directly. Unknown/voice-only turns never reach
 * here (see {@link isStructuredOutputMessage}).
 */
export function structuredOutputToAgentMessage(
  msg: StructuredOutputMessage,
): AgentMessage {
  const p = msg.payload;
  // ai-parrot (TASK-2592): `output`/`arguments` were `null` in navigator —
  // the generated `AgentToolCall` type (TASK-2590, from `AgentTalk`'s dict
  // envelope contract) types both as an optional object, not nullable;
  // `undefined` carries the same "absent" meaning at every consumer.
  const toolCalls: AgentToolCall[] = (p.tool_calls ?? []).map((name) => ({
    name,
    status: "completed",
    output: undefined,
    arguments: undefined,
  }));

  // Heuristic: chart/map configs are objects; tabular data is an array of records.
  const dataIsConfigObject =
    !!p.data && typeof p.data === "object" && !Array.isArray(p.data);

  return {
    id: msg.turn_id ?? p.artifact_id ?? crypto.randomUUID(),
    role: "assistant",
    content: p.response ?? "",
    timestamp: new Date(),
    data: p.data ?? null,
    code: p.code ?? null,
    output: dataIsConfigObject ? p.data : undefined,
    output_mode: p.output_mode ?? undefined,
    tool_calls: toolCalls.length ? toolCalls : undefined,
    metadata: {
      model: "",
      provider: "",
      session_id: msg.session_id,
      turn_id: msg.turn_id ?? p.artifact_id ?? "",
      artifact_id: p.artifact_id ?? undefined,
    },
  };
}

/**
 * Stop an avatar session. Idempotent — resolves even on unknown-session or
 * network errors during teardown (must not throw on cleanup paths).
 *
 * POSTs to /api/v1/agents/avatar/{agentId}/stop with { session_id }.
 * Shared by Phase A and Phase C (the backend keys teardown by session_id).
 */
export async function stopAvatarSession(
  agentId: string,
  sessionId: string,
  client?: AxiosInstance,
): Promise<void> {
  const http = client ?? apiClient;
  try {
    await http.post(`${AVATAR_PATH}/${agentId}/stop`, {
      session_id: sessionId,
    });
  } catch {
    // Swallow all errors — teardown must never throw
  }
}

/**
 * Mint N subscribe-only viewer tokens for an active LITE avatar session (Mode C).
 *
 * POSTs to /api/v1/avatar/{agentId}/viewers with { session_id, count }.
 * Returns an array of ViewerToken objects (subscribe-only `client_token`s) that
 * can be handed to other browsers to join the SAME room as observers.
 *
 * Note: path is /api/v1/avatar (NO "agents" segment) — matches the backend route.
 *
 * Error mapping:
 *   400 → Error("Invalid request") (count out of range, missing session_id)
 *   403 → AvatarDisabledError   (tenant has no opt-in)
 *   404 → Error("Session not found")
 *   409 → Error("Session conflict")
 *   other non-2xx → generic Error
 */
export async function mintViewerTokens(
  agentId: string,
  sessionId: string,
  count = 1,
  client?: AxiosInstance,
): Promise<ViewerToken[]> {
  const http = client ?? apiClient;
  try {
    const res = await http.post(`${VIEWER_PATH}/${agentId}/viewers`, {
      session_id: sessionId,
      count,
    });
    const viewers = (res.data as { viewers: ViewerToken[] }).viewers ?? [];
    return viewers;
  } catch (err: any) {
    const status = err?.status ?? err?.response?.status;
    if (status === 400) throw new Error("Invalid request for viewer tokens");
    if (status === 403) throw new AvatarDisabledError();
    if (status === 404) throw new Error("Avatar session not found");
    if (status === 409) throw new Error("Avatar session conflict");
    throw err;
  }
}

/**
 * Send a text turn to the avatar voice endpoint.
 *
 * POSTs to /api/v1/agents/voice/{agentId} as multipart/form-data with:
 *   query, avatar="true", session_id, tenant_id (when provided).
 *
 * Returns the AgentChatResponse envelope. Callers MUST NOT play audio_base64
 * in avatar mode (the room delivers the audio via LiveKit tracks).
 */
export async function sendAvatarTextTurn(
  agentId: string,
  sessionId: string,
  query: string,
  tenantId?: string,
  client?: AxiosInstance,
  signal?: AbortSignal,
): Promise<AgentChatResponse> {
  const http = client ?? apiClient;
  const form = new FormData();
  form.append("query", query);
  form.append("avatar", "true");
  form.append("session_id", sessionId);
  if (tenantId) form.append("tenant_id", tenantId);

  const response = await http.post<AgentChatResponse>(
    `${VOICE_PATH}/${agentId}`,
    form,
    {
      headers: { "Content-Type": "multipart/form-data" },
      signal,
    },
  );
  return response.data;
}
