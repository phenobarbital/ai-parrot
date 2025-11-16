const DEFAULT_API = 'http://localhost:5000';
const rawBaseUrl = import.meta.env?.VITE_API_URL ?? DEFAULT_API;
const apiBaseUrl = rawBaseUrl.replace(/\/$/, '');
const authUrlFromEnv = import.meta.env?.VITE_AUTH_URL;
const authUrl = (authUrlFromEnv ? authUrlFromEnv : `${apiBaseUrl}/api/v1/login`).replace(/\/$/, '');
const environmentLabel = import.meta.env?.VITE_AGENTUI_ENV || 'local';
const defaultUsername = import.meta.env?.VITE_AGENTUI_USERNAME || '';
const defaultPassword = import.meta.env?.VITE_AGENTUI_PASSWORD || '';
const storageNamespace = `agentui.${environmentLabel}`;

export const config = {
  apiBaseUrl,
  authUrl,
  environmentLabel,
  defaultUsername,
  defaultPassword,
  storageNamespace,
  tokenStorageKey: `${storageNamespace}.token`,
  conversationStoragePrefix: `${storageNamespace}.conversation`
};
