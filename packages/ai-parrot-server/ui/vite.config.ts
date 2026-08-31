import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, loadEnv } from 'vite';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// FEAT-476: build-time AgentChat feature flags. Every `PUBLIC_AGENTCHAT_*`
// var defaults to true; only the strings "false"/"0" (case-insensitive)
// disable it. Injected via `define` as `__AGENTCHAT_<NAME>__` compile-time
// booleans so `src/lib/features.ts` + `{#if features.x}` let Rollup drop
// the corresponding chunk when a flag is off (spec §2 "Feature flags").
function agentchatFlag(value: string | undefined): boolean {
  if (value === undefined) return true;
  const normalized = value.trim().toLowerCase();
  return normalized !== 'false' && normalized !== '0';
}

function agentchatDefines(env: Record<string, string>): Record<string, string> {
  const names = [
    'VOICE',
    'AVATAR',
    'MAPS',
    'CHARTS',
    'CANVAS',
    'INFOGRAPHIC',
    'DATASETS',
    'RICH_EDITOR',
  ] as const;
  const defines: Record<string, string> = {};
  for (const name of names) {
    defines[`__AGENTCHAT_${name}__`] = JSON.stringify(
      agentchatFlag(env[`PUBLIC_AGENTCHAT_${name}`]),
    );
  }
  return defines;
}

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
        // FEAT-476: satisfy the vendored navigator tree's SvelteKit import
        // specifiers verbatim (minimal diff vs navigator — spec §2 "Shims").
        '$app/environment': path.resolve(__dirname, 'src/lib/shims/environment.ts'),
        '$app/navigation': path.resolve(__dirname, 'src/lib/shims/navigation.ts'),
        '$env/dynamic/public': path.resolve(__dirname, 'src/lib/shims/env-public.ts'),
      },
    },
    define: agentchatDefines(env),
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
