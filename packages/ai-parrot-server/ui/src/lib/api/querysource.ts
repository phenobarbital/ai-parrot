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

/** `/api/v3/queries/{slug}` or `/api/v1/{tenant}/queries/{slug}` (spec G3, AC4). */
export function queryUrl(baseUrl: string, slug: string, tenant: string | null | undefined): string {
  const s = encodeURIComponent(slug);
  return tenant ? `${baseUrl}/api/v1/${encodeURIComponent(tenant)}/queries/${s}` : `${baseUrl}/api/v3/queries/${s}`;
}

export function querySourceHeaders(): HeadersInit {
  return { 'Content-Type': 'application/json', ...getAuthHeaders() };
}

export async function postQuery(url: string, body: Record<string, unknown>, headers: HeadersInit): Promise<unknown> {
  const res = await fetch(url, { method: 'POST', headers, body: JSON.stringify(body) });
  if (!res.ok) throw new QuerySourceHttpError(res.status, `QuerySource ${res.status}`);
  return res.json();
}
