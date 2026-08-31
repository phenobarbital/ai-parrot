/**
 * Thin shim for navigator's navauth-backed `$lib/auth.ts`
 * (`createNavAuthConfig`/`createNavAuthStore`, multi-provider SSO).
 *
 * ai-parrot: `navauth/**` (Azure/ADFS/basic multi-provider SSO) is not
 * ported (spec §1 Non-Goals; §3 Module 3 drop list) — this Admin UI only
 * has the Bearer-token `authStore` (rune-class store, FEAT-468
 * `stores/auth.svelte.ts`). This module re-points the one remaining
 * `import { auth } from "$lib/auth"` call site
 * (`stores/prompt-library.svelte.ts`'s `resolveUserId()`) at `authStore`,
 * exposing just the subset of navauth's store surface that call site
 * uses: `auth.subscribe((s) => …)` and `get(auth.session)`.
 *
 * Deviation: this file stays a plain `.ts` module (matching navigator's
 * import specifier `$lib/auth`, without a `.svelte` segment), so it
 * cannot use runes to reactively bridge `authStore`'s `$state`. Instead
 * `subscribe()` is a one-shot notification of the *current* state —
 * `authStore` hydrates synchronously from `localStorage` in its
 * constructor (no async multi-provider session negotiation to await like
 * navauth's), so there is no "still loading" phase a caller needs to wait
 * out; every caller here (`resolveUserId()`) only ever reads the state at
 * the moment it subscribes.
 */
import { authStore, type AuthUser } from "$lib/stores/auth.svelte";

/**
 * `authStore.user` is the raw login response JSON (`AuthUser`, an
 * index-signature-only type) — the vendored `stores/prompt-library.svelte.ts`
 * reads `session?.user_id` expecting a `number | undefined`, matching
 * ai-parrot's login envelope (`ChatbotHandler`/PBAC user records carry an
 * integer `user_id`). Narrowing that one field here (rather than in the
 * vendored call site) keeps that file an unmodified copy.
 */
export interface AuthSessionUser extends AuthUser {
  user_id?: number;
}

export interface AuthState {
  loading: boolean;
  session: AuthSessionUser | null;
}

function currentState(): AuthState {
  return { loading: false, session: authStore.user as AuthSessionUser | null };
}

export const auth = {
  subscribe(run: (value: AuthState) => void): () => void {
    run(currentState());
    return () => {};
  },
  session: {
    subscribe(run: (value: AuthSessionUser | null) => void): () => void {
      run(authStore.user as AuthSessionUser | null);
      return () => {};
    },
  },
};
