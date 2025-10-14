import { browser } from '$app/environment';
import { writable } from 'svelte/store';

const DEFAULT_THEME = 'light';

function createThemeStore() {
  const { subscribe, set, update } = writable(DEFAULT_THEME, (set) => {
    if (browser) {
      const stored = localStorage.getItem('theme');
      const initial = stored ?? DEFAULT_THEME;
      set(initial);
      applyTheme(initial);
    }

    return () => undefined;
  });

  function applyTheme(value: string) {
    if (!browser) return;
    document.documentElement.setAttribute('data-theme', value);
    localStorage.setItem('theme', value);
  }

  return {
    subscribe,
    set: (value: string) => {
      set(value);
      applyTheme(value);
    },
    toggle: () => {
      update((current) => {
        const next = current === 'dark' ? 'light' : 'dark';
        applyTheme(next);
        return next;
      });
    }
  };
}

export const theme = createThemeStore();
