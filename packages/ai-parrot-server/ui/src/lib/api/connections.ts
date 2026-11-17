/** Principal-scoped connections client (FEAT-777 M5): /api/v1/connections*, /api/v1/channel-links*. */
import { ApiError, createApiClient } from "$lib/api/http";
import { getAuthHeaders } from "$lib/api/auth-headers";
import { config } from "$lib/config";
import type { ChannelLinkPreview } from "$lib/types/generated/ChannelLinkPreview";
import type { ConnectInitResponse } from "$lib/types/generated/ConnectInitResponse";
import type { ConnectionEvent } from "$lib/types/generated/ConnectionEvent";
import type { DisconnectResponse } from "$lib/types/generated/DisconnectResponse";
import type { IntegrationDescriptor } from "$lib/types/generated/IntegrationDescriptor";

const client = createApiClient();
const BASE = "/api/v1/connections";
const enc = encodeURIComponent;

export async function listConnections(): Promise<IntegrationDescriptor[]> {
  const { data } = await client.get<IntegrationDescriptor[]>(BASE);
  return data;
}

export async function getConnection(provider: string): Promise<IntegrationDescriptor> {
  const { data } = await client.get<IntegrationDescriptor>(`${BASE}/${enc(provider)}`);
  return data;
}

export async function startConnect(
  provider: string,
  returnOrigin: string,
  scopes?: string[],
): Promise<ConnectInitResponse> {
  const { data } = await client.post<ConnectInitResponse>(
    `${BASE}/${enc(provider)}/start`,
    scopes ? { return_origin: returnOrigin, scopes } : { return_origin: returnOrigin },
  );
  return data;
}

export async function disconnect(provider: string): Promise<DisconnectResponse> {
  const { data } = await client.delete<DisconnectResponse>(`${BASE}/${enc(provider)}`);
  return data;
}

export async function previewChannelLink(token: string): Promise<ChannelLinkPreview> {
  const { data } = await client.get<ChannelLinkPreview>(`/api/v1/channel-links/${enc(token)}`);
  return data;
}

export async function confirmChannelLink(token: string): Promise<{ channel: string; linked: boolean }> {
  const { data } = await client.post<{ channel: string; linked: boolean }>(
    `/api/v1/channel-links/${enc(token)}/confirm`,
    { confirm: true },
  );
  return data;
}

/** Parse one SSE block ("event: …\\ndata: …"); returns the event, or null for comments/other events/bad JSON. */
export function parseSseBlock(block: string): ConnectionEvent | null {
  let event: string | undefined;
  const data: string[] = [];

  for (const line of block.replace(/\r\n?/g, "\n").split("\n")) {
    if (line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    const value = separator === -1 ? "" : line.slice(separator + 1).replace(/^ /, "");
    if (field === "event") event = value;
    if (field === "data") data.push(value);
  }

  if (event !== "connection" || data.length === 0) return null;
  try {
    return JSON.parse(data.join("\n")) as ConnectionEvent;
  } catch {
    return null;
  }
}

/** Read the SSE stream until it ends or `signal` aborts; calls onEvent per `connection` frame. */
export async function openConnectionEvents(
  onEvent: (e: ConnectionEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${config.apiBaseUrl}${BASE}/events`, {
      headers: { Accept: "text/event-stream", ...getAuthHeaders() },
      signal,
    });
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") throw err;
    throw new ApiError("Network unavailable", "network", undefined, err);
  }

  if (!response.ok || !response.body) {
    throw new ApiError(`HTTP ${response.status}`, response.status === 401 ? "auth" : "server", response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const normalized = buffer.replace(/\r\n?/g, "\n");
      const blocks = normalized.split("\n\n");
      buffer = blocks.pop() ?? "";
      for (const block of blocks) {
        const event = parseSseBlock(block);
        if (event) onEvent(event);
      }
      if (done) {
        const event = parseSseBlock(buffer);
        if (event) onEvent(event);
        break;
      }
    }
  } finally {
    reader.releaseLock();
  }
}
