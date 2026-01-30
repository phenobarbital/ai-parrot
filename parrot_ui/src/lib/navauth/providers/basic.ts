// src/lib/navauth/providers/basic.ts

import { AuthProvider } from './base';
import type { AuthResult, AuthResponse, UserSession } from '../types';
import type { BasicProviderConfig } from '../config';

export interface BasicAuthConfig extends BasicProviderConfig {
  authHeader: string;  // 'BasicAuth'
}

export interface BasicCredentials {
  username: string;
  password: string;
}

export class BasicAuthProvider extends AuthProvider<BasicAuthConfig> {
  readonly name = 'basic' as const;

  constructor(
    config: BasicAuthConfig,
    private apiUrl: string,
    private endpoint: string
  ) {
    super(config);
  }

  async login(credentials: BasicCredentials): Promise<AuthResult> {
    try {
      const response = await fetch(`${this.apiUrl}${this.endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-auth-method': this.config.authHeader
        },
        body: JSON.stringify(credentials)
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({ message: 'Login failed' }));
        return { success: false, error: error.reason || error.message || `HTTP ${response.status}` };
      }

      const data: AuthResponse = await response.json();

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
      let errorMessage = error.message || 'Network error';
      if (errorMessage === 'Failed to fetch') {
        errorMessage = 'Unable to connect';
      }
      return {
        success: false,
        error: errorMessage
      };
    }
  }
}
