import { svelte } from '@sveltejs/vite-plugin-svelte';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// FEAT-476: mirror vite.config.ts's __AGENTCHAT_*__ defines so vitest can
// import gated modules; all default true (see vite.config.ts for the
// PUBLIC_AGENTCHAT_* -> boolean parsing this test build assumes).
const AGENTCHAT_DEFINES = {
  __AGENTCHAT_VOICE__: 'true',
  __AGENTCHAT_AVATAR__: 'true',
  __AGENTCHAT_MAPS__: 'true',
  __AGENTCHAT_CHARTS__: 'true',
  __AGENTCHAT_CANVAS__: 'true',
  __AGENTCHAT_INFOGRAPHIC__: 'true',
  __AGENTCHAT_DATASETS__: 'true',
  __AGENTCHAT_RICH_EDITOR__: 'true',
};

export default defineConfig({
  plugins: [svelte({ hot: false })],
  resolve: {
    alias: {
      $lib: path.resolve(__dirname, 'src/lib'),
      // FEAT-476: same SvelteKit shims as vite.config.ts (spec §2 "Shims").
      '$app/environment': path.resolve(__dirname, 'src/lib/shims/environment.ts'),
      '$app/navigation': path.resolve(__dirname, 'src/lib/shims/navigation.ts'),
      '$env/dynamic/public': path.resolve(__dirname, 'src/lib/shims/env-public.ts'),
    },
    conditions: ['browser'],
  },
  define: AGENTCHAT_DEFINES,
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest-setup.ts'],
  },
});
