/**
 * AuthStore (TASK-2527).
 *
 * Shape referenced from navigator-frontend-next's
 * `src/lib/stores/auth.svelte.ts` (rune-class pattern) and
 * `src/lib/navauth/providers/basic.ts` (login request/response shape),
 * but storage keys and the login contract come from THIS repo's Codebase
 * Contract, verified against `navigator_auth.auth.AuthHandler`:
 *
 *   POST /api/v1/login   header `X-Auth-Method: BasicAuth`,
 *                        body {username, password} -> JSON userdata
 *                        (includes `.token`), sets a session cookie too
 *                        (unused — the SPA authenticates via `Authorization:
 *                        Bearer`, matching parrot_formdesigner).
 *   GET  /api/v1/logout  -> invalidates the server-side session.
 *
 * localStorage keys (`ai_parrot_token` / `ai_parrot_session`) MUST match
 * `packages/parrot-formdesigner/.../templates.py` and
 * `parrot/autonomous/admin.py`'s inline admin login page.
 */
import apiClient from "$lib/api/http";
import { postPasskeyLogin } from "$lib/api/passkey";
import { config } from "$lib/config";
import { isInAppPath, router } from "$lib/router.svelte";
import type { PublicKeyCredentialJSON } from "$lib/webauthn";

export interface AuthUser {
  [key: string]: unknown;
}

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(config.tokenStorageKey);
  } catch {
    return null;
  }
}

function readStoredUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(config.sessionStorageKey);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

function clearStorage(): void {
  try {
    localStorage.removeItem(config.tokenStorageKey);
    localStorage.removeItem(config.sessionStorageKey);
  } catch {
    // localStorage unavailable — nothing to clear.
  }
}

class AuthStore {
  token = $state<string | null>(readStoredToken());
  user = $state<AuthUser | null>(readStoredUser());
  loading = $state(false);
  isAuthenticated = $derived(this.token !== null);
  /** `user.auth_method` from the stored login envelope ("passkey" after a passkey login), else null. */
  authMethod = $derived<string | null>(
    typeof this.user?.auth_method === "string" ? (this.user.auth_method as string) : null,
  );

  /** Shared tail of every login: require data.token, persist both keys (best effort), set token + user. */
  private _storeLoginEnvelope(data: Record<string, unknown>): void {
    const token = data?.token;
    if (typeof token !== "string" || !token) {
      throw new Error("No token received from server");
    }
    try {
      localStorage.setItem(config.tokenStorageKey, token);
      localStorage.setItem(config.sessionStorageKey, JSON.stringify(data));
    } catch {
      // localStorage unavailable — session still works for this tab via in-memory state.
    }
    this.token = token;
    this.user = data;
  }

  /** POST /api/v1/login with X-Auth-Method: BasicAuth; stores token + user payload. */
  async login(username: string, password: string): Promise<{ success: boolean; error?: string }> {
    this.loading = true;
    try {
      const { data } = await apiClient.post(
        config.loginUrl,
        { username, password },
        { headers: { "X-Auth-Method": "BasicAuth" } },
      );

      this._storeLoginEnvelope(data);
      return { success: true };
    } catch (error: unknown) {
      const message =
        (error as { response?: { data?: { message?: string } }; message?: string })?.response
          ?.data?.message ||
        (error as Error)?.message ||
        "Login failed";
      return { success: false, error: message };
    } finally {
      this.loading = false;
    }
  }

  /** Finish a passkey sign-in and persist its envelope exactly like a BasicAuth login. */
  async loginWithPasskey(
    challengeId: string,
    credential: PublicKeyCredentialJSON,
  ): Promise<{ success: boolean; error?: string }> {
    this.loading = true;
    try {
      const data = await postPasskeyLogin({ challenge_id: challengeId, credential });
      this._storeLoginEnvelope(data);
      return { success: true };
    } catch (error: unknown) {
      const responseData = (error as { response?: { data?: unknown } })?.response?.data;
      const reason =
        responseData && typeof responseData === "object"
          ? (responseData as { reason?: unknown }).reason
          : undefined;
      const message = error instanceof Error ? error.message : undefined;
      return {
        success: false,
        error: typeof reason === "string" && reason ? reason : message || "Passkey sign-in failed",
      };
    } finally {
      this.loading = false;
    }
  }

  /** GET /api/v1/logout, then clear local storage regardless of the result. */
  async logout(): Promise<void> {
    try {
      await apiClient.get(config.logoutUrl);
    } catch {
      // Best-effort — the server-side session may already be gone; the
      // client-side state is cleared unconditionally below.
    } finally {
      clearStorage();
      this.token = null;
      this.user = null;
    }
  }

  /** Clear the session and route to login, preserving the intended path. */
  handle401(): void {
    clearStorage();
    this.token = null;
    this.user = null;
    const current = router.path;
    const next = isInAppPath(current) ? current : config.homePath;
    router.navigate(`${config.loginPath}?next=${encodeURIComponent(next)}`, {
      replace: true,
    });
  }
}

export { AuthStore };

export const authStore = new AuthStore();
