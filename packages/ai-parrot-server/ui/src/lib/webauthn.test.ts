import { afterEach, describe, expect, it, vi } from "vitest";

import {
  base64UrlToBuffer,
  bufferToBase64Url,
  credentialToJSON,
  isConditionalMediationAvailable,
  isUserCancelled,
  isWebAuthnSupported,
  toCreationOptions,
  toRequestOptions,
} from "./webauthn";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubSupportedBrowser(publicKeyCredential: object): void {
  vi.stubGlobal("PublicKeyCredential", publicKeyCredential);
  vi.stubGlobal("navigator", { credentials: {} });
}

function bytes(value: string): ArrayBuffer {
  return base64UrlToBuffer(value);
}

describe("webauthn helpers", () => {
  it("round-trips base64url for padded and unpadded lengths", () => {
    for (const value of ["", "Zg", "Zm8", "Zm9v", "Y2hhbGxlbmdl", "_-8"]) {
      expect(bufferToBase64Url(base64UrlToBuffer(value))).toBe(value);
    }
  });

  it("isUserCancelled is true only for NotAllowedError / AbortError", () => {
    expect(isUserCancelled(new DOMException("x", "NotAllowedError"))).toBe(true);
    expect(isUserCancelled(new DOMException("x", "AbortError"))).toBe(true);
    expect(isUserCancelled(new Error("boom"))).toBe(false);
    expect(isUserCancelled(null)).toBe(false);
  });

  it("detects browser WebAuthn support only when both required APIs are present", () => {
    expect(isWebAuthnSupported()).toBe(false);

    stubSupportedBrowser({});

    expect(isWebAuthnSupported()).toBe(true);
  });

  it("reports conditional mediation support without leaking browser errors", async () => {
    expect(await isConditionalMediationAvailable()).toBe(false);

    stubSupportedBrowser({});
    expect(await isConditionalMediationAvailable()).toBe(false);

    stubSupportedBrowser({ isConditionalMediationAvailable: vi.fn().mockResolvedValue(true) });
    expect(await isConditionalMediationAvailable()).toBe(true);

    stubSupportedBrowser({ isConditionalMediationAvailable: vi.fn().mockRejectedValue(new Error("unsupported")) });
    expect(await isConditionalMediationAvailable()).toBe(false);
  });

  it("uses the native request parser when available and decodes request binary fields otherwise", () => {
    const json = {
      challenge: "Y2hhbGxlbmdl",
      allowCredentials: [{ id: "Y3JlZGVudGlhbA", type: "public-key" as const }],
    };
    const nativeOptions = { challenge: bytes("bmF0aXZl") } as PublicKeyCredentialRequestOptions;
    const parseRequestOptionsFromJSON = vi.fn().mockReturnValue(nativeOptions);
    stubSupportedBrowser({ parseRequestOptionsFromJSON });

    expect(toRequestOptions(json)).toBe(nativeOptions);
    expect(parseRequestOptionsFromJSON).toHaveBeenCalledWith(json);

    stubSupportedBrowser({});
    const fallback = toRequestOptions(json);
    expect(bufferToBase64Url(fallback.challenge)).toBe(json.challenge);
    expect(bufferToBase64Url(fallback.allowCredentials![0].id)).toBe(json.allowCredentials[0].id);
  });

  it("uses the native creation parser when available and decodes creation binary fields otherwise", () => {
    const json = {
      rp: { id: "example.test", name: "Example" },
      user: { id: "dXNlcg", name: "alice", displayName: "Alice" },
      challenge: "Y2hhbGxlbmdl",
      pubKeyCredParams: [{ alg: -7, type: "public-key" as const }],
      excludeCredentials: [{ id: "Y3JlZGVudGlhbA", type: "public-key" as const }],
    };
    const nativeOptions = { challenge: bytes("bmF0aXZl") } as PublicKeyCredentialCreationOptions;
    const parseCreationOptionsFromJSON = vi.fn().mockReturnValue(nativeOptions);
    stubSupportedBrowser({ parseCreationOptionsFromJSON });

    expect(toCreationOptions(json)).toBe(nativeOptions);
    expect(parseCreationOptionsFromJSON).toHaveBeenCalledWith(json);

    stubSupportedBrowser({});
    const options = toCreationOptions(json);

    expect(bufferToBase64Url(options.challenge)).toBe(json.challenge);
    expect(bufferToBase64Url(options.user.id)).toBe(json.user.id);
    expect(bufferToBase64Url(options.excludeCredentials![0].id)).toBe(json.excludeCredentials[0].id);
  });

  it("prefers credential toJSON and serializes assertion and attestation fallbacks", () => {
    const native = { id: "native", rawId: "raw", type: "public-key", clientExtensionResults: {}, response: {} };
    expect(credentialToJSON({ toJSON: () => native } as unknown as PublicKeyCredential)).toBe(native);

    const assertion = {
      id: "assertion",
      rawId: bytes("cmF3"),
      type: "public-key",
      authenticatorAttachment: "platform",
      getClientExtensionResults: () => ({ appid: true }),
      response: {
        clientDataJSON: bytes("Y2xpZW50"),
        authenticatorData: bytes("YXV0aA"),
        signature: bytes("c2ln"),
        userHandle: null,
      },
    } as unknown as PublicKeyCredential;
    expect(credentialToJSON(assertion)).toMatchObject({
      id: "assertion",
      rawId: "cmF3",
      authenticatorAttachment: "platform",
      response: { clientDataJSON: "Y2xpZW50", authenticatorData: "YXV0aA", signature: "c2ln", userHandle: undefined },
    });

    const attestation = {
      id: "attestation",
      rawId: bytes("cmF3"),
      type: "public-key",
      getClientExtensionResults: () => ({}),
      response: {
        clientDataJSON: bytes("Y2xpZW50"),
        attestationObject: bytes("YXR0"),
        getTransports: () => ["internal"],
        getAuthenticatorData: () => bytes("YXV0aA"),
        getPublicKey: () => bytes("cHVi"),
        getPublicKeyAlgorithm: () => -7,
      },
    } as unknown as PublicKeyCredential;
    expect(credentialToJSON(attestation).response).toEqual({
      clientDataJSON: "Y2xpZW50",
      attestationObject: "YXR0",
      transports: ["internal"],
      authenticatorData: "YXV0aA",
      publicKey: "cHVi",
      publicKeyAlgorithm: -7,
    });
  });
});
