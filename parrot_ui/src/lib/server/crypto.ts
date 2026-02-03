import crypto from 'node:crypto';
import { privateEnv } from '$lib/env/private';

// Use a consistent key for encryption. In production, this MUST be set in environment variables.
// Fallback is only for development convenience.
const ENCRYPTION_KEY = privateEnv.SESSION_SECRET || 'dev-secret-key-must-be-32-bytes-long!';
const IV_LENGTH = 16; // For AES, this is always 16

// Ensure the key is exactly 32 bytes (256 bits)
const key = crypto.createHash('sha256').update(String(ENCRYPTION_KEY)).digest('base64').substring(0, 32);

export function encrypt(text: string): string {
    const iv = crypto.randomBytes(IV_LENGTH);
    const cipher = crypto.createCipheriv('aes-256-cbc', Buffer.from(key), iv);
    let encrypted = cipher.update(text);
    encrypted = Buffer.concat([encrypted, cipher.final()]);
    return iv.toString('hex') + ':' + encrypted.toString('hex');
}

export function decrypt(text: string): string | null {
    try {
        const textParts = text.split(':');
        const ivPart = textParts.shift();
        if (!ivPart || ivPart.length !== 32) return null;

        const iv = Buffer.from(ivPart, 'hex');
        if (iv.length !== 16) return null;

        const encryptedText = Buffer.from(textParts.join(':'), 'hex');
        const decipher = crypto.createDecipheriv('aes-256-cbc', Buffer.from(key), iv);
        let decrypted = decipher.update(encryptedText);
        decrypted = Buffer.concat([decrypted, decipher.final()]);
        return decrypted.toString();
    } catch (error) {
        console.error('Decryption failed:', error);
        return null;
    }
}
