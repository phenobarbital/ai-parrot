import { browser } from '$app/environment';
import { goto } from '$app/navigation';
import { login as loginRequest } from '$lib/auth/auth';

class AuthStore {
  user = $state(null);
  token = $state(null);
  loading = $state(true);
  isAuthenticated = $derived(Boolean(this.token));

  init() {
    if (!browser) return;

    const storedToken = localStorage.getItem('token');
    const storedUser = localStorage.getItem('user');

    if (storedToken && storedUser) {
      try {
        this.user = JSON.parse(storedUser);
        this.token = storedToken;
      } catch (error) {
        console.error('Failed to parse stored user', error);
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        this.user = null;
        this.token = null;
      }
    } else {
      this.user = null;
      this.token = null;
    }

    this.loading = false;
  }

  async login(username, password) {
    this.loading = true;

    try {
      const response = await loginRequest(
        { username, password },
        { 'x-auth-method': 'BasicAuth' }
      );

      const data = response?.data ?? response;
      const token = data?.token;

      if (!token) {
        throw new Error('Authentication token missing from response');
      }

      this.user = data;
      this.token = token;
      this.loading = false;

      if (browser) {
        localStorage.setItem('token', token);
        localStorage.setItem('user', JSON.stringify(data));
      }

      await goto('/');

      return { success: true };
    } catch (error) {
      const apiMessage =
        typeof error === 'object' &&
        error !== null &&
        'response' in error &&
        typeof error.response?.data?.message === 'string'
          ? error.response.data.message
          : undefined;

      const message = apiMessage ?? (error instanceof Error ? error.message : 'Invalid credentials');

      this.loading = false;

      return {
        success: false,
        error: message
      };
    }
  }

  async logout() {
    if (browser) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
    }

    this.user = null;
    this.token = null;
    this.loading = false;

    await goto('/login');
  }

  checkAuth() {
    if (!browser) return false;
    return Boolean(localStorage.getItem('token'));
  }
}

export const authStore = new AuthStore();
