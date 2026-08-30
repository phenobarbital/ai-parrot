/**
 * User Prompts API Client
 *
 * CRUD operations for the /api/v1/agents/user_prompts endpoint.
 * Manages per-user prompts (keyed by user_id + chatbot_id or agent_id).
 */

import apiClient from "./http";
import type {
  Prompt,
  BackendPrompt,
  CreatePromptRequest,
  UpdatePromptRequest,
} from "$lib/types/prompt-library";
import { mapBackendPrompt } from "$lib/types/prompt-library";

const BASE_PATH = "/api/v1/agents/user_prompts";

/**
 * Query parameters for listing a user's prompts.
 * The backend model (navigator.users_prompts) has no agent_id column:
 * chatbot_id is a VARCHAR holding either a chatbot UUID or an agent slug.
 */
export interface GetUserPromptsParams {
  user_id: number;
  chatbot_id: string;
}

/**
 * Request payload to create a new user prompt.
 * user_id is enforced server-side from the session; sending it is optional.
 */
export interface CreateUserPromptRequest extends CreatePromptRequest {
  user_id: number;
}

/**
 * Fetch the current user's prompts for a given chatbot/agent.
 * GET /api/v1/agents/user_prompts?user_id={id}&chatbot_id={uuid}
 *
 * Returns an empty array on 404 to mirror prompt-library's public endpoint behavior.
 */
export async function getUserPrompts(
  params: GetUserPromptsParams,
): Promise<Prompt[]> {
  try {
    const { data } = await apiClient.get<BackendPrompt[]>(BASE_PATH, {
      params,
    });
    return (data || []).map(mapBackendPrompt);
  } catch (error: unknown) {
    if (isAxiosError(error) && error.response?.status === 404) {
      return [];
    }
    throw error;
  }
}

/**
 * Create a new user prompt.
 * PUT /api/v1/agents/user_prompts
 *
 * ModelView semantics are inverted vs REST: PUT inserts (no primary key in
 * the payload), POST updates an existing row by primary key.
 */
export async function createUserPrompt(
  request: CreateUserPromptRequest,
): Promise<Prompt> {
  const { data } = await apiClient.put<BackendPrompt | BackendPrompt[]>(
    BASE_PATH,
    request,
  );
  return mapBackendPrompt(Array.isArray(data) ? data[0] : data);
}

/**
 * Update an existing user prompt.
 * POST /api/v1/agents/user_prompts/{prompt_id}
 */
export async function updateUserPrompt(
  promptId: string,
  request: UpdatePromptRequest,
): Promise<Prompt> {
  const { data } = await apiClient.post<BackendPrompt | BackendPrompt[]>(
    `${BASE_PATH}/${encodeURIComponent(promptId)}`,
    request,
  );
  return mapBackendPrompt(Array.isArray(data) ? data[0] : data);
}

/**
 * Delete a user prompt.
 * DELETE /api/v1/agents/user_prompts/{prompt_id}
 */
export async function deleteUserPrompt(promptId: string): Promise<void> {
  await apiClient.delete(`${BASE_PATH}/${encodeURIComponent(promptId)}`);
}

/**
 * Type guard for Axios errors.
 */
function isAxiosError(
  error: unknown,
): error is { response?: { status: number } } {
  return (
    typeof error === "object" &&
    error !== null &&
    "response" in error &&
    typeof (error as { response?: unknown }).response === "object"
  );
}
