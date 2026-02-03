// src/hooks.server.ts

/**
 * Server Hooks
 * Resolves client from subdomain/domain and injects into request context
 */

import type { Handle } from '@sveltejs/kit';
import { getClientBySlug } from '$lib/data/manual-data';
import { config } from '$lib/config';
import { decrypt } from '$lib/server/crypto';

/**
 * Parse subdomain from host
 * Examples:
 * - epson.trocdigital.io -> epson
 * - localhost:5174 -> localhost
 * - trocdigital.io -> trocdigital
 */
function parseClientSlug(host: string): string {
    // Remove port number
    const hostname = host.split(':')[0];

    // Handle localhost
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
        return 'localhost';
    }

    // Check for subdomain pattern (e.g., epson.trocdigital.io)
    const parts = hostname.split('.');
    if (parts.length >= 3) {
        // Has subdomain - return first part
        return parts[0];
    }

    // No subdomain - use domain name (e.g., trocdigital from trocdigital.io)
    if (parts.length >= 2) {
        return parts[0];
    }

    return hostname;
}

export const handle: Handle = async ({ event, resolve }) => {
    const host = event.request.headers.get('host') || 'localhost';
    const clientSlug = parseClientSlug(host);

    // Load client configuration
    const client = getClientBySlug(clientSlug) || null;

    // Inject into locals for access in load functions
    event.locals.client = client;
    event.locals.clientSlug = clientSlug;

    // Try to get token from cookie
    const encryptedToken = event.cookies.get(`${config.storageNamespace}.jwt`);
    if (encryptedToken) {
        try {
            const token = decrypt(encryptedToken);
            if (token) {
                event.locals.token = token;
                // Simple JWT decode (payload is 2nd part)
                const payload = token.split('.')[1];
                if (payload) {
                    const decoded = JSON.parse(Buffer.from(payload, 'base64').toString('utf-8'));
                    // Map to UserInfo (adjust based on your JWT structure)
                    event.locals.user = {
                        id: decoded.user_id || decoded.sub,
                        username: decoded.username || decoded.preferred_username,
                        email: decoded.email,
                        displayName: decoded.name || `${decoded.first_name} ${decoded.last_name}`,
                        firstName: decoded.first_name,
                        lastName: decoded.last_name,
                        isSuperuser: decoded.superuser,
                        groups: decoded.groups || [],
                        groupIds: decoded.group_id || [],
                        programs: decoded.programs || [],
                        domain: decoded.domain
                    };
                    console.log('[Server Auth] Token received for user:', event.locals.user.username);
                }
            }
        } catch (e) {
            console.error('Failed to parse JWT token server-side', e);
        }
    }

    // Resolve with dark mode class support
    const response = await resolve(event, {
        transformPageChunk: ({ html }) => {
            // Default to light mode (no class)
            // Only add dark class if explicitly stored/requested in a way we want to persist (optional)
            return html;
        }
    });

    return response;
};
