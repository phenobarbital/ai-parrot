/**
 * Typed wrappers over `apiClient` for the agent-management endpoints
 * (TASK-2586, FEAT-475). Every response type is generated
 * (`$lib/types/generated/*`) — no hand-written payload types.
 *
 * Wire contract (verified against `parrot.handlers.bots.ChatbotHandler`
 * and `parrot.server.ui.catalog.AdminCatalogHandler`):
 *   GET    /api/v1/bots[?include_disabled=true]  -> BotsListResponse
 *   GET    /api/v1/bots/{name}                   -> BotAgentItem
 *   PUT    /api/v1/bots        {storage:"database", ...}  -> 201 BotMutationResponse
 *   POST   /api/v1/bots/{name} {...changed fields}         -> 200 BotMutationResponse
 *   DELETE /api/v1/bots/{name}                    -> 200 BotMutationResponse
 *   GET    /api/v1/agent_tools                    -> ToolsListResponse
 *   GET    /api/v1/admin/catalog                  -> AdminCatalog
 */
import apiClient from "$lib/api/http";
import type { AdminCatalog } from "$lib/types/generated/AdminCatalog";
import type { BotAgentItem } from "$lib/types/generated/BotAgentItem";
import type { BotMutationResponse } from "$lib/types/generated/BotMutationResponse";
import type { BotsListResponse } from "$lib/types/generated/BotsListResponse";
import type { BotWritePayload } from "$lib/types/generated/BotWritePayload";
import type { ToolsListResponse } from "$lib/types/generated/ToolsListResponse";

/** GET /api/v1/bots — optionally including disabled DB agents. */
export async function listAgents(opts?: {
  includeDisabled?: boolean;
}): Promise<BotsListResponse> {
  const url = opts?.includeDisabled ? "/api/v1/bots?include_disabled=true" : "/api/v1/bots";
  const { data } = await apiClient.get<BotsListResponse>(url);
  return data;
}

/** GET /api/v1/bots/{name} — single agent, DB checked before registry. */
export async function getAgent(name: string): Promise<BotAgentItem> {
  const { data } = await apiClient.get<BotAgentItem>(
    `/api/v1/bots/${encodeURIComponent(name)}`,
  );
  return data;
}

/**
 * PUT /api/v1/bots — create a database agent. The caller supplies the full
 * payload including `storage: "database"` (see `AgentFormState.payload()`);
 * the backend may slugify/deduplicate `name` — the response's `name` is
 * the one actually persisted.
 */
export async function createAgent(body: BotWritePayload): Promise<BotMutationResponse> {
  const { data } = await apiClient.put<BotMutationResponse>("/api/v1/bots", body);
  return data;
}

/**
 * POST /api/v1/bots/{name} — update an existing database agent. `patch`
 * should be the changed-fields-only diff (see `AgentFormState.diff()`);
 * the handler applies every key it receives (`agent.set(key, val)`), so
 * sending unchanged fields risks clobbering concurrent edits.
 */
export async function updateAgent(
  name: string,
  patch: Partial<BotWritePayload>,
): Promise<BotMutationResponse> {
  const { data } = await apiClient.post<BotMutationResponse>(
    `/api/v1/bots/${encodeURIComponent(name)}`,
    patch,
  );
  return data;
}

/**
 * DELETE /api/v1/bots/{name} — database agents only; a repository registry
 * agent responds 403 (surfaced via `ApiError`, never retried).
 */
export async function deleteAgent(name: string): Promise<BotMutationResponse> {
  const { data } = await apiClient.delete<BotMutationResponse>(
    `/api/v1/bots/${encodeURIComponent(name)}`,
  );
  return data;
}

/** GET /api/v1/agent_tools — the tools picker's option list. */
export async function listTools(): Promise<ToolsListResponse> {
  const { data } = await apiClient.get<ToolsListResponse>("/api/v1/agent_tools");
  return data;
}

/** GET /api/v1/admin/catalog — LLM providers / enums / KB class options. */
export async function getCatalog(): Promise<AdminCatalog> {
  const { data } = await apiClient.get<AdminCatalog>("/api/v1/admin/catalog");
  return data;
}
