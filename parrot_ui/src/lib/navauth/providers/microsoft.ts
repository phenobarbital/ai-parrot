// src/lib/navauth/providers/microsoft.ts

import { AuthProvider } from './base';
import type { AuthResult } from '../types';
import type { MicrosoftProviderConfig } from '../config';

export interface MicrosoftAuthConfig extends MicrosoftProviderConfig {
  clientId: string;
  tenantId?: string;        // 'common' | 'organizations' | 'consumers' | tenant-id
  scopes?: string[];
  redirectUri?: string;     // Override callback URI
}

// MSAL types (simplified)
interface MsalAccount {
  username: string;
  name?: string;
}

interface MsalResponse {
  accessToken: string;
  account: MsalAccount | null;
}

interface MsalInstance {
  initialize(): Promise<void>;
  loginPopup(request: { scopes: string[] }): Promise<{ accessToken: string; account: unknown }>;
  loginRedirect(request: { scopes: string[] }): Promise<void>;
  handleRedirectPromise(): Promise<{ accessToken: string } | null>;
  logoutPopup(): Promise<void>;
}

export class MicrosoftAuthProvider extends AuthProvider<MicrosoftProviderConfig> {
  readonly name = 'microsoft' as const;
  private msal: MsalInstance | null = null;

  constructor(
    config: MicrosoftProviderConfig,
    private callbackPath: string,
    private exchangeToken: (msToken: string) => Promise<AuthResult>
  ) {
    super(config);
  }

  async init(): Promise<void> {
    if (typeof window === 'undefined' || !this.isEnabled) return;

    try {
      // Dynamic import - falla silenciosamente si no está instalado
      const msal = await import('@azure/msal-browser').catch(() => null);
      if (!msal) {
        console.warn('NavAuth: @azure/msal-browser not installed, Microsoft auth disabled');
        return;
      }
      await this.initClient(msal);
    } catch (e) {
      console.warn('MSAL init failed:', e);
    }
  }

  private async initClient(msal: typeof import('@azure/msal-browser')): Promise<void> {
    const { PublicClientApplication } = msal;

    const msalConfig = {
      auth: {
        clientId: this.config.clientId,
        authority: `https://login.microsoftonline.com/${this.config.tenantId || 'common'}`,
        redirectUri: this.config.redirectUri || `${window.location.origin}${this.callbackPath}`
      },
      cache: {
        cacheLocation: 'sessionStorage' as const,
        storeAuthStateInCookie: false
      }
    };

    this.msal = new PublicClientApplication(msalConfig);
    await this.msal.initialize();
  }

  async login(): Promise<AuthResult> {
    if (!this.msal) {
      return { success: false, error: 'MSAL not initialized' };
    }

    const scopes = this.config.scopes || ['openid', 'profile', 'email'];

    try {
      const response = await this.msal.loginPopup({ scopes });

      if (response?.accessToken) {
        return this.exchangeToken(response.accessToken);
      }

      return { success: false, error: 'No token received' };
    } catch (error: any) {
      return { success: false, error: error.message || 'Microsoft login failed' };
    }
  }

  async initiateFlow(): Promise<void> {
    if (!this.msal) return;

    const scopes = this.config.scopes || ['openid', 'profile', 'email'];
    await this.msal.loginRedirect({ scopes });
  }

  async handleCallback(): Promise<AuthResult> {
    if (!this.msal) {
      return { success: false, error: 'MSAL not initialized' };
    }

    const response = await this.msal.handleRedirectPromise();

    if (response?.accessToken) {
      return this.exchangeToken(response.accessToken);
    }

    return { success: false, error: 'No token in redirect response' };
  }

  async logout(): Promise<void> {
    try {
      await this.msal?.logoutPopup();
    } catch {
      // Silently fail - user is logged out locally anyway
    }
  }
}
