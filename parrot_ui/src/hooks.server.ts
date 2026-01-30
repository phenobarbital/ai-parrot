// src/hooks.server.ts

/**
 * Server Hooks
 * Resolves client from subdomain/domain and injects into request context
 */

import type { Handle } from '@sveltejs/kit';
import { getClientBySlug } from '$lib/data/mock-data';

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
