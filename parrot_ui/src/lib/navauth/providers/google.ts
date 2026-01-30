// src/lib/navauth/providers/google.ts

import { AuthProvider } from './base';
import type { AuthResult } from '../types';
import type { GoogleProviderConfig } from '../config';

export interface GoogleAuthConfig extends GoogleProviderConfig {
  clientId: string;
  scopes?: string[];
}

// Google Identity Services types
declare global {
  interface Window {
    google?: {
      accounts: {
        oauth2: {
          initTokenClient(config: {
            client_id: string;
            scope: string;
            callback: (response: { access_token?: string; error?: string }) => void;
          }): { requestAccessToken(): void };
          revoke(token: string, callback?: () => void): void;
        };
      };
    };
  }
}

export class GoogleAuthProvider extends AuthProvider<GoogleAuthConfig> {
  readonly name = 'google' as const;
  private client: ReturnType<typeof window.google.accounts.oauth2.initTokenClient> | null = null;
  private pendingResolve: ((result: AuthResult) => void) | null = null;

  constructor(
    config: GoogleAuthConfig,
    private exchangeToken: (googleToken: string) => Promise<AuthResult>
  ) {
    super(config);
  }

  async init(): Promise<void> {
    if (typeof window === 'undefined' || !this.isEnabled) return;
    await this.loadScript();
    this.initClient();
  }

  private loadScript(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (window.google?.accounts) {
        resolve();
        return;
      }

      const script = document.createElement('script');
      script.src = 'https://accounts.google.com/gsi/client';
      script.async = true;
      script.defer = true;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error('Failed to load Google Identity Services'));
      document.head.appendChild(script);
    });
  }

  private initClient(): void {
    if (!window.google?.accounts) return;

    const scopes = this.config.scopes || ['openid', 'email', 'profile'];

    this.client = window.google.accounts.oauth2.initTokenClient({
      client_id: this.config.clientId,
      scope: scopes.join(' '),
      callback: (response) => this.handleResponse(response)
    });
  }

  private async handleResponse(response: { access_token?: string; error?: string }): Promise<void> {
    if (response.error || !response.access_token) {
      this.pendingResolve?.({ success: false, error: response.error || 'No token received' });
      return;
    }

    // Intercambiar token de Google por token de nuestra API
    const result = await this.exchangeToken(response.access_token);
    this.pendingResolve?.(result);
  }

  async login(): Promise<AuthResult> {
    if (!this.client) {
      return { success: false, error: 'Google client not initialized' };
    }

    return new Promise((resolve) => {
      this.pendingResolve = resolve;
      this.client!.requestAccessToken();
    });
  }

  initiateFlow(): void {
    this.client?.requestAccessToken();
  }

  async logout(): Promise<void> {
    // Google doesn't require explicit logout, but we can revoke if we stored the token
  }
}
