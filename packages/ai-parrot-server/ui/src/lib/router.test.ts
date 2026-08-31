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

  it("match() ignores a query string so the login redirect's ?next= round-trips", () => {
    const router = new Router([{ path: LOGIN, component: async () => ({ default: null }) }]);

    const matched = router.match(`${LOGIN}?next=${encodeURIComponent(DASHBOARD)}`);

    expect(matched?.path).toBe(LOGIN);
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

  describe(":param routes", () => {
    const AGENTS_NEW = "/admin/agents/new";
    const AGENT_PARAM = "/admin/agents/:name";

    it("matches :param routes and exposes params", () => {
      const router = new Router([
        { path: AGENT_PARAM, component: async () => ({ default: null }) },
      ]);

      const matched = router.match("/admin/agents/helpdesk");

      expect(matched?.path).toBe(AGENT_PARAM);
      expect(router.params).toEqual({ name: "helpdesk" });
    });

    it("prefers a static route over a param route", () => {
      const router = new Router([
        { path: AGENT_PARAM, component: async () => ({ default: null }) },
        { path: AGENTS_NEW, component: async () => ({ default: null }) },
      ]);

      const matched = router.match(AGENTS_NEW);

      expect(matched?.path).toBe(AGENTS_NEW);
      expect(router.params).toEqual({});
    });

    it("does not match a route with a different segment count", () => {
      const router = new Router([
        { path: AGENT_PARAM, component: async () => ({ default: null }) },
      ]);

      expect(router.match("/admin/agents")).toBeUndefined();
      expect(router.match("/admin/agents/helpdesk/extra")).toBeUndefined();
    });

    it("decodes URI-encoded param segments", () => {
      const router = new Router([
        { path: AGENT_PARAM, component: async () => ({ default: null }) },
      ]);

      router.match("/admin/agents/my%20bot");

      expect(router.params).toEqual({ name: "my bot" });
    });
  });

  describe("beforeNavigate", () => {
    it("beforeNavigate returning false cancels navigation", () => {
      const router = new Router([
        { path: DASHBOARD, component: async () => ({ default: null }) },
      ]);
      router.beforeNavigate = () => false;

      router.navigate(DASHBOARD);

      expect(router.path).not.toBe(DASHBOARD);
    });

    it("beforeNavigate returning true allows navigation", () => {
      const router = new Router([
        { path: DASHBOARD, component: async () => ({ default: null }) },
      ]);
      router.beforeNavigate = () => true;

      router.navigate(DASHBOARD);

      expect(router.path).toBe(DASHBOARD);
    });

    it("an async beforeNavigate defers the commit until it resolves true", async () => {
      const router = new Router([
        { path: DASHBOARD, component: async () => ({ default: null }) },
      ]);
      let resolveHook: (value: boolean) => void = () => {};
      router.beforeNavigate = () =>
        new Promise<boolean>((resolve) => {
          resolveHook = resolve;
        });

      router.navigate(DASHBOARD);
      expect(router.path).not.toBe(DASHBOARD);

      resolveHook(true);
      await Promise.resolve();
      await Promise.resolve();

      expect(router.path).toBe(DASHBOARD);
    });

    it("guard redirect bypasses beforeNavigate", () => {
      const router = new Router([
        { path: DASHBOARD, component: async () => ({ default: null }), requiresAuth: true },
      ]);
      router.path = DASHBOARD;
      router.beforeNavigate = () => false;

      const allowed = router.guard(DASHBOARD);

      expect(allowed).toBe(false);
      expect(router.path).toBe(`${LOGIN}?next=${encodeURIComponent(DASHBOARD)}`);
    });
  });
});
