/**
 * Typed API client for the OAuth2 integrations endpoints.
 *
 * Wraps the four routes exposed by `parrot.handlers.integrations.IntegrationsHandler`:
 *   GET    /api/v1/agents/integrations/{agentId}
 *   POST   /api/v1/agents/integrations/{agentId}/{provider}/connect
 *   POST   /api/v1/agents/integrations/{agentId}/{provider}/enable
 *   DELETE /api/v1/agents/integrations/{agentId}/{provider}
 */
import { createApiClient } from "$lib/api/http";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface IntegrationDescriptor {
  provider: string;
  display_name: string;
  icon?: string;
  default_scopes: string[];
  connected: boolean;
  enabled_on_agent: boolean;
  account_id?: string;
  display_account_name?: string;
  email?: string;
  connected_at?: string;
}

export interface ConnectInitResponse {
  auth_url: string;
  state: string;
  scopes: string[];
  expires_in: number;
}

export interface EnableResponse {
  integration: IntegrationDescriptor;
}

export interface DisconnectResponse {
  provider: string;
  disconnected: boolean;
}

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
 * Confirm-enable after the OAuth popup completes. Writes a `user_agent_toolkits`
 * row so the Jira toolkit becomes available to the agent.
 */
export async function confirmIntegrationEnable(
  agentId: string,
  provider: string,
): Promise<EnableResponse> {
  const { data } = await client.post<EnableResponse>(
    `${BASE(agentId)}/${encodeURIComponent(provider)}/enable`,
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
