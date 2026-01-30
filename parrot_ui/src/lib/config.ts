const DEFAULT_API = 'http://localhost:5000';
const parseEnvBoolean = (value: string | boolean | undefined, defaultValue = false): boolean => {
  if (value === undefined || value === null) return defaultValue;
  if (typeof value === 'boolean') return value;
  return value.toLowerCase() === 'true' || value === '1';
};
const rawBaseUrl = import.meta.env?.VITE_API_URL ?? DEFAULT_API;
const apiBaseUrl = rawBaseUrl.replace(/\/$/, '');
const authUrlFromEnv = import.meta.env?.VITE_AUTH_URL;
const authUrl = (authUrlFromEnv ? authUrlFromEnv : `${apiBaseUrl}/api/v1/login`).replace(/\/$/, '');
const environmentLabel = import.meta.env?.VITE_AGENTUI_ENV || 'local';
const defaultUsername = import.meta.env?.VITE_AGENTUI_USERNAME || '';
const defaultPassword = import.meta.env?.VITE_AGENTUI_PASSWORD || '';
const apiWithCredentials = parseEnvBoolean(import.meta.env?.VITE_API_WITH_CREDENTIALS, false);
const storageNamespace = `agentui.${environmentLabel}`;
const appName = import.meta.env?.NAVIGATOR_APPNAME || 'Navigator Concierge';

export const config = {
  apiBaseUrl,
  authUrl,
  environmentLabel,
  defaultUsername,
  defaultPassword,
  apiWithCredentials,
  storageNamespace,
  tokenStorageKey: `${storageNamespace}.token`,
  conversationStoragePrefix: `${storageNamespace}.conversation`,
  appName: appName
};
