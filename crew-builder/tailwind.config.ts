import type { Config } from 'tailwindcss';
import daisyui from 'daisyui';

export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {}
  },
  plugins: [daisyui],
  daisyui: {
    themes: ['light', 'dark', 'cupcake', 'business']
  }
} satisfies Config;
