/**
 * Field metadata and validators for the agent form (TASK-2586, FEAT-475).
 *
 * Headless — no Svelte, no components. `AgentFormState`
 * (`stores/agent-form.svelte.ts`) and the six tab panels (TASK-2587)
 * consume these exports.
 *
 * `defaults()` mirrors `parrot.handlers.models.bots.BotModel`'s field
 * defaults (handlers/models/bots.py:95-260, verified against the source,
 * not just the spec's paraphrase — `custom_kbs` defaults to `null`
 * there, `Field(nullable=True, default=None)`, not `[]`).
 */
import type { BotWritePayload } from "$lib/types/generated/BotWritePayload";

export type TabId =
  | "general"
  | "behavior"
  | "ai"
  | "capabilities"
  | "data_memory"
  | "advanced";

/** Fields the UI never sends back to the server (server-managed identity/audit columns). */
export const IMMUTABLE_FIELDS = ["chatbot_id", "created_at", "created_by"] as const;

/** JSONB `BotWritePayload` fields — each must be edited through JsonEditor. */
export const JSON_FIELDS = [
  "model_config",
  "prompt_config",
  "vector_store_config",
  "reranker_config",
  "parent_searcher_config",
  "memory_config",
  "permissions",
] as const;

/** `BotModel.required=True` fields the client enforces before Save. */
export const REQUIRED_FIELDS = ["name", "goal", "backstory", "rationale"] as const;

/**
 * `BotModel` field defaults (handlers/models/bots.py:95-260). `chatbot_id`/
 * `created_at`/`created_by`/`updated_at` are server-assigned and never part
 * of the write payload — omitted here, not in `BotWritePayload` either.
 */
export function defaults(): BotWritePayload {
  return {
    name: "",
    description: null,
    avatar: null,
    enabled: true,
    timezone: "UTC",
    language: "en",
    disclaimer: null,
    role: "AI Assistant",
    goal: "Help users accomplish their tasks effectively.",
    backstory: "I am an AI assistant created to help users with various tasks.",
    rationale:
      "I maintain a professional tone and provide accurate, helpful information.",
    capabilities:
      "I can engage in conversation, answer questions, and use tools when needed.",
    system_prompt_template: null,
    human_prompt_template: null,
    pre_instructions: [],
    prompt_config: {},
    llm: "google",
    model_config: {},
    tools_enabled: true,
    auto_tool_detection: true,
    tool_threshold: 0.7,
    tools: [],
    operation_mode: "adaptive",
    use_kb: false,
    kb: [],
    // BotModel.custom_kbs: Field(nullable=True, default=None) — not [].
    custom_kbs: null,
    use_vector: false,
    vector_store_config: {},
    reranker_config: {},
    parent_searcher_config: {},
    context_search_limit: 10,
    context_score_threshold: 0.7,
    memory_type: "memory",
    memory_config: {},
    max_context_turns: 5,
    use_conversation_history: true,
    bot_class: "BasicBot",
    permissions: {},
  };
}

/**
 * Tab each `BotWritePayload` field belongs to (spec §2 component diagram).
 * `storage` (create-only, never a user-editable field on its own) lives
 * alongside `name` on General, the tab the create flow starts on.
 *
 * Typed as `Record<keyof BotWritePayload, TabId>` so a field added to the
 * generated type without a matching entry here is a compile error.
 */
export const FIELD_TAB: Record<keyof BotWritePayload, TabId> = {
  // General
  storage: "general",
  name: "general",
  description: "general",
  avatar: "general",
  enabled: "general",
  timezone: "general",
  language: "general",
  disclaimer: "general",
  // Behavior
  role: "behavior",
  goal: "behavior",
  backstory: "behavior",
  rationale: "behavior",
  capabilities: "behavior",
  system_prompt_template: "behavior",
  human_prompt_template: "behavior",
  pre_instructions: "behavior",
  prompt_config: "behavior",
  // AI
  llm: "ai",
  model_config: "ai",
  // Capabilities
  tools_enabled: "capabilities",
  auto_tool_detection: "capabilities",
  tool_threshold: "capabilities",
  tools: "capabilities",
  operation_mode: "capabilities",
  use_kb: "capabilities",
  kb: "capabilities",
  custom_kbs: "capabilities",
  // Data & Memory
  use_vector: "data_memory",
  vector_store_config: "data_memory",
  reranker_config: "data_memory",
  parent_searcher_config: "data_memory",
  context_search_limit: "data_memory",
  context_score_threshold: "data_memory",
  memory_type: "data_memory",
  memory_config: "data_memory",
  max_context_turns: "data_memory",
  use_conversation_history: "data_memory",
  // Advanced
  bot_class: "advanced",
  permissions: "advanced",
};

