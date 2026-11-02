/**
 * Typed API client for the OAuth2 integrations endpoints.
 *
 * Wraps the three routes exposed by `parrot.handlers.integrations.IntegrationsHandler`:
 *   GET    /api/v1/agents/integrations/{agentId}
 *   POST   /api/v1/agents/integrations/{agentId}/{provider}/connect
 *   DELETE /api/v1/agents/integrations/{agentId}/{provider}
 */
import { createApiClient } from "$lib/api/http";
import type { ConnectInitResponse } from "$lib/types/generated/ConnectInitResponse";
import type { DisconnectResponse } from "$lib/types/generated/DisconnectResponse";
import type { IntegrationDescriptor } from "$lib/types/generated/IntegrationDescriptor";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type { ConnectInitResponse } from "$lib/types/generated/ConnectInitResponse";
export type { DisconnectResponse } from "$lib/types/generated/DisconnectResponse";
export type { IntegrationDescriptor } from "$lib/types/generated/IntegrationDescriptor";

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

const client = createApiClient();

const BASE = (agentId: string) =>
  `/api/v1/agents/integrations/${encodeURIComponent(agentId)}`;

/**
 * List all OAuth2 integrations (connected/disconnected) for the current user
 * on the given agent.
 */
export async function listIntegrations(
  agentId: string,
): Promise<IntegrationDescriptor[]> {
  const { data } = await client.get<IntegrationDescriptor[]>(BASE(agentId));
  return data;
}

/**
 * Initiate the OAuth2 popup flow for `provider`. Returns the authorization URL
 * and a CSRF state nonce.
 *
 * @param returnOrigin - The origin the popup should postMessage back to
 *   (typically `window.location.origin`).
 */
export async function startIntegrationConnect(
  agentId: string,
  provider: string,
  returnOrigin?: string,
): Promise<ConnectInitResponse> {
  const { data } = await client.post<ConnectInitResponse>(
    `${BASE(agentId)}/${encodeURIComponent(provider)}/connect`,
    returnOrigin ? { return_origin: returnOrigin } : {},
    { headers: returnOrigin ? { Origin: returnOrigin } : {} },
  );
  return data;
}

/**
 * Disconnect the provider: removes both the credential row and all
 * `user_agent_toolkits` rows for the user + provider.
 */
export async function disconnectIntegration(
  agentId: string,
  provider: string,
): Promise<DisconnectResponse> {
  const { data } = await client.delete<DisconnectResponse>(
    `${BASE(agentId)}/${encodeURIComponent(provider)}`,
  );
  return data;
}
