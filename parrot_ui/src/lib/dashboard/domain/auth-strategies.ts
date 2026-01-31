/**
 * Authentication strategies for DataSource.
 * Prioritized: jwt-storage for user sessions.
 */

// ============================================================================
// Auth Strategy Types
// ============================================================================

export type AuthStrategy =
    | { type: 'none' }
    | { type: 'basic'; username: string; password: string }
    | { type: 'apiKey'; key: string; header?: string; prefix?: string }
    | { type: 'bearer'; token: string }
    | { type: 'jwt-storage'; storageKey?: string }
    | { type: 'jwt-session'; sessionKey?: string }
    | { type: 'oauth2'; tokenEndpoint: string; clientId: string; clientSecret: string; scope?: string }
    | { type: 'custom'; getHeaders: () => Promise<Record<string, string>> };

// ============================================================================
// Auth Header Resolution
// ============================================================================

/** Cache for OAuth2 tokens */
const oauth2TokenCache = new Map<string, { token: string; expiresAt: number }>();

/**
 * Resolve authentication strategy to HTTP headers.
 */
export async function resolveAuthHeaders(auth: AuthStrategy): Promise<Record<string, string>> {
    switch (auth.type) {
        case 'none':
            return {};

        case 'basic': {
            const encoded = btoa(`${auth.username}:${auth.password}`);
            return { 'Authorization': `Basic ${encoded}` };
        }

        case 'apiKey': {
            const headerName = auth.header ?? 'X-API-Key';
            const value = auth.prefix ? `${auth.prefix} ${auth.key}` : auth.key;
            return { [headerName]: value };
        }

        case 'bearer':
            return { 'Authorization': `Bearer ${auth.token}` };

        case 'jwt-storage': {
            const key = auth.storageKey ?? 'auth_token';
            const token = localStorage.getItem(key);
            if (!token) {
                console.warn(`[AuthStrategy] No JWT found in localStorage key: ${key}`);
                return {};
            }
            return { 'Authorization': `Bearer ${token}` };
        }

        case 'jwt-session': {
            const key = auth.sessionKey ?? 'auth_token';
            const token = sessionStorage.getItem(key);
            if (!token) {
                console.warn(`[AuthStrategy] No JWT found in sessionStorage key: ${key}`);
                return {};
            }
            return { 'Authorization': `Bearer ${token}` };
        }

        case 'oauth2': {
            const cacheKey = `${auth.tokenEndpoint}:${auth.clientId}`;
            const cached = oauth2TokenCache.get(cacheKey);

            if (cached && cached.expiresAt > Date.now()) {
                return { 'Authorization': `Bearer ${cached.token}` };
            }

            // Fetch new token
            const params = new URLSearchParams({
                grant_type: 'client_credentials',
                client_id: auth.clientId,
                client_secret: auth.clientSecret,
            });
            if (auth.scope) {
                params.set('scope', auth.scope);
            }

            const response = await fetch(auth.tokenEndpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: params.toString(),
            });

            if (!response.ok) {
                throw new Error(`OAuth2 token request failed: ${response.status}`);
            }

            const data = await response.json();
            const expiresIn = (data.expires_in ?? 3600) * 1000;
            oauth2TokenCache.set(cacheKey, {
                token: data.access_token,
                expiresAt: Date.now() + expiresIn - 60000, // 1 min buffer
            });

            return { 'Authorization': `Bearer ${data.access_token}` };
        }

        case 'custom':
            return await auth.getHeaders();

        default:
            return {};
    }
}
