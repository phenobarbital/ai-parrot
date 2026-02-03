
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { encrypt } from '$lib/server/crypto';
import { config } from '$lib/config';

const COOKIE_NAME = `${config.storageNamespace}.jwt`;

export const POST: RequestHandler = async ({ request, cookies }) => {
    const { token, expiresAt } = await request.json();

    if (!token) {
        return json({ success: false, message: 'Token required' }, { status: 400 });
    }

    try {
        const encryptedToken = encrypt(token);

        // Calculate maxAge
        const maxAge = Math.max(0, Math.floor(expiresAt - (Date.now() / 1000)));

        cookies.set(COOKIE_NAME, encryptedToken, {
            path: '/',
            httpOnly: true,
            secure: process.env.NODE_ENV === 'production',
            sameSite: 'lax',
            maxAge: maxAge
        });

        return json({ success: true });
    } catch (error) {
        console.error('Failed to encrypt session token', error);
        return json({ success: false, message: 'Encryption failed' }, { status: 500 });
    }
};

export const DELETE: RequestHandler = async ({ cookies }) => {
    cookies.delete(COOKIE_NAME, { path: '/' });
    return json({ success: true });
};