const OPERATION_MODES = ["conversational", "agentic", "adaptive"] as const;
const MEMORY_TYPES = ["memory", "file", "redis"] as const;

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** True for a value in [0, 1] (used by tool_threshold / context_score_threshold). */
function inUnitRange(v: unknown): boolean {
  return typeof v === "number" && v >= 0 && v <= 1;
}

/** True for a non-negative integer. */
function isNonNegativeInt(v: unknown): boolean {
  return typeof v === "number" && Number.isInteger(v) && v >= 0;
}

/**
 * Validate a `BotWritePayload` draft. Returns a map of field name -> error
 * message; an empty object means the form is valid. `mode` is accepted for
 * symmetry with `AgentFormState`/future mode-specific rules (e.g. `name`
 * required only matters for create — edit's `name` is read-only and never
 * sent, per §8 Q3 — but an empty `name` is still invalid input either way).
 */
export function validate(
  values: BotWritePayload,
  mode: "create" | "edit" = "create",
): Record<string, string> {
  void mode; // reserved for mode-specific rules; no rule currently differs by mode
  const errors: Record<string, string> = {};

  for (const field of REQUIRED_FIELDS) {
    const value = values[field];
    if (typeof value !== "string" || value.trim() === "") {
      errors[field] = "This field is required.";
    }
  }

  if (values.tool_threshold !== undefined && values.tool_threshold !== null) {
    if (!inUnitRange(values.tool_threshold)) {
      errors.tool_threshold = "Must be a number between 0 and 1.";
    }
  }
  if (
    values.context_score_threshold !== undefined &&
    values.context_score_threshold !== null
  ) {
    if (!inUnitRange(values.context_score_threshold)) {
      errors.context_score_threshold = "Must be a number between 0 and 1.";
    }
  }
  if (
    values.context_search_limit !== undefined &&
    values.context_search_limit !== null &&
    !isNonNegativeInt(values.context_search_limit)
  ) {
    errors.context_search_limit = "Must be a non-negative integer.";
  }
  if (
    values.max_context_turns !== undefined &&
    values.max_context_turns !== null &&
    !isNonNegativeInt(values.max_context_turns)
  ) {
    errors.max_context_turns = "Must be a non-negative integer.";
  }

  if (
    values.operation_mode !== undefined &&
    values.operation_mode !== null &&
    !(OPERATION_MODES as readonly string[]).includes(values.operation_mode)
  ) {
    errors.operation_mode = `Must be one of: ${OPERATION_MODES.join(", ")}.`;
  }
  if (
    values.memory_type !== undefined &&
    values.memory_type !== null &&
    !(MEMORY_TYPES as readonly string[]).includes(values.memory_type)
  ) {
    errors.memory_type = `Must be one of: ${MEMORY_TYPES.join(", ")}.`;
  }

  // model_config: object-shaped, plus temperature >= 0 / max_tokens a
  // non-negative integer when present (nested keys, not top-level fields).
  const modelConfig = values.model_config;
  if (modelConfig !== undefined && modelConfig !== null) {
    if (!isPlainObject(modelConfig)) {
      errors.model_config = "Must be a JSON object.";
    } else {
      if (
        "temperature" in modelConfig &&
        modelConfig.temperature !== undefined &&
        modelConfig.temperature !== null &&
        !(typeof modelConfig.temperature === "number" && modelConfig.temperature >= 0)
      ) {
        errors.model_config = "temperature must be a number >= 0.";
      }
      if (
        "max_tokens" in modelConfig &&
        modelConfig.max_tokens !== undefined &&
        modelConfig.max_tokens !== null &&
        !isNonNegativeInt(modelConfig.max_tokens)
      ) {
        errors.model_config = "max_tokens must be a non-negative integer.";
      }
    }
  }

  // Every other JSON field must be a plain object; `permissions` also
  // accepts a list of rule dicts (BotModel.permissions dual shape).
  for (const field of JSON_FIELDS) {
    if (field === "model_config") continue; // handled above
    const value = values[field];
    if (value === undefined || value === null) continue;
    if (field === "permissions") {
      const permsValid =
        isPlainObject(value) || (Array.isArray(value) && value.every(isPlainObject));
      if (!permsValid) {
        errors.permissions = "Must be a JSON object or a list of rule objects.";
      }
      continue;
    }
    if (!isPlainObject(value)) {
      errors[field] = "Must be a JSON object.";
    }
  }

  return errors;
}
