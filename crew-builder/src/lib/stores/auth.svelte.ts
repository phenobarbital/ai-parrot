import { browser } from '$app/environment';
import { goto } from '$app/navigation';
import type { LoginResponse, SessionData } from '$lib/auth/auth';
import { login as loginRequest } from '$lib/auth/auth';

class AuthStore {
  user = $state<LoginResponse | null>(null);
  session = $state<SessionData | null>(null);
  token = $state<string | null>(null);
  loading = $state(true);
  isAuthenticated = $derived(Boolean(this.token));
  currentUser = $derived(
    this.user
      ? {
          id: this.user.id,
          user_id: this.user.user_id,
          username: this.user.username,
          email: this.user.email,
          name: this.user.name
        }
      : null
  );

  init() {
    if (!browser) return;

    const storedToken = localStorage.getItem('token');
    const storedUser = localStorage.getItem('user');
    const storedSession = localStorage.getItem('session');

    if (storedToken && storedUser) {
      try {
        this.user = JSON.parse(storedUser);
        this.token = storedToken;

        if (storedSession) {
          this.session = JSON.parse(storedSession);
        }
      } catch (error) {
        console.error('Failed to parse stored auth data', error);
        this.clearStorage();
      }
    } else {
      this.user = null;
      this.session = null;
      this.token = null;
    }

    this.loading = false;
  }

  private clearStorage() {
    if (!browser) return;

    localStorage.removeItem('token');
    localStorage.removeItem('user');
    localStorage.removeItem('session');
    localStorage.removeItem('user_id');
    localStorage.removeItem('id');
    localStorage.removeItem('username');
    localStorage.removeItem('email');

    this.user = null;
    this.session = null;
    this.token = null;
  }

  private saveToStorage(data: LoginResponse) {
    if (!browser) return;

    // Save token
    localStorage.setItem('token', data.token);

    // Save full user data
    localStorage.setItem('user', JSON.stringify(data));

    // Save session data
    if (data.session) {
      localStorage.setItem('session', JSON.stringify(data.session));
    }

    // Save basic user info for quick access
    localStorage.setItem('user_id', data.user_id.toString());
    localStorage.setItem('id', data.id);
    localStorage.setItem('username', data.username);
    localStorage.setItem('email', data.email);
  }

  async login(username: string, password: string) {
    this.loading = true;

    try {
      const response = await loginRequest({ username, password });

      const data = response.data;

      if (!data?.token) {
        throw new Error('Authentication token missing from response');
      }

      this.user = data;
      this.session = data.session;
      this.token = data.token;
      this.loading = false;

      this.saveToStorage(data);

      await goto('/');

      return { success: true };
    } catch (error: any) {
      this.loading = false;

      // Extract error message from response
      let message = 'Invalid credentials';

      if (error.response) {
        const status = error.response.status;
        const data = error.response.data;

        // Handle specific error codes
        if (status === 403) {
          message = data?.message || 'Access forbidden. Please check your credentials.';
        } else if (status === 401) {
          message = data?.message || 'Invalid username or password.';
        } else if (status === 400) {
          message = data?.message || 'Invalid request. Please check your input.';
        } else if (status >= 400 && status < 500) {
          message = data?.message || `Authentication failed (${status}).`;
        } else if (status >= 500) {
          message = data?.message || 'Server error. Please try again later.';
        }
      } else if (error.message) {
        message = error.message;
      }

      return {
        success: false,
        error: message,
        status: error.response?.status
      };
    }
  }

  async logout() {
    this.clearStorage();
    this.loading = false;

    await goto('/login');
  }

  checkAuth() {
    if (!browser) return false;
    return Boolean(localStorage.getItem('token'));
  }
}

export const authStore = new AuthStore();
