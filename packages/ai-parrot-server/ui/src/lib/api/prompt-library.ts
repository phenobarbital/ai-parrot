/**
 * Prompt Library API Client
 *
 * CRUD operations for the /api/v1/prompt_library endpoint.
 * Manages public (system) prompts that are synced with the backend.
 */

import apiClient from "./http";
import type {
  Prompt,
  BackendPrompt,
  CreatePromptRequest,
  UpdatePromptRequest,
} from "$lib/types/prompt-library";
import { mapBackendPrompt } from "$lib/types/prompt-library";

const BASE_PATH = "/api/v1/prompt_library";

/**
 * Fetch all prompts for a specific chatbot (by UUID).
 * GET /api/v1/prompt_library?chatbot_id={chatbotId}
 *
 * The backend filters by chatbot_id/agent_id as query params; a path segment
 * would be interpreted as a prompt_id lookup instead.
 *
 * @param chatbotId - The chatbot UUID to fetch prompts for
 * @returns Array of prompts (empty array if none or 404)
 *
 * @example
 * const prompts = await getPrompts('550e8400-e29b-41d4-a716-446655440000');
 */
export async function getPrompts(chatbotId: string): Promise<Prompt[]> {
  try {
    const { data } = await apiClient.get<BackendPrompt[]>(BASE_PATH, {
      params: { chatbot_id: chatbotId },
    });

    return (data || []).map(mapBackendPrompt);
  } catch (error: unknown) {
    // Return empty array for 404 (no prompts yet)
    if (isAxiosError(error) && error.response?.status === 404) {
      return [];
    }
    // Re-throw other errors
    throw error;
  }
}

/**
 * Create a new prompt.
 * PUT /api/v1/prompt_library
 *
 * ModelView semantics are inverted vs REST: PUT inserts (no primary key in
 * the payload), POST updates an existing row by primary key.
 *
 * @param request - The prompt data to create (chatbot_id must be a UUID)
 * @returns The created prompt with ID
 *
 * @example
 * const prompt = await createPrompt({
 *   chatbot_id: '550e8400-e29b-41d4-a716-446655440000',
 *   title: 'Monthly Revenue',
 *   query: 'Show revenue for {{current_month}}'
 * });
 */
export async function createPrompt(
  request: CreatePromptRequest,
): Promise<Prompt> {
  const { data } = await apiClient.put<BackendPrompt | BackendPrompt[]>(
    BASE_PATH,
    request,
  );
  return mapBackendPrompt(Array.isArray(data) ? data[0] : data);
}

/**
 * Update an existing prompt.
 * POST /api/v1/prompt_library/{prompt_id}
 *
 * @param promptId - The prompt_id (UUID) to update
 * @param request - The fields to update
 * @returns The updated prompt
 *
 * @example
 * const updated = await updatePrompt('550e8400-...', { title: 'New Title' });
 */
export async function updatePrompt(
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
 * Delete a prompt.
 * DELETE /api/v1/prompt_library/{prompt_id}
 *
 * @param promptId - The prompt_id (UUID) to delete
 *
 * @example
 * await deletePrompt('550e8400-...');
 */
export async function deletePrompt(promptId: string): Promise<void> {
  await apiClient.delete(`${BASE_PATH}/${encodeURIComponent(promptId)}`);
}

/**
 * Type guard for Axios errors.
 * Checks if the error has a response property with status.
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
