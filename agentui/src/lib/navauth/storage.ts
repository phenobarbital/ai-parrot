// src/lib/navauth/storage.ts

import type { StoredAuth, StoredProfile, AuthResponse, UserInfo, UserSession } from './types';

export class AuthStorage {
  constructor(private namespace: string) { }

  private get keys() {
    return {
      token: `${this.namespace}.token`,
      profile: `${this.namespace}.profile`
    };
  }

  // Token (separado para acceso rápido en interceptors)
  saveToken(data: { token: string; expiresAt: number; method: string; sessionId: string }): void {
    localStorage.setItem(this.keys.token, JSON.stringify(data));
  }

  getToken(): StoredAuth | null {
    const raw = localStorage.getItem(this.keys.token);
    if (!raw) return null;

    try {
      const data = JSON.parse(raw) as StoredAuth;
      // Check expiration
      if (data.expiresAt && Date.now() / 1000 > data.expiresAt) {
        this.clear();
        return null;
      }
      return data;
    } catch {
      // Fallback: assume raw token string if parse fails
      return {
        token: raw,
        expiresAt: 0,
        method: 'legacy',
        sessionId: ''
      };
    }
  }

  // Profile (session completa)
  saveProfile(user: UserInfo, session: UserSession): void {
    const data: StoredProfile = { user, session, lastUpdated: Date.now() };
    localStorage.setItem(this.keys.profile, JSON.stringify(data));
  }

  getProfile(): StoredProfile | null {
    const raw = localStorage.getItem(this.keys.profile);
    return raw ? JSON.parse(raw) : null;
  }

  // Procesa respuesta del backend
  saveAuthResponse(response: AuthResponse): { auth: StoredAuth; user: UserInfo } {
    const auth: StoredAuth = {
      token: response.token,
      expiresAt: response.expires_in,
      method: response.auth_method,
      sessionId: response.session_id
    };

    const user = this.mapToUserInfo(response.session, response.name);

    this.saveToken(auth);
    this.saveProfile(user, response.session);

    return { auth, user };
  }

  private mapToUserInfo(session: UserSession, displayName: string): UserInfo {
    return {
      id: session.user_id,
      username: session.username,
      email: session.email,
      displayName,
      firstName: session.first_name,
      lastName: session.last_name,
      isSuperuser: session.superuser,
      groups: session.groups,
      groupIds: session.group_id,
      programs: session.programs,
      domain: session.domain
    };
  }

  clear(): void {
    localStorage.removeItem(this.keys.token);
    localStorage.removeItem(this.keys.profile);
  }

  isAuthenticated(): boolean {
    return this.getToken() !== null;
  }
}
