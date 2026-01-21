// src/lib/navauth/providers/sso.ts

import { AuthProvider } from './base';
import type { AuthResult } from '../types';
import type { SSOProviderConfig } from '../config';

export interface SSOConfig extends SSOProviderConfig {
  redirectUrl: string;      // URL del SSO externo
  returnParam?: string;     // Query param para callback URL (default: 'return_url')
}

export class SSOProvider extends AuthProvider<SSOConfig> {
  readonly name = 'sso' as const;

  constructor(
    config: SSOProviderConfig,
    private callbackUrl: string,
    private onTokenReceived?: (token: string) => Promise<AuthResult>
  ) {
    super(config);
  }

  async login(): Promise<AuthResult> {
    // SSO siempre requiere redirect
    this.initiateFlow();
    return { success: false, error: 'redirect_initiated' };
  }

  initiateFlow(): void {
    const returnParam = this.config.returnParam || 'return_url';
    const returnUrl = encodeURIComponent(this.callbackUrl);
    window.location.href = `${this.config.redirectUrl}?${returnParam}=${returnUrl}`;
  }

  async handleCallback(params: URLSearchParams): Promise<AuthResult> {
    const token = params.get('token');
    const type = params.get('type');

    if (!token) {
      return { success: false, error: 'No token in callback' };
    }

    if (type && type.toLowerCase() !== 'bearer') {
      return { success: false, error: `Unsupported token type: ${type}` };
    }

    // Si hay handler para obtener user info del token
    if (this.onTokenReceived) {
      return this.onTokenReceived(token);
    }

    // Retornar token crudo - el store debe obtener user info
    return {
      success: true,
      token
    };
  }
}
