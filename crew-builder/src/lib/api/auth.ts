import apiClient from './client';

export interface LoginPayload {
  username: string;
  password: string;
}

export function login(payload: LoginPayload, extraHeaders?: Record<string, string>) {
  return apiClient.post('/auth/login', payload, {
    headers: {
      ...(extraHeaders ?? {})
    }
  });
}

export const auth = {
  login
};
