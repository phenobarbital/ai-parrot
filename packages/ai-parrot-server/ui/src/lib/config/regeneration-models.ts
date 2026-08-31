/**
 * Curated model list for the Regeneration Options popover.
 * This is a subset of the full model list in ChatInput.svelte,
 * chosen for quick access during regeneration.
 *
 * Format matches the backend enum pattern: "provider:model-name"
 *
 * `enabled`: Whether the backend currently supports this model for regeneration.
 *            Disabled models show as "Coming Soon" and are non-interactive.
 */

export interface RegenerationModel {
  value: string;
  label: string;
  provider: string;
  enabled: boolean;
}

export const REGENERATION_MODELS: RegenerationModel[] = [
  // Google (supported)
  {
    value: "google:gemini-2.5-flash",
    label: "Gemini 2.5 Flash",
    provider: "Google",
    enabled: true,
  },
  {
    value: "google:gemini-3-flash-preview",
    label: "Gemini 3 Flash",
    provider: "Google",
    enabled: true,
  },
  {
    value: "google:gemini-3-pro-preview",
    label: "Gemini 3 Pro",
    provider: "Google",
    enabled: true,
  },
  // OpenAI (coming soon)
  {
    value: "openai:gpt-4.1",
    label: "GPT 4.1",
    provider: "OpenAI",
    enabled: false,
  },
  {
    value: "openai:o4-mini",
    label: "o4 Mini",
    provider: "OpenAI",
    enabled: false,
  },
  // Anthropic (coming soon)
  {
    value: "anthropic:claude-sonnet-4-5-20250929",
    label: "Claude Sonnet 4.5",
    provider: "Anthropic",
    enabled: false,
  },
];

/** Default model used when no selection has been made */
export const DEFAULT_MODEL = "google:gemini-2.5-flash";

/**
 * Find a matching enabled model from metadata.
 * Handles the naming mismatch between backend metadata (e.g. "gemini-2.5-flash")
 * and frontend config values (e.g. "google:gemini-2.5-flash").
 *
 * Matching strategy (in priority order):
 * 1. Exact match on value
 * 2. Config value ends with the metadata model name (handles missing provider prefix)
 * 3. Metadata model ends with the config model name (handles extra prefix in metadata)
 */
export function findModelByMetadata(
  metadataModel: string | undefined,
): RegenerationModel | undefined {
  if (!metadataModel) return undefined;
  return (
    REGENERATION_MODELS.find((m) => m.enabled && m.value === metadataModel) ||
    REGENERATION_MODELS.find(
      (m) => m.enabled && m.value.endsWith(metadataModel),
    ) ||
    REGENERATION_MODELS.find(
      (m) => m.enabled && metadataModel.endsWith(m.value.split(":").pop()!),
    )
  );
}
