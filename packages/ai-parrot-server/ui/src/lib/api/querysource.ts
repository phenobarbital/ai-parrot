/**
 * QuerySource client for linked A2UI surfaces (FEAT-598, spec G3).
 * The renderer calls QuerySource DIRECTLY with the viewer's bearer — ai-parrot-server never proxies.
 * Native fetch (not the admin axios client, whose 401 interceptor logs the user out).
 */
import { getAuthHeaders } from '$lib/api/auth-headers';
import { config } from '$lib/config';

/** Base URL of the QuerySource API; defaults to the admin API origin (same-origin ""). */
export const querySourceBaseUrl: string = (
  (import.meta.env.PUBLIC_QUERYSOURCE_URL as string | undefined) ?? config.apiBaseUrl
).replace(/\/$/, '');

export class QuerySourceHttpError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = 'QuerySourceHttpError';
  }
}

/**
 * Route rule (spec G3, AC4):
 * - `tenant` set → `/api/v1/{tenant}/queries/{slug}` (kind-aware tenant handler);
 * - `isMultiquery` → `/api/v3/queries/{slug}` (MultiQS — the only HTTP lane that expands a MultiQuery pipeline);
 * - otherwise → `/api/v2/services/queries/{slug}` (plain `QS()`, milliseconds).
 * MultiQS favours availability over latency (definition load, threads, up to 3 retries), so a regular slug
 * must never go through v3 — it is the pipeline/ETL lane, not the query lane.
 */
export function queryUrl(
  baseUrl: string,
  slug: string,
  tenant: string | null | undefined,
  isMultiquery: boolean = false,
): string {
  const s = encodeURIComponent(slug);
  if (tenant) return `${baseUrl}/api/v1/${encodeURIComponent(tenant)}/queries/${s}`;
  return isMultiquery ? `${baseUrl}/api/v3/queries/${s}` : `${baseUrl}/api/v2/services/queries/${s}`;
}

export function querySourceHeaders(): HeadersInit {
  return { 'Content-Type': 'application/json', ...getAuthHeaders() };
}

export async function postQuery(url: string, body: Record<string, unknown>, headers: HeadersInit): Promise<unknown> {
  const res = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body) });
  if (!res.ok) throw new QuerySourceHttpError(res.status, `QuerySource ${res.status}`);
  // QuerySource answers an empty result with 204 `x-status: Empty Result` and no body — zero rows, not an error.
  if (res.status === 204) return [];
  return res.json();
}
