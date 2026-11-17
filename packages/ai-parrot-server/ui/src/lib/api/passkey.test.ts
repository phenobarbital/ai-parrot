import axios from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

import apiClient, { ApiError } from "$lib/api/http";

import {
  deletePasskey,
  fetchLoginOptions,
  fetchRegisterOptions,
  listPasskeys,
  passkeyErrorMessage,
  postPasskeyLogin,
  renamePasskey,
  verifyRegistration,
} from "./passkey";

const credential = {
  id: "x",
  rawId: "x",
  type: "public-key",
  clientExtensionResults: {},
  response: {},
};

afterEach(() => vi.restoreAllMocks());

describe("passkey api", () => {
  it("fetchLoginOptions uses bare axios, never apiClient, and sends {} without a username", async () => {
    const options = { challenge_id: "c1", publicKey: { challenge: "Y2g", allowCredentials: [] } };
    const bare = vi.spyOn(axios, "post").mockResolvedValue({ data: options });
    const client = vi.spyOn(apiClient, "post");

    expect(await fetchLoginOptions()).toEqual(options);
    expect(bare).toHaveBeenCalledWith("/api/v1/auth/passkey/login/options", {}, expect.any(Object));
    expect(client).not.toHaveBeenCalled();
  });

  it("fetchLoginOptions sends a supplied username and returns null for failures or malformed data", async () => {
    const bare = vi.spyOn(axios, "post").mockResolvedValueOnce({ data: { challenge_id: "c1", publicKey: {} } });

    await fetchLoginOptions("alice");
    expect(bare).toHaveBeenCalledWith(
      "/api/v1/auth/passkey/login/options",
      { username: "alice" },
      expect.any(Object),
    );

    bare.mockResolvedValueOnce({ data: { challenge_id: "c1" } });
    expect(await fetchLoginOptions()).toBeNull();
    bare.mockRejectedValueOnce({ response: { status: 404 } });
    expect(await fetchLoginOptions()).toBeNull();
  });

  it("postPasskeyLogin uses bare axios with the PasskeyAuth header", async () => {
    const bare = vi.spyOn(axios, "post").mockResolvedValue({ data: { token: "t" } });
    const client = vi.spyOn(apiClient, "post");

    await expect(postPasskeyLogin({ challenge_id: "c1", credential })).resolves.toEqual({ token: "t" });
    expect(bare).toHaveBeenCalledWith(
      "/api/v1/login",
      expect.objectContaining({ challenge_id: "c1" }),
      expect.objectContaining({ headers: { "X-Auth-Method": "PasskeyAuth" } }),
    );
    expect(client).not.toHaveBeenCalled();
  });

  it("uses apiClient for authenticated registration and credential calls", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { status: "registered", id: "x" } });
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: [] });
    const patch = vi.spyOn(apiClient, "patch").mockResolvedValue({});
    const noContent = {};
    Object.defineProperty(noContent, "data", {
      get: () => {
        throw new Error("DELETE 204 body must not be read");
      },
    });
    const del = vi.spyOn(apiClient, "delete").mockResolvedValue(noContent);

    await fetchRegisterOptions();
    await verifyRegistration(credential, "  Laptop  ");
    await verifyRegistration(credential, "   ");
    expect(await listPasskeys()).toEqual([]);
    await renamePasskey("credential/id", "  Phone  ");
    await deletePasskey("credential/id");

    expect(post).toHaveBeenNthCalledWith(1, "/api/v1/auth/passkey/register/options", {});
    expect(post).toHaveBeenNthCalledWith(2, "/api/v1/auth/passkey/register/verify", {
      credential,
      label: "Laptop",
    });
    expect(post).toHaveBeenNthCalledWith(3, "/api/v1/auth/passkey/register/verify", { credential });
    expect(get).toHaveBeenCalledWith("/api/v1/auth/passkey/credentials");
    expect(patch).toHaveBeenCalledWith("/api/v1/auth/passkey/credentials/credential%2Fid", { label: "Phone" });
    expect(del).toHaveBeenCalledWith("/api/v1/auth/passkey/credentials/credential%2Fid");
  });

  it("rejects invalid labels before calling apiClient", async () => {
    const patch = vi.spyOn(apiClient, "patch");

    await expect(renamePasskey("id", "   ")).rejects.toThrow("between 1 and 128");
    await expect(renamePasskey("id", "x".repeat(129))).rejects.toThrow("between 1 and 128");
    expect(patch).not.toHaveBeenCalled();
  });

  it("maps navigator-auth reasons before normal server messages and Error fallbacks", () => {
    const apiError = new ApiError("Unauthorized", "auth", 401, {
      response: { status: 401, data: { reason: "Passkey challenge expired" } },
    });
    expect(passkeyErrorMessage(apiError)).toBe("Passkey challenge expired");
    expect(passkeyErrorMessage({ response: { status: 400, data: { reason: "Invalid origin" } } })).toBe(
      "Invalid origin",
    );
    expect(passkeyErrorMessage({ response: { status: 409, data: { detail: "Already registered" } } })).toBe(
      "Already registered",
    );
    expect(passkeyErrorMessage(new Error("network down"))).toBe("network down");
  });
});
