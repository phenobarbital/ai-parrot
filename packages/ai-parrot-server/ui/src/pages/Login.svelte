<!--
  Login page (TASK-2528) — route /admin/login.

  Structurally adapted from navigator-frontend-next's
  src/lib/navauth/components/LoginForm.svelte + src/routes/login/+page.svelte
  (username/password/showPassword/loading/error $state shape) — rewritten
  against our own vendored shadcn primitives (Button/Card/Input/Label)
  instead of the source's DaisyUI classes, since DaisyUI was not vendored
  by TASK-2525.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import axios from "axios";

  import { config } from "$lib/config";
  import ProviderButtons, { type AuthMethodInfo } from "$lib/components/ProviderButtons.svelte";
  import { isInAppPath, router } from "$lib/router.svelte";
  import { authStore } from "$lib/stores/auth.svelte";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import { Card, CardContent, CardHeader, CardTitle } from "$lib/ui/internal/shadcn/ui/card/index.js";
  import { Input } from "$lib/ui/internal/shadcn/ui/input/index.js";
  import { Label } from "$lib/ui/internal/shadcn/ui/label/index.js";

  let username = $state("");
  let password = $state("");
  let showPassword = $state(false);
  let loading = $state(false);
  let error = $state("");
  let methods = $state<Record<string, AuthMethodInfo> | null>(null);

  function nextTarget(): string {
    const params = new URLSearchParams(window.location.search);
    const next = params.get("next");
    return next && isInAppPath(next) ? next : "/admin/home";
  }

  onMount(async () => {
    // Discovery failure must never block the BasicAuth form — swallow and
    // just render the form alone.
    //
    // Deliberately bypasses `apiClient` (which carries the shared 401
    // interceptor): `/api/v1/auth/methods` is NOT in navigator-auth's
    // default exclude list (only /static/, /api/v1/login, /api/v1/logout,
    // /api/v1/forgot-password, /api/v1/reset-password are), so an
    // unauthenticated visitor landing on this page always gets a 401 here.
    // Routing that through `apiClient` would trigger
    // `AuthStore.handle401()`, which reads the CURRENT path (this login
    // page, including its own `?next=<intended>` query) and re-wraps it
    // into a fresh `?next=`, corrupting/losing the original redirect
    // target before the user ever submits the form. A bare axios call has
    // no interceptor to trip, so a 401 here just falls through to the
    // catch below like any other discovery failure.
    try {
      const { data } = await axios.get(`${config.apiBaseUrl}${config.authMethodsUrl}`, {
        withCredentials: config.apiWithCredentials,
      });
      methods = data;
    } catch {
      methods = null;
    }
  });

  async function handleSubmit(event: Event) {
    event.preventDefault();
    error = "";
    loading = true;

    const result = await authStore.login(username, password);
    loading = false;

    if (result.success) {
      router.navigate(nextTarget(), { replace: true });
    } else {
      error = result.error || "Login failed";
    }
  }
</script>

<main class="bg-background text-foreground flex min-h-screen items-center justify-center p-4">
  <Card class="w-full max-w-sm">
    <CardHeader>
      <CardTitle class="text-xl">Sign in to AI-Parrot Admin</CardTitle>
    </CardHeader>
    <CardContent class="flex flex-col gap-4">
      {#if error}
        <div
          class="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          role="alert"
        >
          {error}
        </div>
      {/if}

      <form class="flex flex-col gap-4" onsubmit={handleSubmit}>
        <div class="flex flex-col gap-1.5">
          <Label for="username">Username</Label>
          <Input
            id="username"
            type="text"
            bind:value={username}
            disabled={loading}
            required
            autocomplete="username"
          />
        </div>

        <div class="flex flex-col gap-1.5">
          <Label for="password">Password</Label>
          <div class="relative">
            <Input
              id="password"
              type={showPassword ? "text" : "password"}
              bind:value={password}
              disabled={loading}
              required
              autocomplete="current-password"
              class="pr-16"
            />
            <button
              type="button"
              class="text-muted-foreground hover:text-foreground absolute top-1/2 right-2 -translate-y-1/2 text-xs"
              onclick={() => (showPassword = !showPassword)}
              tabindex="-1"
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </div>
        </div>

        <Button type="submit" disabled={loading} class="w-full">
          {loading ? "Signing in…" : "Sign In"}
        </Button>
      </form>

      <ProviderButtons {methods} />
    </CardContent>
  </Card>
</main>
