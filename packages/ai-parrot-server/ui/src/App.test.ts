import axios from "axios";
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { beforeEach, expect, test, vi } from "vitest";

import apiClient from "$lib/api/http";
import { router } from "$lib/router.svelte";
import type { AdminStatus } from "$lib/types/generated/AdminStatus";

import App from "./App.svelte";

// TASK-2528: App.svelte now resolves routes (including a lazy component
// import) asynchronously through Router.guard(), so the smoke test must
// await the resolved DOM instead of asserting synchronously — updated
// from TASK-2525's original placeholder-only assertion.
beforeEach(() => {
  localStorage.clear();
  window.history.pushState({}, "", "/admin");
  // Login's onMount discovers auth methods via bare `axios.get` (NOT
  // `apiClient` — see Login.svelte's comment and the dedicated regression
  // test below) — keep it a no-op 200 so the smoke test isn't coupled to
  // network behavior.
  vi.spyOn(axios, "get").mockResolvedValue({ data: {} });
});

test("unauthenticated visit to the app root resolves to the Login page", async () => {
  const { findByText } = render(App);
  // A cold dynamic import() of a .svelte page (Vite's on-demand transform)
  // can take several seconds the first time in a test run — well past
  // testing-library's 1000ms default findBy* timeout.
  expect(await findByText(/parrot/i, {}, { timeout: 10000 })).toBeTruthy();
}, 15000);

// Regression test: Router.match() used to do an EXACT string match
// (including the query string) against the route table's bare paths.
// guard()/AuthStore.handle401() redirect to `${loginPath}?next=<encoded>`,
// which never equals the route table's bare "/admin/login" entry — so
// App.svelte's resolve() treated that redirect as an unmatched route and
// immediately navigated AWAY again (to the fallback path), wiping
// `?next=` before Login.svelte ever mounted to read it via
// `window.location.search`. Fixed in router.svelte.ts's match() by
// stripping the query string before comparing.
test("visiting a guarded route while unauthenticated preserves ?next= through Login and returns there after sign-in", async () => {
  window.history.pushState({}, "", "/admin/dashboard");
  // `router` is a module-level singleton — its `path` was set once at
  // construction time (reading `window.location.pathname` as it was at
  // FIRST import) and is NOT re-derived from a later `pushState()` call.
  // Sync it explicitly, matching the established pattern in
  // Login.test.ts/AppShell.test.ts's beforeEach blocks.
  router.path = "/admin/dashboard";

  const adminStatus: AdminStatus = {
    name: "ai-parrot",
    version: "1.0.0",
    uptime_seconds: 42,
    agents: { database: 0, registry: 0, loaded: 0 },
    crews: 0,
    dependencies: {},
  };
  vi.spyOn(apiClient, "get").mockResolvedValue({ data: adminStatus });
  // Login's discovery call — bare axios.get, not apiClient.get.
  vi.spyOn(axios, "get").mockResolvedValue({ data: {} });
  const postSpy = vi
    .spyOn(apiClient, "post")
    .mockResolvedValue({ data: { token: "tok-1", username: "alice" } });

  const { findByLabelText, getByLabelText, getByRole } = render(App);

  // The guard redirects to login, preserving ?next= for the originally
  // requested (guarded) route.
  await waitFor(
    () => expect(window.location.pathname).toBe("/admin/login"),
    { timeout: 10000 },
  );
  expect(window.location.search).toBe(
    `?next=${encodeURIComponent("/admin/dashboard")}`,
  );
  expect(await findByLabelText("Username", {}, { timeout: 10000 })).toBeTruthy();

  await fireEvent.input(getByLabelText("Username"), { target: { value: "alice" } });
  await fireEvent.input(getByLabelText("Password"), { target: { value: "secret" } });
  await fireEvent.click(getByRole("button", { name: /sign in/i }));

  await waitFor(() => expect(postSpy).toHaveBeenCalled());
  await waitFor(() => expect(window.location.pathname).toBe("/admin/dashboard"));
}, 15000);

// Regression test: Login.svelte's onMount auth-method discovery call used
// to go through the shared `apiClient` (with its 401 interceptor).
// `/api/v1/auth/methods` is NOT in navigator-auth's default exclude list,
// so an unauthenticated visitor always gets a 401 there — which used to
// trip `AuthStore.handle401()`, which reads the CURRENT path (the login
// page, already carrying its own `?next=<intended>` query) and re-wraps it
// into a fresh `?next=`, corrupting the original redirect target before
// the user ever got to submit the form. Fixed by having Login.svelte call
// bare `axios.get` (no interceptor) for discovery instead.
test("a 401 from auth-method discovery on the login page does not corrupt the pending ?next=", async () => {
  window.history.pushState({}, "", "/admin/dashboard");
  router.path = "/admin/dashboard";

  const adminStatus: AdminStatus = {
    name: "ai-parrot",
    version: "1.0.0",
    uptime_seconds: 42,
    agents: { database: 0, registry: 0, loaded: 0 },
    crews: 0,
    dependencies: {},
  };
  vi.spyOn(apiClient, "get").mockResolvedValue({ data: adminStatus });
  // Discovery 401s — the exact failure mode that used to trip the shared
  // interceptor when this call went through `apiClient` instead.
  vi.spyOn(axios, "get").mockRejectedValue({
    response: { status: 401, data: { message: "Unauthorized" }, statusText: "" },
  });
  const postSpy = vi
    .spyOn(apiClient, "post")
    .mockResolvedValue({ data: { token: "tok-1", username: "alice" } });

  const { findByLabelText, getByLabelText, getByRole } = render(App);

  await waitFor(
    () => expect(window.location.pathname).toBe("/admin/login"),
    { timeout: 10000 },
  );
  // The ?next= target must still point at the originally guarded route —
  // not be re-wrapped/lost because discovery's 401 fired handle401().
  await waitFor(() =>
    expect(window.location.search).toBe(
      `?next=${encodeURIComponent("/admin/dashboard")}`,
    ),
  );
  expect(await findByLabelText("Username", {}, { timeout: 10000 })).toBeTruthy();

  await fireEvent.input(getByLabelText("Username"), { target: { value: "alice" } });
  await fireEvent.input(getByLabelText("Password"), { target: { value: "secret" } });
  await fireEvent.click(getByRole("button", { name: /sign in/i }));

  await waitFor(() => expect(postSpy).toHaveBeenCalled());
  await waitFor(() => expect(window.location.pathname).toBe("/admin/dashboard"));
}, 15000);
