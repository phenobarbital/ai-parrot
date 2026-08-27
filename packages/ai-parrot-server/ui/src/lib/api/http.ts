/**
 * Axios API client wrapper (TASK-2527), adapted from
 * navigator-frontend-next's `src/lib/api/http.ts`.
 *
 * Deviations from the source (Codebase Contract, TASK-2527):
 *  - the SvelteKit `browser` (env: environment) guard is dropped — this SPA has no
 *    SSR, so browser-only code always runs.
 *  - The 401 branch calls `authStore.handle401()` instead of directly
 *    clearing `localStorage`/redirecting — matches this task's Scope
 *    ("wire a 401 interceptor to AuthStore.handle401"). `authStore` is
 *    imported here and `apiClient` is imported back from
 *    `stores/auth.svelte.ts` — a circular ES module import, but safe:
 *    both sides only touch the other's export from inside a function
 *    body (interceptor callback / login()/logout() methods), never at
 *    module-evaluation time, so both modules are fully initialized by
 *    the time either is actually invoked.
 *  - `config.tokenStorageKey` stores the raw bearer token string
 *    directly (matches `parrot/autonomous/admin.py`'s
 *    `localStorage.setItem('ai_parrot_token', data.token)`), not a JSON
 *    blob — so no `JSON.parse` fallback chain is needed here.
 */
import axios, { type AxiosInstance } from "axios";

import { config } from "$lib/config";
import { authStore } from "$lib/stores/auth.svelte";

/**
 * Typed API error — replaces raw Axios errors with a structured format
 * so callers can detect network vs HTTP errors uniformly.
 */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly code: "network" | "timeout" | "server" | "auth" | "unknown",
    public readonly status?: number,
    public readonly raw?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Build a SAFE `raw` payload for ApiError from an Axios error.
 *
 * The full AxiosError carries `config.headers.Authorization` (the bearer
 * token) and other request internals. Those must never reach an error UI.
 * We keep only debugging-safe fields and preserve the `response.data`
 * path callers read from.
 */
function safeRaw(error: unknown): unknown {
  if (!error || typeof error !== "object") return error;
  const e = error as {
    message?: string;
    code?: string;
    response?: { status?: number; statusText?: string; data?: unknown };
    config?: { method?: string; url?: string; baseURL?: string };
  };
  return {
    message: e.message,
    code: e.code,
    response: e.response
      ? {
          status: e.response.status,
          statusText: e.response.statusText,
          data: e.response.data,
        }
      : undefined,
    request: e.config
      ? { method: e.config.method, url: e.config.url, baseURL: e.config.baseURL }
      : undefined,
  };
}

/**
 * Extract a human-readable error message from an API response body.
 * Checks common message shapes: { error }, { message }, { message: { message } }, { detail }.
 * Falls back to "HTTP <status>" if nothing useful is found.
 */
export function extractServerMessage(data: unknown, status: number): string {
  if (data === null || data === undefined || typeof data !== "object") {
    return `HTTP ${status}`;
  }
  const d = data as Record<string, unknown>;

  if (typeof d.error === "string") return d.error;

  if (d.message !== undefined) {
    if (typeof d.message === "object" && d.message !== null) {
      const nested = (d.message as Record<string, unknown>).message;
      if (typeof nested === "string") return nested;
    }
    if (typeof d.message === "string") return d.message;
  }

  if (typeof d.detail === "string") return d.detail;
  // FastAPI 422: detail is an array of validation errors — use the first message
  if (Array.isArray(d.detail) && d.detail.length > 0) {
    const first = d.detail[0];
    if (first !== null && typeof first === "object") {
      const msg = (first as Record<string, unknown>).msg;
      if (typeof msg === "string") return msg;
    }
  }

  return `HTTP ${status}`;
}

/**
 * Register auth token injection and error-handling interceptors
 * on an Axios instance.
 */
function registerInterceptors(instance: AxiosInstance): void {
  // Request interceptor — attach the bearer token.
  instance.interceptors.request.use(
    (requestConfig) => {
      const token = localStorage.getItem(config.tokenStorageKey);
      if (token) {
        requestConfig.headers.Authorization = `Bearer ${token}`;
      }
      return requestConfig;
    },
    (error) => Promise.reject(error),
  );

  // Response interceptor — normalize errors into ApiError.
  instance.interceptors.response.use(
    (response) => response,
    (error) => {
      if (error.response) {
        switch (error.response.status) {
          case 401: {
            const bodyMsg = extractServerMessage(error.response.data, 401);
            const statusText: string = error.response.statusText || "";
            // Policy denials come back as 401 but are authorization failures,
            // not session failures — surface the message instead of forcing
            // a re-login.
            if (/policy/i.test(bodyMsg) || /policy/i.test(statusText)) {
              const msg = bodyMsg !== "HTTP 401" ? bodyMsg : statusText || "Access denied";
              throw new ApiError(msg, "auth", 401, safeRaw(error));
            }
            authStore.handle401();
            throw new ApiError("Unauthorized", "auth", 401, safeRaw(error));
          }
          case 403:
            throw new ApiError("Forbidden", "auth", 403, safeRaw(error));
          case 404:
            throw new ApiError("Not found", "server", 404, safeRaw(error));
          default: {
            const msg = extractServerMessage(error.response.data, error.response.status);
            throw new ApiError(msg, "server", error.response.status, safeRaw(error));
          }
        }
      } else if (error.code === "ECONNABORTED") {
        throw new ApiError("Request timed out", "timeout", undefined, safeRaw(error));
      } else {
        throw new ApiError("Network unavailable", "network", undefined, safeRaw(error));
      }
    },
  );
}

// Global API client singleton.
const apiClient = axios.create({
  baseURL: config.apiBaseUrl,
  timeout: 300000, // 5 minutes — agent queries can take a while.
  withCredentials: config.apiWithCredentials,
  headers: {
    "Content-Type": "application/json",
  },
});
registerInterceptors(apiClient);

/**
 * Create an Axios instance configured with auth interceptors.
 * If `baseURL` is omitted or matches the global API URL, returns the
 * existing global singleton to avoid duplication.
 */
export function createApiClient(baseURL?: string): AxiosInstance {
  const normalizedBaseURL = baseURL?.replace(/\/+$/, "");
  if (!normalizedBaseURL || normalizedBaseURL === config.apiBaseUrl) {
    return apiClient;
  }

  const instance = axios.create({
    baseURL: normalizedBaseURL,
    timeout: 300000,
    withCredentials: config.apiWithCredentials,
    headers: {
      "Content-Type": "application/json",
    },
  });
  registerInterceptors(instance);
  return instance;
}

export default apiClient;
