import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, loadEnv } from 'vite';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// TASK-2525: standalone Vite + Svelte 5 SPA (NOT SvelteKit). The Admin UI
// is served from the aiohttp backend at /admin (see
// parrot/server/ui/serving.py), hence base: '/admin/'.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '');
  const apiUrl = env.PUBLIC_API_URL || 'http://localhost:5000';

  return {
    base: '/admin/',
    plugins: [tailwindcss(), svelte()],
    resolve: {
      alias: {
        $lib: path.resolve(__dirname, 'src/lib'),
      },
    },
    build: {
      outDir: path.resolve(__dirname, '../src/parrot/server/ui/dist'),
      emptyOutDir: true,
      assetsDir: 'assets',
    },
    server: {
      proxy: {
        '/api': {
          target: apiUrl,
          changeOrigin: true,
        },
      },
    },
  };
});
