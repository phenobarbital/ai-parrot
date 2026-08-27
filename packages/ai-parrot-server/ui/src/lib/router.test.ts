import { beforeEach, describe, expect, it } from "vitest";

import { Router } from "./router.svelte";

const LOGIN = "/admin/login";
const DASHBOARD = "/admin/dashboard";

function setPath(path: string) {
  window.history.pushState({}, "", path);
}

describe("Router", () => {
  beforeEach(() => {
    localStorage.clear();
    setPath("/admin");
  });

  it("navigates and updates history", () => {
    const router = new Router([{ path: DASHBOARD, component: async () => ({ default: null }) }]);
    router.navigate(DASHBOARD);
    expect(router.path).toBe(DASHBOARD);
    expect(window.location.pathname).toBe(DASHBOARD);
  });

  it("restores on popstate", () => {
    const router = new Router();
    router.navigate(DASHBOARD);
    setPath("/admin/settings");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(router.path).toBe("/admin/settings");
  });

  it("guard redirects unauthenticated visitors to login with next param", () => {
    const router = new Router([
      { path: DASHBOARD, component: async () => ({ default: null }), requiresAuth: true },
    ]);
    setPath(DASHBOARD);
    router.path = DASHBOARD;

    const allowed = router.guard(DASHBOARD);

    expect(allowed).toBe(false);
    expect(router.path).toBe(`${LOGIN}?next=${encodeURIComponent(DASHBOARD)}`);
  });

  it("allows navigation when a token is present", () => {
    localStorage.setItem("ai_parrot_token", "test-token");
    const router = new Router([
      { path: DASHBOARD, component: async () => ({ default: null }), requiresAuth: true },
    ]);
    router.path = DASHBOARD;

    expect(router.guard(DASHBOARD)).toBe(true);
    expect(router.path).toBe(DASHBOARD);
  });

  it("rejects external next targets, falling back to the base path", () => {
    const router = new Router([
      {
        path: "https://evil.example/phish",
        component: async () => ({ default: null }),
        requiresAuth: true,
      },
    ]);

    router.guard("https://evil.example/phish");

    expect(router.path).toBe(`${LOGIN}?next=${encodeURIComponent("/admin")}`);
  });
});
