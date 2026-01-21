// src/lib/navauth/types.ts

export type AuthMethod = 'basic' | 'sso' | 'google' | 'microsoft' | string;

// Respuesta completa del endpoint /api/v1/login
export interface AuthResponse {
  token: string;
  token_type: 'Bearer';
  auth_method: AuthMethod;
  session: UserSession;
  username: string;
  id: string;
  user_id: number;
  name: string;
  email: string;
  upn: string;
  created: number;
  last_visit: number;
  session_id: string;
  expires_in: number;
}

// Perfil completo (session)
export interface UserSession {
  user_id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  enabled: boolean;
  superuser: boolean;
  last_login: string;
  title?: string;
  associate_id?: string;
  associate_oid?: string;
  user?: string;
  domain?: string;
  group_id: number[];
  groups: string[];
  programs: string[];
  birthday?: string;
  start_date?: string;
  manager_id?: string;
  [key: string]: unknown;
}

// Para uso en UI
export interface UserInfo {
  id: number;
  username: string;
  email: string;
  displayName: string;
  firstName: string;
  lastName: string;
  isSuperuser: boolean;
  groups: string[];
  groupIds: number[];
  programs: string[];
  domain?: string;
  avatar?: string;
}

// Resultado de operaciones auth
export interface AuthResult {
  success: boolean;
  error?: string;
  // On success:
  token?: string;
  user?: UserInfo;
  session?: UserSession;
  expiresAt?: number;
  sessionId?: string;
}

// localStorage structures
export interface StoredAuth {
  token: string;
  expiresAt: number;
  method: AuthMethod;
  sessionId: string;
}

export interface StoredProfile {
  user: UserInfo;
  session: UserSession;
  lastUpdated: number;
}
