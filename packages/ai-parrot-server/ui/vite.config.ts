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
    // Vite only exposes vars matching `envPrefix` to client code via
    // `import.meta.env` (default: just `VITE_`). `src/lib/config.ts` reads
    // `PUBLIC_API_URL` / `PUBLIC_API_WITH_CREDENTIALS` straight off
    // `import.meta.env` — without this, those documented overrides
    // (docs/admin-ui.md, config.ts's own comments) would silently resolve
    // to `undefined` in the built production bundle even when set at
    // `pnpm build` time, because `loadEnv()` above only feeds the dev-server
    // proxy target, not the client bundle.
    envPrefix: ['VITE_', 'PUBLIC_'],
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
