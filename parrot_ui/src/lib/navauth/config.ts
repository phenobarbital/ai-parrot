// src/lib/navauth/config.ts

export interface ProviderConfig {
  enabled: boolean;
  label?: string;
  icon?: string;
}

export interface BasicProviderConfig extends ProviderConfig {
  authHeader: string;
}

export interface SSOProviderConfig extends ProviderConfig {
  redirectUrl: string;
  returnParam?: string;
}

export interface GoogleProviderConfig extends ProviderConfig {
  clientId: string;
  scopes?: string[];
}

export interface MicrosoftProviderConfig extends ProviderConfig {
  clientId: string;
  tenantId?: string;
  scopes?: string[];
  redirectUri?: string;
}

export interface NavigatorProviderConfig extends ProviderConfig {
  authEndpoint: string;
  sessionEndpoint?: string;
  callbackPath?: string;
}

export interface ProvidersConfig {
  basic?: BasicProviderConfig;
  sso?: SSOProviderConfig;
  google?: GoogleProviderConfig;
  microsoft?: MicrosoftProviderConfig;
  azure?: NavigatorProviderConfig;
  adfs?: NavigatorProviderConfig;
  custom?: Record<string, ProviderConfig>;
}

export interface NavAuthConfig {
  apiBaseUrl: string;
  loginEndpoint: string;
  callbackPath: string;
  storageKey: string;
  providers: ProvidersConfig;
}

export const DEFAULT_PROVIDERS: ProvidersConfig = {
  basic: {
    enabled: true,
    label: 'Sign in',
    authHeader: 'BasicAuth'
  }
};

export function createNavAuthConfig(
  apiBaseUrl: string,
  overrides: Partial<Omit<NavAuthConfig, 'apiBaseUrl'>> = {}
): NavAuthConfig {
  return {
    apiBaseUrl,
    loginEndpoint: overrides.loginEndpoint ?? '/api/v1/login',
    callbackPath: overrides.callbackPath ?? '/auth/callback',
    storageKey: overrides.storageKey ?? 'navauth',
    providers: overrides.providers ?? DEFAULT_PROVIDERS
  };
}
