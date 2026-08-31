/**
 * Prompt Library Types
 *
 * TypeScript interfaces for the Prompt Library feature.
 * Used across API client, store, and UI components.
 */

/**
 * Represents a saved prompt in the library.
 * Can be either a per-user prompt or a shared public prompt; both are API-backed.
 */
export interface Prompt {
  /** Unique identifier (mapped from backend's prompt_id) */
  id: string;
  /** Agent/chatbot UUID this prompt belongs to */
  chatbot_id: string;
  /** Short label displayed on the pill button */
  title: string;
  /** The actual prompt text (may contain {{placeholders}}) */
  query: string;
  /** true = belongs to the current user (editable), false = public prompt (read-only) */
  is_user_prompt: boolean;
  /** ISO 8601 timestamp when created */
  created_at?: string;
  /** ISO 8601 timestamp when last updated */
  updated_at?: string;
}

/**
 * Raw backend response shape for a prompt.
 * The backend uses prompt_id (UUID) as the primary key.
 * Use mapBackendPrompt() to convert to the frontend Prompt interface.
 */
export interface BackendPrompt {
  /** Backend primary key */
  prompt_id: string;
  /** Chatbot UUID */
  chatbot_id: string;
  /** Owner user_id when the prompt is a user prompt; absent for public prompts */
  user_id?: number;
  title: string;
  query: string;
  description?: string;
  prompt_category?: string;
  prompt_tags?: string[];
  created_at?: string;
  created_by?: number;
  updated_at?: string;
}

/**
 * Map a raw backend prompt to the frontend Prompt interface.
 * Normalises prompt_id → id and derives is_user_prompt from user_id presence.
 */
export function mapBackendPrompt(bp: BackendPrompt): Prompt {
  return {
    id: bp.prompt_id,
    chatbot_id: bp.chatbot_id,
    title: bp.title,
    query: bp.query,
    is_user_prompt: bp.user_id != null,
    created_at: bp.created_at,
    updated_at: bp.updated_at,
  };
}

/**
 * Represents a placeholder that can be used in prompt templates.
 * Placeholders use the {{key}} syntax and are replaced at runtime.
 */
export interface PromptPlaceholder {
  /** The placeholder key (without braces), e.g., "today" */
  key: string;
  /** Human-readable label for UI display, e.g., "Today's Date" */
  label: string;
  /** Function that returns the current value for this placeholder */
  getValue: () => string;
}

/**
 * Request payload for creating a new prompt via API.
 * POST /api/v1/chatbots/prompt_library
 */
export interface CreatePromptRequest {
  /** Chatbot UUID this prompt belongs to */
  chatbot_id: string;
  /** Short label for the prompt pill */
  title: string;
  /** The prompt text */
  query: string;
}

/**
 * Request payload for updating an existing prompt via API.
 * PUT /api/v1/chatbots/prompt_library/{prompt_id}
 */
export interface UpdatePromptRequest {
  /** Updated title (optional) */
  title?: string;
  /** Updated query text (optional) */
  query?: string;
}

/**
 * Options for placeholder dropdown in the UI.
 * Includes a preview of the current resolved value.
 */
export interface PlaceholderOption {
  /** The placeholder key */
  key: string;
  /** Human-readable label */
  label: string;
  /** Current resolved value for preview */
  preview: string;
}
