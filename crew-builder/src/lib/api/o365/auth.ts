import { apiClient } from '../client';

export interface StartSessionPayload {
  scopes?: string[];
  redirect_uri?: string;
  credentials?: Record<string, unknown>;
}

export interface RemoteAuthSummary {
  expires_on?: number | string;
  scope?: string;
  token_source?: string;
  account?: {
    home_account_id?: string;
    environment?: string;
    username?: string;
  };
  user?: {
    name?: string;
    preferred_username?: string;
    oid?: string;
    tid?: string;
  };
}

export interface RemoteAuthSession {
  session_id: string;
  status: string;
  auth_url?: string;
  device_flow?: {
    user_code?: string;
    verification_uri?: string;
    verification_uri_complete?: string;
    message?: string;
    expires_in?: number;
    interval?: number;
  };
  result?: RemoteAuthSummary;
  error?: string;
  created_at?: string;
  updated_at?: string;
  expires_at?: string;
}

export async function startInteractiveSession(payload: StartSessionPayload = {}) {
  const response = await apiClient.post<RemoteAuthSession>(
    '/api/v1/o365/auth/sessions',
    payload
  );
  return response.data;
}

export async function getSessionStatus(sessionId: string) {
  const response = await apiClient.get<RemoteAuthSession>(
    `/api/v1/o365/auth/sessions/${encodeURIComponent(sessionId)}`
  );
  return response.data;
}

export async function cancelSession(sessionId: string) {
  const response = await apiClient.delete<{ session_id: string; status: string }>(
    `/api/v1/o365/auth/sessions/${encodeURIComponent(sessionId)}`
  );
  return response.data;
}
