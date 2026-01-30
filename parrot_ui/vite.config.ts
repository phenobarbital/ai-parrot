import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), '');

    return {
        plugins: [
            tailwindcss(),
            sveltekit()
        ],
        ssr: {
            noExternal: ['flowbite-svelte', 'flowbite-svelte-icons']
        },
        server: {
            port: 5174,
            strictPort: false
        }
    };
});
