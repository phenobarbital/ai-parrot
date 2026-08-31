import apiClient from "./http";

/**
 * Fetch the list of available LLM providers (clients).
 * Backend response shape: { clients: string[] }
 */
export async function listLlmClients(): Promise<string[]> {
  const { data } = await apiClient.get("/api/v1/ai/clients");
  return Array.isArray(data?.clients) ? data.clients : [];
}

/**
 * Fetch the list of available models for a given LLM provider.
 *
 * When filtered by `client`, the backend wraps the payload as
 * `{ client: string, models: <shape> }`, where `models` is either:
 * - For "openai"/"azure": { active: string[], deprecated: string[] }
 * - For all others: string[] (flat list)
 *
 * This function unwraps the envelope and normalizes both `models` shapes
 * into a flat string[]. It also tolerates an un-enveloped response (a bare
 * array or bare { active, deprecated }) for backward compatibility.
 */
export async function listLlmModels(client: string): Promise<string[]> {
  const { data } = await apiClient.get("/api/v1/ai/clients/models", {
    params: { client },
  });

  // Unwrap the { client, models } envelope when present; otherwise treat the
  // whole body as the payload.
  const payload =
    data && typeof data === "object" && "models" in data ? data.models : data;

  if (Array.isArray(payload)) {
    return payload;
  }

  if (payload && typeof payload === "object") {
    const active = Array.isArray(payload.active) ? payload.active : [];
    const deprecated = Array.isArray(payload.deprecated) ? payload.deprecated : [];
    return [...active, ...deprecated];
  }

  return [];
}
