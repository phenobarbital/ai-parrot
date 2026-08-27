import { render } from "@testing-library/svelte";
import { beforeEach, expect, test, vi } from "vitest";

import apiClient from "$lib/api/http";

import App from "./App.svelte";

// TASK-2528: App.svelte now resolves routes (including a lazy component
// import) asynchronously through Router.guard(), so the smoke test must
// await the resolved DOM instead of asserting synchronously — updated
// from TASK-2525's original placeholder-only assertion.
beforeEach(() => {
  localStorage.clear();
  window.history.pushState({}, "", "/admin");
  // Login's onMount discovers auth methods — keep it a no-op 200 so the
  // smoke test isn't coupled to network behavior.
  vi.spyOn(apiClient, "get").mockResolvedValue({ data: {} });
});

test("unauthenticated visit to the app root resolves to the Login page", async () => {
  const { findByText } = render(App);
  // A cold dynamic import() of a .svelte page (Vite's on-demand transform)
  // can take several seconds the first time in a test run — well past
  // testing-library's 1000ms default findBy* timeout.
  expect(await findByText(/parrot/i, {}, { timeout: 10000 })).toBeTruthy();
}, 15000);
