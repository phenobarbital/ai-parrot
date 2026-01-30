import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// https://vite.dev/config/
export default defineConfig({
  plugins: [svelte()],
  optimizeDeps: {
    include: [
      "svelte-echarts",
      "echarts",
      "svelte-vega",
      "vega",
      "vega-lite",
      "frappe-charts",
      "@carbon/charts-svelte",
      "layerchart",
      "d3-scale",
      "d3-array",
    ],
  },
})
