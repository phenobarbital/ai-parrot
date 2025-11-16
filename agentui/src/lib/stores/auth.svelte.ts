import apiClient from '$lib/api/http';
import { writable, get } from 'svelte/store';
import { config } from '$lib/config';

type AuthState = {
  loading: boolean;
  isAuthenticated: boolean;
  token: string | null;
  user: { username: string } | null;
};

const STORAGE_KEY = config.tokenStorageKey;

function createAuthStore() {
  const internal = writable<AuthState>({
    loading: true,
    isAuthenticated: false,
    token: null,
    user: null
  });

  const { subscribe, update, set } = internal;

  async function init() {
    if (typeof window === 'undefined') return;
    const token = localStorage.getItem(STORAGE_KEY);
    if (token) {
      set({ loading: false, isAuthenticated: true, token, user: null });
    } else {
      set({ loading: false, isAuthenticated: false, token: null, user: null });
    }
  }

  async function login(username: string, password: string) {
    update((state) => ({ ...state, loading: true }));
    try {
      const { data } = await apiClient.post(config.authUrl, { username, password });
      const token = data?.access_token || data?.token;
      if (typeof window !== 'undefined' && token) {
        localStorage.setItem(STORAGE_KEY, token);
      }
      set({ loading: false, isAuthenticated: true, token: token || null, user: { username } });
      return { success: true };
    } catch (error: any) {
      set({ loading: false, isAuthenticated: false, token: null, user: null });
      return {
        success: false,
        error: error?.response?.data?.message || error?.message || 'Login failed'
      };
    }
  }

  function logout() {
    if (typeof window !== 'undefined') {
      localStorage.removeItem(STORAGE_KEY);
    }
    set({ loading: false, isAuthenticated: false, token: null, user: null });
  }

  function getToken() {
    return get(internal).token;
  }

  return {
    subscribe,
    init,
    login,
    logout,
    getToken
  };
}

export const authStore = createAuthStore();
