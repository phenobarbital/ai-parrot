// src/lib/navauth/providers/base.ts

import type { AuthMethod, AuthResult } from '../types';
import type { ProviderConfig } from '../config';

export abstract class AuthProvider<TConfig extends ProviderConfig = ProviderConfig> {
  abstract readonly name: AuthMethod;

  constructor(public readonly config: TConfig) {}

  abstract login(credentials?: unknown): Promise<AuthResult>;

  async init(): Promise<void> {}

  initiateFlow?(): void;

  handleCallback?(params: URLSearchParams): Promise<AuthResult>;

  async logout(): Promise<void> {}

  get isEnabled(): boolean {
    return this.config.enabled;
  }

  get label(): string {
    return this.config.label || this.name;
  }

  get icon(): string | undefined {
    return this.config.icon;
  }
}
