<!--
  ThemeSwitcher (TASK-2528) — light/dark toggle.

  Adapted (heavily trimmed) from navigator-frontend-next's
  src/components/ThemeSwitcher.svelte: the source is a 4-entry dropdown
  built on `@iconify/svelte` + a corporate `AppDropdown`/`AppDropdownItem`
  wrapper, neither of which was vendored by TASK-2525. This scaffold only
  has "light"/"dark" (see stores/theme.svelte.ts), so a single toggle
  button covers the same behavior without either dependency.
-->
<script lang="ts">
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import { themeStore } from "$lib/stores/theme.svelte";

  let isDark = $derived(themeStore.isDark);
</script>

<Button
  variant="ghost"
  size="icon-sm"
  onclick={() => themeStore.toggleDarkMode()}
  aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
  title={isDark ? "Switch to light theme" : "Switch to dark theme"}
>
  {isDark ? "🌙" : "☀️"}
</Button>
