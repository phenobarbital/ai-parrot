import apiClient from '../api/client';

export interface LoginPayload {
  username: string;
  password: string;
}

export interface SessionData {
  user_id: number;
  username: string;
  first_name: string;
  last_name: string;
  email: string;
  enabled: boolean;
  superuser: boolean;
  last_login: string;
  title: string | null;
  associate_id: number | null;
  group_id: number[];
  groups: string[];
  programs: string[];
  manager_id: number | null;
  user: string;
  domain: string;
}

export interface LoginResponse {
  token: string;
  session: SessionData;
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
  token_type: string;
  auth_method: string;
}

export function login(payload: LoginPayload) {
  return apiClient.post<LoginResponse>('/api/v1/login', payload, {
    headers: {
      'x-auth-method': 'BasicAuth'
    }
  });
}

export const auth = {
  login
};
