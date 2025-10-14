import { browser } from '$app/environment';

/**
 * Theme Store using Svelte 5 Runes
 *
 * Manages daisyUI theme switching with localStorage persistence.
 * Based on: https://scottspence.com/posts/theme-switching-in-sveltekit-updated-for-daisyui-v5-and-tailwind-v4
 */
const STORAGE_KEY = 'theme';
const DEFAULT_THEME = 'light';

const THEMES = [
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
  'halloween',
  'garden',
  'forest',
  'aqua',
  'lofi',
  'pastel',
  'fantasy',
  'wireframe',
  'black',
  'luxury',
  'dracula',
  'cmyk',
  'autumn',
  'business',
  'acid',
  'lemonade',
  'night',
  'coffee',
  'winter',
  'dim',
  'nord',
  'sunset'
];

class ThemeStore {
  currentTheme = $state(DEFAULT_THEME);
  availableThemes = THEMES;

  /**
   * Initialize the theme from localStorage or system preference
   */
  init() {
    if (!browser) return;

    // Try to get theme from localStorage
    const stored = localStorage.getItem(STORAGE_KEY);

    if (stored && THEMES.includes(stored)) {
      this.setTheme(stored);
    } else {
      // Check for system dark mode preference
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      this.setTheme(prefersDark ? 'dark' : DEFAULT_THEME);
    }

    // Listen for system theme changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
      if (!localStorage.getItem(STORAGE_KEY)) {
        this.setTheme(e.matches ? 'dark' : DEFAULT_THEME);
      }
    });
  }

  /**
   * Set the current theme
   * @param {string} theme - Theme name
   */
  setTheme(theme) {
    if (!THEMES.includes(theme)) {
      console.warn(`Theme "${theme}" not found, using default`);
      theme = DEFAULT_THEME;
    }

    this.currentTheme = theme;

    if (browser) {
      // Apply theme to document
      document.documentElement.setAttribute('data-theme', theme);

      // Save to localStorage
      localStorage.setItem(STORAGE_KEY, theme);
    }
  }

  /**
   * Toggle between light and dark themes
   */
  toggleDarkMode() {
    const newTheme = this.currentTheme === 'dark' ? 'light' : 'dark';
    this.setTheme(newTheme);
  }

  /**
   * Get the next theme in the list (for cycling through themes)
   * @returns {string}
   */
  getNextTheme() {
    const currentIndex = THEMES.indexOf(this.currentTheme);
    const nextIndex = (currentIndex + 1) % THEMES.length;
    return THEMES[nextIndex];
  }

  /**
   * Cycle to the next theme
   */
  cycleTheme() {
    const nextTheme = this.getNextTheme();
    this.setTheme(nextTheme);
  }

  /**
   * Check if current theme is dark
   * @returns {boolean}
   */
  isDark() {
    return (
      this.currentTheme === 'dark' ||
      this.currentTheme === 'halloween' ||
      this.currentTheme === 'forest' ||
      this.currentTheme === 'black' ||
      this.currentTheme === 'luxury' ||
      this.currentTheme === 'dracula' ||
      this.currentTheme === 'business' ||
      this.currentTheme === 'night' ||
      this.currentTheme === 'coffee' ||
      this.currentTheme === 'dim' ||
      this.currentTheme === 'sunset'
    );
  }
}

export const themeStore = new ThemeStore();
export { THEMES };
