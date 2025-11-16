import { writable } from 'svelte/store';

export const THEMES = [
  'light',
  'dark',
  'cupcake',
  'bumblebee',
  'emerald',
  'corporate',
  'synthwave',
  'retro',
  'cyberpunk',
  'valentine',
  'garden',
  'aqua',
  'lofi',
  'pastel',
  'fantasy',
  'wireframe',
  'black',
  'luxury',
  'dracula'
];

const defaultTheme = 'light';

function createThemeStore() {
  const { subscribe, update, set } = writable({ currentTheme: defaultTheme });

  function applyTheme(theme) {
    if (typeof document === 'undefined') return;
    document.documentElement.setAttribute('data-theme', theme);
  }

  return {
    subscribe,
    init: () => {
      if (typeof window === 'undefined') return;
      const stored = localStorage.getItem('agentui.theme') || defaultTheme;
      set({ currentTheme: stored });
      applyTheme(stored);
    },
    setTheme: (theme) => {
      update(() => ({ currentTheme: theme }));
      if (typeof window !== 'undefined') {
        localStorage.setItem('agentui.theme', theme);
      }
      applyTheme(theme);
    },
    toggleDarkMode: () => {
      let next = 'dark';
      update((state) => {
        next = state.currentTheme === 'dark' ? defaultTheme : 'dark';
        return { currentTheme: next };
      });
      if (typeof window !== 'undefined') {
        localStorage.setItem('agentui.theme', next);
      }
      applyTheme(next);
    }
  };
}

export const themeStore = createThemeStore();
