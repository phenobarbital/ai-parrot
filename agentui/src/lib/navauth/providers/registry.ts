// src/lib/navauth/providers/registry.ts

import type { AuthProvider } from './base';
import type { AuthResult } from '../types';
import { BasicAuthProvider } from './basic';
import { SSOProvider } from './sso';
import { GoogleAuthProvider } from './google';
import { MicrosoftAuthProvider } from './microsoft';
import { NavigatorAuthProvider } from './navigator';
import type { ProviderConfig, NavAuthConfig } from '../config';

export type ProviderMap = Record<string, AuthProvider>;

export class ProviderRegistry {
  private providers: ProviderMap = {};
  private config: NavAuthConfig | null = null;

  init(config: NavAuthConfig): ProviderMap {
    this.config = config;
    // Clear existing while keeping the reference
    for (const key in this.providers) {
      delete this.providers[key];
    }

    const { apiBaseUrl, loginEndpoint, callbackPath, providers: providerConfigs } = config;
    const origin = typeof window !== 'undefined' ? window.location.origin : '';

    // BasicAuth
    if (providerConfigs.basic?.enabled) {
      this.providers.basic = new BasicAuthProvider(
        providerConfigs.basic,
        apiBaseUrl,
        loginEndpoint
      );
    }

    // SSO
    if (providerConfigs.sso?.enabled) {
      this.providers.sso = new SSOProvider(
        providerConfigs.sso,
        `${origin}${callbackPath}/sso`,
        (token) => this.exchangeExternalToken(token, 'sso')
      );
    }

    // Google
    if (providerConfigs.google?.enabled) {
      this.providers.google = new GoogleAuthProvider(
        providerConfigs.google,
        (token) => this.exchangeExternalToken(token, 'google')
      );
    }

    // Microsoft
    if (providerConfigs.microsoft?.enabled) {
      this.providers.microsoft = new MicrosoftAuthProvider(
        providerConfigs.microsoft,
        `${callbackPath}/microsoft`,
        (token) => this.exchangeExternalToken(token, 'microsoft')
      );
    }

    // Azure
    if (providerConfigs.azure?.enabled) {
      this.providers.azure = new NavigatorAuthProvider(
        providerConfigs.azure,
        `${origin}${providerConfigs.azure.callbackPath || '/auth/sso'}`,
        apiBaseUrl,
        'azure'
      );
    }

    // ADFS
    if (providerConfigs.adfs?.enabled) {
      this.providers.adfs = new NavigatorAuthProvider(
        providerConfigs.adfs,
        `${origin}${providerConfigs.adfs.callbackPath || '/auth/sso'}`,
        apiBaseUrl,
        'adfs'
      );
    }

    return this.providers;
  }

  // Intercambia token externo (Google/Microsoft/SSO) por token de nuestra API
  private async exchangeExternalToken(externalToken: string, method: string): Promise<AuthResult> {
    if (!this.config) {
      return { success: false, error: 'Registry not initialized' };
    }

    try {
      const response = await fetch(`${this.config.apiBaseUrl}${this.config.loginEndpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-auth-method': method
        },
        body: JSON.stringify({ token: externalToken })
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        return { success: false, error: error.message || 'Token exchange failed' };
      }

      const data = await response.json();

      return {
        success: true,
        token: data.token,
        session: data.session,
        user: {
          id: data.user_id,
          username: data.username,
          email: data.email,
          displayName: data.name,
          firstName: data.session.first_name,
          lastName: data.session.last_name,
          isSuperuser: data.session.superuser,
          groups: data.session.groups,
          groupIds: data.session.group_id,
          programs: data.session.programs,
          domain: data.session.domain
        },
        expiresAt: data.expires_in,
        sessionId: data.session_id
      };
    } catch (error: any) {
      return { success: false, error: error.message || 'Network error' };
    }
  }

  get(name: string): AuthProvider | undefined {
    return this.providers[name];
  }

  getEnabled(): Array<{ name: string; provider: AuthProvider }> {
    return Object.entries(this.providers)
      .filter(([_, p]) => p.isEnabled)
      .map(([name, provider]) => ({ name, provider }));
  }

  // Para registrar providers custom
  register(name: string, provider: AuthProvider): void {
    this.providers[name] = provider;
  }
}

export const providerRegistry = new ProviderRegistry();
