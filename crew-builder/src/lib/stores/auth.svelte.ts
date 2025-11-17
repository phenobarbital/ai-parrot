import { browser } from '$app/environment';
import { goto } from '$app/navigation';
import type { Subscriber } from 'svelte/store';
import type { LoginResponse, SessionData } from '$lib/auth/auth';
import { login as loginRequest } from '$lib/auth/auth';

interface AuthState {
  user: LoginResponse | null;
  session: SessionData | null;
  token: string | null;
  loading: boolean;
  isAuthenticated: boolean;
}

class AuthStore {
  private state: AuthState = {
    user: null,
    session: null,
    token: null,
    loading: true,
    isAuthenticated: false
  };

  private subscribers = new Set<Subscriber<AuthState>>();

  get user() {
    return this.state.user;
  }

  set user(value: LoginResponse | null) {
    this.setState({ user: value });
  }

  get session() {
    return this.state.session;
  }

  set session(value: SessionData | null) {
    this.setState({ session: value });
  }

  get token() {
    return this.state.token;
  }

  set token(value: string | null) {
    this.setState({ token: value });
  }

  get loading() {
    return this.state.loading;
  }

  set loading(value: boolean) {
    this.setState({ loading: value });
  }

  get isAuthenticated() {
    return this.state.isAuthenticated;
  }

  get currentUser() {
    if (!this.state.user) return null;

    return {
      id: this.state.user.id,
      user_id: this.state.user.user_id,
      username: this.state.user.username,
      email: this.state.user.email,
      name: this.state.user.name
    };
  }

  subscribe(run: Subscriber<AuthState>) {
    run(this.state);
    this.subscribers.add(run);

    return () => {
      this.subscribers.delete(run);
    };
  }

  private notify() {
    for (const subscriber of this.subscribers) {
      subscriber(this.state);
    }
  }

  private setState(partial: Partial<AuthState>) {
    this.state = {
      ...this.state,
      ...partial
    };
    this.state.isAuthenticated = Boolean(this.state.token);
    this.notify();
  }

  init() {
    if (!browser) {
      this.loading = false;
      return;
    }

    const storedToken = localStorage.getItem('token');
    const storedUser = localStorage.getItem('user');
    const storedSession = localStorage.getItem('session');

    if (storedToken && storedUser) {
      try {
        const parsedUser = JSON.parse(storedUser) as LoginResponse;
        this.user = parsedUser;
        this.token = storedToken;

        if (storedSession) {
          this.session = JSON.parse(storedSession) as SessionData;
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

    localStorage.setItem('token', data.token);
    localStorage.setItem('user', JSON.stringify(data));

    if (data.session) {
      localStorage.setItem('session', JSON.stringify(data.session));
    }

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

      let message = 'Invalid credentials';

      if (error.response) {
        const status = error.response.status;
        const responseData = error.response.data;

        if (status === 403) {
          message = responseData?.message || 'Access forbidden. Please check your credentials.';
        } else if (status === 401) {
          message = responseData?.message || 'Invalid username or password.';
        } else if (status === 400) {
          message = responseData?.message || 'Invalid request. Please check your input.';
        } else if (status >= 400 && status < 500) {
          message = responseData?.message || `Authentication failed (${status}).`;
        } else if (status >= 500) {
          message = responseData?.message || 'Server error. Please try again later.';
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
