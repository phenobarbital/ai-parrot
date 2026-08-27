import { svelte } from '@sveltejs/vite-plugin-svelte';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export default defineConfig({
  plugins: [svelte({ hot: false })],
  resolve: {
    alias: {
      $lib: path.resolve(__dirname, 'src/lib'),
    },
    conditions: ['browser'],
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest-setup.ts'],
  },
});
