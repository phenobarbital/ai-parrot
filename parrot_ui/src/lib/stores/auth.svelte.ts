import apiClient from '$lib/api/http';
import { config } from '$lib/config';

const STORAGE_KEY = config.tokenStorageKey;

class AuthStore {
  loading = $state(true);
  isAuthenticated = $state(false);
  token = $state<string | null>(null);
  user = $state<{ username: string } | null>(null);

  async init() {
    if (typeof window === 'undefined') return;
    const storedToken = localStorage.getItem(STORAGE_KEY);
    if (storedToken) {
      this.loading = false;
      this.isAuthenticated = true;
      this.token = storedToken;
    } else {
      this.loading = false;
      this.isAuthenticated = false;
      this.token = null;
      this.user = null;
    }
  }

  async login(username: string, password: string) {
    this.loading = true;
    try {
      const { data } = await apiClient.post(config.authUrl, { username, password });
      const accessToken = data?.access_token || data?.token;
      if (typeof window !== 'undefined' && accessToken) {
        localStorage.setItem(STORAGE_KEY, accessToken);
      }
      this.loading = false;
      this.isAuthenticated = true;
      this.token = accessToken || null;
      this.user = { username };
      return { success: true };
    } catch (error: any) {
      this.loading = false;
      this.isAuthenticated = false;
      this.token = null;
      this.user = null;
      return {
        success: false,
        error: error?.response?.data?.message || error?.message || 'Login failed'
      };
    }
  }

  logout() {
    if (typeof window !== 'undefined') {
      localStorage.removeItem(STORAGE_KEY);
    }
    this.loading = false;
    this.isAuthenticated = false;
    this.token = null;
    this.user = null;
  }

  getToken() {
    return this.token;
  }
}

export const authStore = new AuthStore();
