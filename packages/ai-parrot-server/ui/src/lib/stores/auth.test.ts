import axios from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import apiClient from "$lib/api/http";

import { AuthStore } from "./auth.svelte";

describe("AuthStore", () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.pushState({}, "", "/admin/dashboard");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("login() posts with X-Auth-Method: BasicAuth and stores ai_parrot_token/ai_parrot_session", async () => {
    const responseData = { token: "abc123", username: "alice", superuser: false };
    const postSpy = vi.spyOn(apiClient, "post").mockResolvedValue({ data: responseData });

    const store = new AuthStore();
    const result = await store.login("alice", "secret");

    expect(result).toEqual({ success: true });
    expect(postSpy).toHaveBeenCalledWith(
      "/api/v1/login",
      { username: "alice", password: "secret" },
      { headers: { "X-Auth-Method": "BasicAuth" } },
    );
    expect(store.token).toBe("abc123");
    expect(store.user).toEqual(responseData);
    expect(localStorage.getItem("ai_parrot_token")).toBe("abc123");
    expect(JSON.parse(localStorage.getItem("ai_parrot_session")!)).toEqual(responseData);
    expect(store.isAuthenticated).toBe(true);
  });

  it("loginWithPasskey() posts with X-Auth-Method: PasskeyAuth via bare axios and stores the same keys", async () => {
    const envelope = { token: "pk-1", username: "alice", auth_method: "passkey", mfa: true };
    const bare = vi.spyOn(axios, "post").mockResolvedValue({ data: envelope });
    const client = vi.spyOn(apiClient, "post");

    const store = new AuthStore();
    const result = await store.loginWithPasskey("chal-1", {
      id: "Y3JlZA",
      rawId: "Y3JlZA",
      type: "public-key",
      clientExtensionResults: {},
      response: {},
    });

    expect(result).toEqual({ success: true });
    expect(client).not.toHaveBeenCalled();
    expect(bare.mock.calls[0][2]).toMatchObject({ headers: { "X-Auth-Method": "PasskeyAuth" } });
    expect(localStorage.getItem("ai_parrot_token")).toBe("pk-1");
    expect(JSON.parse(localStorage.getItem("ai_parrot_session")!)).toEqual(envelope);
    expect(store.authMethod).toBe("passkey");
  });

  it("loginWithPasskey() leaves storage untouched and does not handle a failed ceremony", async () => {
    const existingEnvelope = { token: "existing-token", username: "alice" };
    localStorage.setItem("ai_parrot_token", existingEnvelope.token);
    localStorage.setItem("ai_parrot_session", JSON.stringify(existingEnvelope));
    vi.spyOn(axios, "post").mockRejectedValue({ response: { data: { reason: "Challenge expired" } } });
    const store = new AuthStore();
    const handle401 = vi.spyOn(store, "handle401");

    const result = await store.loginWithPasskey("chal-1", {
      id: "Y3JlZA",
      rawId: "Y3JlZA",
      type: "public-key",
      clientExtensionResults: {},
      response: {},
    });

    expect(result).toEqual({ success: false, error: "Challenge expired" });
    expect(localStorage.getItem("ai_parrot_token")).toBe(existingEnvelope.token);
    expect(JSON.parse(localStorage.getItem("ai_parrot_session")!)).toEqual(existingEnvelope);
    expect(handle401).not.toHaveBeenCalled();
  });

  it("authMethod is null for a BasicAuth envelope without auth_method", async () => {
    vi.spyOn(apiClient, "post").mockResolvedValue({ data: { token: "abc123", username: "alice" } });

    const store = new AuthStore();
    await store.login("alice", "secret");

    expect(store.authMethod).toBeNull();
  });

  it("login() surfaces the server error message on failure", async () => {
    vi.spyOn(apiClient, "post").mockRejectedValue({
      response: { data: { message: "Invalid credentials" } },
    });

    const store = new AuthStore();
    const result = await store.login("alice", "wrong");

    expect(result.success).toBe(false);
    expect(result.error).toBe("Invalid credentials");
    expect(store.token).toBeNull();
    expect(localStorage.getItem("ai_parrot_token")).toBeNull();
  });

  it("logout() calls GET /api/v1/logout and clears storage", async () => {
    localStorage.setItem("ai_parrot_token", "abc123");
    localStorage.setItem("ai_parrot_session", JSON.stringify({ token: "abc123" }));
    const getSpy = vi.spyOn(apiClient, "get").mockResolvedValue({ data: {} });

    const store = new AuthStore();
    store.token = "abc123";
    store.user = { token: "abc123" };

    await store.logout();

    expect(getSpy).toHaveBeenCalledWith("/api/v1/logout");
    expect(store.token).toBeNull();
    expect(store.user).toBeNull();
    expect(localStorage.getItem("ai_parrot_token")).toBeNull();
    expect(localStorage.getItem("ai_parrot_session")).toBeNull();
  });

  it("logout() still clears local storage when the server call fails", async () => {
    localStorage.setItem("ai_parrot_token", "abc123");
    vi.spyOn(apiClient, "get").mockRejectedValue(new Error("network down"));

    const store = new AuthStore();
    store.token = "abc123";

    await store.logout();

    expect(store.token).toBeNull();
    expect(localStorage.getItem("ai_parrot_token")).toBeNull();
  });

  it("handle401() clears storage and routes to login preserving the intended path", async () => {
    localStorage.setItem("ai_parrot_token", "abc123");
    localStorage.setItem("ai_parrot_session", JSON.stringify({ token: "abc123" }));
    window.history.pushState({}, "", "/admin/dashboard");

    const { router } = await import("$lib/router.svelte");
    router.path = "/admin/dashboard";

    const store = new AuthStore();
    store.token = "abc123";

    store.handle401();

    expect(store.token).toBeNull();
    expect(localStorage.getItem("ai_parrot_token")).toBeNull();
    expect(router.path).toBe(
      `/login?next=${encodeURIComponent("/admin/dashboard")}`,
    );
  });
});
