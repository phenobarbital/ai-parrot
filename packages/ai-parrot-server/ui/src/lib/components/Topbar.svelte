<!--
  Topbar (TASK-2528) — user identity (from the stored session payload),
  theme switcher, logout.
-->
<script lang="ts">
  import { config } from "$lib/config";
  import { router } from "$lib/router.svelte";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import { authStore } from "$lib/stores/auth.svelte";
  import ThemeSwitcher from "./ThemeSwitcher.svelte";

  const identity = $derived.by(() => {
    const user = authStore.user as
      | { username?: string; name?: string; user?: string; email?: string }
      | null;
    return user?.name || user?.username || user?.user || user?.email || "Signed in";
  });

  async function handleLogout() {
    // AuthStore.logout() only clears session state (TASK-2527 contract) —
    // navigating to login is this shell's responsibility, matching
    // AuthStore.handle401()'s redirect-on-expiry behavior.
    await authStore.logout();
    router.navigate(config.loginPath, { replace: true });
  }
</script>

<header class="border-border bg-card flex h-14 items-center justify-between border-b px-4">
  <span class="text-sm font-semibold">AI-Parrot Admin</span>

  <div class="flex items-center gap-3">
    <span class="text-muted-foreground text-sm" data-testid="topbar-identity">{identity}</span>
    <ThemeSwitcher />
    <Button variant="outline" size="sm" onclick={handleLogout}>Sign out</Button>
  </div>
</header>
