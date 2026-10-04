/** Agent Studio tooling client (FEAT-593). */
import apiClient from "$lib/api/http";
import type { AgentMCPServerSpec } from "$lib/types/generated/AgentMCPServerSpec";
import type { AgentMcpServersResponse } from "$lib/types/generated/AgentMcpServersResponse";
import type { AgentToolkitsResponse } from "$lib/types/generated/AgentToolkitsResponse";
import type { ConfigOption } from "$lib/types/generated/ConfigOption";
import type { ToolkitConfigPutRequest } from "$lib/types/generated/ToolkitConfigPutRequest";
import type { ToolkitPersistResponse } from "$lib/types/generated/ToolkitPersistResponse";
import type { ToolkitSchemaEnvelope } from "$lib/types/generated/ToolkitSchemaEnvelope";

const BASE = "/api/v1/astudio";
const enc = encodeURIComponent;

export async function getToolkitSchema(slug: string): Promise<ToolkitSchemaEnvelope> {
  const { data } = await apiClient.get<ToolkitSchemaEnvelope>(`${BASE}/toolkits/${enc(slug)}/schema`);
  return data;
}

export async function getAgentToolkits(name: string): Promise<AgentToolkitsResponse> {
  // Not `/agents/{name}/toolkits` — that path is the legacy (FEAT-467) StudioToolkitsHandler,
  // which requires a {slug} segment and 400s `missing_slug` without one. The FEAT-593 masked
  // listing lives at `/toolkit-config` (see handlers/studio/__init__.py's routing comment).
  const { data } = await apiClient.get<AgentToolkitsResponse>(`${BASE}/agents/${enc(name)}/toolkit-config`);
  return data;
}

export async function putAgentToolkit(
  name: string,
  slug: string,
  body: ToolkitConfigPutRequest,
): Promise<ToolkitPersistResponse> {
  const { data } = await apiClient.put<ToolkitPersistResponse>(
    `${BASE}/agents/${enc(name)}/toolkits/${enc(slug)}`,
    body,
  );
  return data;
}

export async function deleteAgentToolkit(name: string, slug: string): Promise<ToolkitPersistResponse> {
  const { data } = await apiClient.delete<ToolkitPersistResponse>(
    `${BASE}/agents/${enc(name)}/toolkits/${enc(slug)}`,
  );
  return data;
}

export async function getToolkitOptions(name: string, slug: string, param: string): Promise<{ options: ConfigOption[] }> {
  const { data } = await apiClient.get<{ options: ConfigOption[] }>(
    `${BASE}/agents/${enc(name)}/toolkits/${enc(slug)}/options/${enc(param)}`,
  );
  return data;
}

export async function getAgentMcpServers(name: string): Promise<AgentMcpServersResponse> {
  const { data } = await apiClient.get<AgentMcpServersResponse>(`${BASE}/agents/${enc(name)}/mcp-servers`);
  return data;
}

export async function putAgentMcpServers(name: string, servers: AgentMCPServerSpec[]): Promise<AgentMcpServersResponse> {
  const { data } = await apiClient.put<AgentMcpServersResponse>(`${BASE}/agents/${enc(name)}/mcp-servers`, { servers });
  return data;
}

export async function reloadAgent(name: string): Promise<void> {
  await apiClient.post<void>(`${BASE}/agents/${enc(name)}/reload`);
}

export async function getMyToolkitOverride(name: string, slug: string): Promise<ToolkitPersistResponse> {
  const { data } = await apiClient.get<ToolkitPersistResponse>(
    `${BASE}/agents/${enc(name)}/toolkits/${enc(slug)}/me`,
  );
  return data;
}

export async function putMyToolkitOverride(
  name: string,
  slug: string,
  body: ToolkitConfigPutRequest,
): Promise<ToolkitPersistResponse> {
  const { data } = await apiClient.put<ToolkitPersistResponse>(
    `${BASE}/agents/${enc(name)}/toolkits/${enc(slug)}/me`,
    body,
  );
  return data;
}

export async function deleteMyToolkitOverride(name: string, slug: string): Promise<ToolkitPersistResponse> {
  const { data } = await apiClient.delete<ToolkitPersistResponse>(
    `${BASE}/agents/${enc(name)}/toolkits/${enc(slug)}/me`,
  );
  return data;
}
