import { goto } from '$app/navigation';
import { browser } from '$app/environment';
import { auth as authApi } from '$lib/api';
import { derived, writable } from 'svelte/store';

export interface AuthState {
  user: unknown;
  token: string | null;
  isAuthenticated: boolean;
  loading: boolean;
}

function createAuthStore() {
  const { subscribe, set, update } = writable<AuthState>({
    user: null,
    token: null,
    isAuthenticated: false,
    loading: true
  });

  return {
    subscribe,
    init: async () => {
      if (!browser) return;

      const token = localStorage.getItem('token');
      const user = localStorage.getItem('user');

      if (token && user) {
        try {
          set({
            user: JSON.parse(user),
            token,
            isAuthenticated: true,
            loading: false
          });
        } catch (error) {
          console.error('Failed to parse stored user', error);
          localStorage.removeItem('token');
          localStorage.removeItem('user');
          set({
            user: null,
            token: null,
            isAuthenticated: false,
            loading: false
          });
        }
      } else {
        set({
          user: null,
          token: null,
          isAuthenticated: false,
          loading: false
        });
      }
    },
    login: async (email: string, password: string) => {
      update((state) => ({ ...state, loading: true }));
      try {
        const response = await authApi.login(
          { username: email, password },
          { 'x-auth-method': 'BasicAuth' }
        );
        const { token } = response.data as { token: string };
        const user = response.data;

        if (browser) {
          localStorage.setItem('token', token);
          localStorage.setItem('user', JSON.stringify(response.data));
        }

        set({
          user,
          token,
          isAuthenticated: true,
          loading: false
        });

        await goto('/');

        return { success: true };
      } catch (error: unknown) {
        const apiMessage =
          typeof error === 'object' &&
          error !== null &&
          'response' in error &&
          typeof (error as { response?: { data?: { message?: string } } }).response?.data?.message === 'string'
            ? (error as { response?: { data?: { message?: string } } }).response?.data?.message
            : undefined;
        const message = apiMessage ?? (error instanceof Error ? error.message : 'Invalid credentials');
        update((state) => ({ ...state, loading: false }));
        return {
          success: false,
          error: message
        };
      }
    },
    logout: async () => {
      if (browser) {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
      }

      set({
        user: null,
        token: null,
        isAuthenticated: false,
        loading: false
      });

      await goto('/login');
    },
    checkAuth: () => {
      if (!browser) return false;
      const token = localStorage.getItem('token');
      return Boolean(token);
    }
  };
}

export const authStore = createAuthStore();
export const isAuthenticated = derived(authStore, ($authStore) => $authStore.isAuthenticated);
export const currentUser = derived(authStore, ($authStore) => $authStore.user);
