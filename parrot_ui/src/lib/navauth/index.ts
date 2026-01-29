// src/lib/navauth/index.ts

// Types
export * from './types';

// Config
export {
  createNavAuthConfig,
  DEFAULT_PROVIDERS,
  type NavAuthConfig,
  type ProvidersConfig,
  type ProviderConfig,
  type BasicProviderConfig,
  type SSOProviderConfig,
  type GoogleProviderConfig,
  type MicrosoftProviderConfig,
  type NavigatorProviderConfig
} from './config';

// Storage
export { AuthStorage } from './storage';

// Store
export { createNavAuthStore, type NavAuthStore } from './store.svelte';

// Providers
export { AuthProvider } from './providers/base';
export { BasicAuthProvider } from './providers/basic';
export { SSOProvider } from './providers/sso';
export { GoogleAuthProvider } from './providers/google';
export { MicrosoftAuthProvider } from './providers/microsoft';
export { NavigatorAuthProvider } from './providers/navigator';
export { providerRegistry, type ProviderMap } from './providers/registry';

// Components
export { default as LoginForm } from './components/LoginForm.svelte';
export { default as ProviderButtons } from './components/ProviderButtons.svelte';
export { default as AuthGuard } from './components/AuthGuard.svelte';
