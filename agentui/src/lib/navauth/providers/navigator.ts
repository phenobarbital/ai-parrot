// src/lib/navauth/providers/navigator.ts

import { AuthProvider } from './base';
import type { AuthResult } from '../types';
import type { NavigatorProviderConfig } from '../config';

export class NavigatorAuthProvider extends AuthProvider<NavigatorProviderConfig> {
    // The name will be set dynamically in constructor but we keep the property
    readonly name: string;

    constructor(
        config: NavigatorProviderConfig,
        private callbackUrl: string,
        private apiBaseUrl: string,
        name: string = 'navigator'
    ) {
        super(config);
        this.name = name;
    }

    async login(credentials?: unknown): Promise<AuthResult> {
        // If we receive URLSearchParams, it's a callback
        if (credentials instanceof URLSearchParams) {
            return this.handleCallback(credentials);
        }

        // Otherwise, initiate flow
        this.initiateFlow();
        return { success: false, error: 'redirect_initiated' };
    }

    initiateFlow(): void {
        const returnUrl = encodeURIComponent(`${this.callbackUrl}?provider=${this.name}`);
        // User starts session on IDP
        window.location.href = `${this.config.authEndpoint}?return_url=${returnUrl}`;
    }

    async handleCallback(params: URLSearchParams): Promise<AuthResult> {
        const token = params.get('token');
        const type = params.get('type');

        if (!token) {
            return { success: false, error: 'No token in callback' };
        }

        if (type && type.toLowerCase() !== 'bearer') {
            return { success: false, error: `Unsupported token type: ${type}` };
        }

        // Call session endpoint to get user profile
        return this.fetchUserSession(token);
    }

    private async fetchUserSession(token: string): Promise<AuthResult> {
        const sessionEndpoint = this.config.sessionEndpoint || '/api/v1/user/session';
        const url = sessionEndpoint.startsWith('http')
            ? sessionEndpoint
            : `${this.apiBaseUrl}${sessionEndpoint}`;

        try {
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                return { success: false, error: error.message || 'Failed to fetch user session' };
            }

            const data = await response.json();

            // Return unified AuthResult structure
            return {
                success: true,
                token: token,
                session: data,
                user: {
                    id: data.user_id,
                    username: data.username,
                    email: data.email,
                    displayName: `${data.first_name} ${data.last_name}`,
                    firstName: data.first_name,
                    lastName: data.last_name,
                    isSuperuser: data.superuser,
                    groups: data.groups,
                    groupIds: data.group_id,
                    programs: data.programs,
                    domain: data.domain
                },
                expiresAt: Math.floor(Date.now() / 1000) + 86400, // Default 24h if not specified
                sessionId: data.session_id || ''
            };
        } catch (error: any) {
            return { success: false, error: error.message || 'Network error fetching session' };
        }
    }
}
