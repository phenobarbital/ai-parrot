// src/lib/navauth/store.svelte.ts

import { writable, derived, get } from 'svelte/store';
import type { AuthResponse, UserInfo, UserSession, AuthMethod, AuthResult } from './types';
import { AuthStorage } from './storage';
import { providerRegistry } from './providers/registry';
import type { NavAuthConfig } from './config';

interface AuthState {
  loading: boolean;
  isAuthenticated: boolean;
  token: string | null;
  user: UserInfo | null;
  session: UserSession | null;
  method: AuthMethod | null;
  expiresAt: number | null;
}

export function createNavAuthStore(config: NavAuthConfig) {
  const storage = new AuthStorage(config.storageKey);

  const state = writable<AuthState>({
    loading: true,
    isAuthenticated: false,
    token: null,
    user: null,
    session: null,
    method: null,
    expiresAt: null
  });

  const providers = providerRegistry.init(config);

  async function init() {
    if (typeof window === 'undefined') return;

    // Re-initialize providers on client to get correct window.location.origin
    providerRegistry.init(config);

    const storedAuth = storage.getToken();
    const storedProfile = storage.getProfile();

    if (storedAuth && storedProfile) {
      state.set({
        loading: false,
        isAuthenticated: true,
        token: storedAuth.token,
        user: storedProfile.user,
        session: storedProfile.session,
        method: storedAuth.method,
        expiresAt: storedAuth.expiresAt
      });
    } else {
      storage.clear(); // Limpia si hay datos parciales
      state.set({ loading: false, isAuthenticated: false, token: null, user: null, session: null, method: null, expiresAt: null });
    }

    // Init OAuth providers
    await Promise.all(
      Object.values(providers)
        .filter(p => p.isEnabled && 'init' in p)
        .map(p => (p as any).init())
    );
  }

  async function loginBasic(username: string, password: string): Promise<AuthResult> {
    return login('basic', { username, password });
  }

  async function login(method: AuthMethod, credentials?: unknown): Promise<AuthResult> {
    const provider = providers[method];
    if (!provider?.isEnabled) {
      return { success: false, error: `Provider ${method} not enabled` };
    }

    state.update(s => ({ ...s, loading: true }));

    try {
      const result = await provider.login(credentials);

      if (result.success && result.token && result.session) {
        // Construir AuthResponse-like para el storage
        const { auth, user } = storage.saveAuthResponse({
          token: result.token,
          session: result.session,
          auth_method: method,
          expires_in: result.expiresAt || (Date.now() / 1000 + 86400),
          session_id: result.sessionId || '',
          name: `${result.session.first_name} ${result.session.last_name}`,
          // ... otros campos
        } as AuthResponse);

        state.set({
          loading: false,
          isAuthenticated: true,
          token: auth.token,
          user,
          session: result.session,
          method,
          expiresAt: auth.expiresAt
        });
      } else {
        state.update(s => ({ ...s, loading: false }));
      }

      return result;
    } catch (error: any) {
      state.update(s => ({ ...s, loading: false }));
      return { success: false, error: error.message || 'Login failed' };
    }
  }

  function logout(): void {
    storage.clear();
    state.set({ loading: false, isAuthenticated: false, token: null, user: null, session: null, method: null, expiresAt: null });
  }

  // Helpers
  const isAuthenticated = derived(state, $s => $s.isAuthenticated);
  const user = derived(state, $s => $s.user);
  const session = derived(state, $s => $s.session);
  const programs = derived(state, $s => $s.user?.programs ?? []);
  const groups = derived(state, $s => $s.user?.groups ?? []);
  const isSuperuser = derived(state, $s => $s.user?.isSuperuser ?? false);
  const enabledProviders = Object.entries(providers)
    .filter(([_, p]) => p.isEnabled)
    .map(([name, p]) => ({ name, label: p.label, icon: p.icon }));

  return {
    subscribe: state.subscribe,
    init,
    login,
    loginBasic,
    logout,
    // Derived
    isAuthenticated,
    user,
    session,
    programs,
    groups,
    isSuperuser,
    // Utils
    getToken: () => get(state).token,
    hasProgram: (slug: string) => get(state).user?.programs.includes(slug) ?? false,
    hasGroup: (name: string) => get(state).user?.groups.includes(name) ?? false,
    storage,
    enabledProviders
  };
}

export type NavAuthStore = ReturnType<typeof createNavAuthStore>;
