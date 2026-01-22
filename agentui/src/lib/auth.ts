// src/lib/auth.ts

import { config } from '$lib/config';
import { createNavAuthConfig, createNavAuthStore } from '$lib/navauth';

const navAuthConfig = createNavAuthConfig(config.apiBaseUrl, {
  loginEndpoint: '/api/v1/login',
  callbackPath: '/auth/callback',
  storageKey: config.storageNamespace, // AuthStorage adds .token suffix internally
  providers: {
    basic: {
      enabled: true,
      label: 'Sign in',
      authHeader: 'BasicAuth'
    },
    azure: {
      enabled: true,
      label: 'Azure Login',
      authEndpoint: `${config.apiBaseUrl}/api/v1/auth/azure/`,
      sessionEndpoint: '/api/v1/user/session',
      callbackPath: '/auth/sso'
    },
    adfs: {
      enabled: true,
      label: 'SSO Login',
      authEndpoint: `${config.apiBaseUrl}/api/v1/auth/adfs/`,
      sessionEndpoint: '/api/v1/user/session',
      callbackPath: '/auth/sso'
    }
    // Añadir más providers según necesidad:
    // google: {
    //   enabled: true,
    //   clientId: import.meta.env.VITE_GOOGLE_CLIENT_ID,
    //   label: 'Continue with Google'
    // }
  }
});

export const auth = createNavAuthStore(navAuthConfig);
