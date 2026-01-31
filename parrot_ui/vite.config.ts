import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), '');
    const port = env.PORT ? parseInt(env.PORT) : 5174;
    const allowedHosts = env.ALLOWED_HOSTS ? env.ALLOWED_HOSTS.split(',') : [];

    return {
        plugins: [
            tailwindcss(),
            sveltekit()
        ],
        ssr: {
            noExternal: ['flowbite-svelte', 'flowbite-svelte-icons', 'gridjs-svelte']
        },
        server: {
            port,
            ...(allowedHosts.length > 0 ? { allowedHosts } : {}),
            strictPort: false
        }
    };
});
