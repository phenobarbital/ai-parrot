import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, loadEnv } from 'vite';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export default defineConfig(({ mode }) => {
    const envDir = path.resolve(__dirname, '../env');
    const env = loadEnv(mode, envDir, '');
    const port = env.PORT ? parseInt(env.PORT) : 5174;
    const allowedHosts = env.ALLOWED_HOSTS
        ? env.ALLOWED_HOSTS.split(',').map((s) => s.trim()).filter(Boolean)
        : [];

    return {
        envDir,
        plugins: [
            tailwindcss(),
            sveltekit()
        ],
        ssr: {
            noExternal: ['flowbite-svelte-icons', 'gridjs-svelte']
        },
        server: {
            port,
            ...(allowedHosts.length > 0 ? { allowedHosts } : {}),
            strictPort: false
        }
    };
});
