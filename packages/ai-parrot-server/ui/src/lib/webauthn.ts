/**
 * WebAuthn browser helpers (FEAT-772, spec §3 Module 1).
 *
 * Native WebAuthn Level-3 JSON helpers are used when the browser has them;
 * otherwise a hand-written base64url fallback is used. Native support is
 * detected at call time so callers and tests can select either path.
 */

type PublicKeyCredentialDescriptorJSON = Omit<PublicKeyCredentialDescriptor, "id"> & {
  id: string;
};

/** JSON-safe version of the request options accepted by the backend. */
export type PublicKeyCredentialRequestOptionsJSON = Omit<
  PublicKeyCredentialRequestOptions,
  "challenge" | "allowCredentials"
> & {
  challenge: string;
  allowCredentials?: PublicKeyCredentialDescriptorJSON[];
};

/** JSON-safe version of the creation options accepted by the backend. */
export type PublicKeyCredentialCreationOptionsJSON = Omit<
  PublicKeyCredentialCreationOptions,
  "challenge" | "user" | "excludeCredentials"
> & {
  challenge: string;
  user: Omit<PublicKeyCredentialUserEntity, "id"> & { id: string };
  excludeCredentials?: PublicKeyCredentialDescriptorJSON[];
};

/** Wire shape sent to the backend (`credential` in login and register/verify bodies). */
export type PublicKeyCredentialJSON = {
  id: string;
  rawId: string;
  type: string;
  authenticatorAttachment?: string;
  clientExtensionResults: Record<string, unknown>;
  response: Record<string, unknown>;
};

type PublicKeyCredentialJSONHelpers = {
  isConditionalMediationAvailable?: () => Promise<boolean>;
  parseRequestOptionsFromJSON?: (
    options: PublicKeyCredentialRequestOptionsJSON,
  ) => PublicKeyCredentialRequestOptions;
  parseCreationOptionsFromJSON?: (
    options: PublicKeyCredentialCreationOptionsJSON,
  ) => PublicKeyCredentialCreationOptions;
};

type CredentialWithJSON = PublicKeyCredential & {
  toJSON?: () => PublicKeyCredentialJSON;
};

/** True when `window.PublicKeyCredential` and `navigator.credentials` exist. */
export function isWebAuthnSupported(): boolean {
  return typeof window !== "undefined" && "PublicKeyCredential" in window && !!navigator.credentials;
}

/** Resolves native conditional-mediation support, returning false when unavailable. */
export async function isConditionalMediationAvailable(): Promise<boolean> {
  if (!isWebAuthnSupported()) {
    return false;
  }

  const helpers = PublicKeyCredential as unknown as PublicKeyCredentialJSONHelpers;
  if (typeof helpers.isConditionalMediationAvailable !== "function") {
    return false;
  }

  try {
    return await helpers.isConditionalMediationAvailable();
  } catch {
    return false;
  }
}

/** Decodes an unpadded base64url string into browser WebAuthn binary data. */
export function base64UrlToBuffer(value: string): ArrayBuffer {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  const decoded = atob(padded);
  const bytes = new Uint8Array(decoded.length);

  for (let index = 0; index < decoded.length; index += 1) {
    bytes[index] = decoded.charCodeAt(index);
  }

  return bytes.buffer;
}

/** Encodes browser WebAuthn binary data as an unpadded base64url string. */
export function bufferToBase64Url(buffer: ArrayBuffer): string {
  const binary = String.fromCharCode(...new Uint8Array(buffer));
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Uses the native request converter when available, otherwise decodes binary fields. */
export function toRequestOptions(json: PublicKeyCredentialRequestOptionsJSON): PublicKeyCredentialRequestOptions {
  const helpers =
    typeof PublicKeyCredential === "undefined"
      ? undefined
      : (PublicKeyCredential as unknown as PublicKeyCredentialJSONHelpers);
  if (typeof helpers?.parseRequestOptionsFromJSON === "function") {
    return helpers.parseRequestOptionsFromJSON(json);
  }

  return {
    ...json,
    challenge: base64UrlToBuffer(json.challenge),
    allowCredentials: json.allowCredentials?.map((credential) => ({
      ...credential,
      id: base64UrlToBuffer(credential.id),
    })),
  };
}

/** Uses the native creation converter when available, otherwise decodes binary fields. */
export function toCreationOptions(json: PublicKeyCredentialCreationOptionsJSON): PublicKeyCredentialCreationOptions {
  const helpers =
    typeof PublicKeyCredential === "undefined"
      ? undefined
      : (PublicKeyCredential as unknown as PublicKeyCredentialJSONHelpers);
  if (typeof helpers?.parseCreationOptionsFromJSON === "function") {
    return helpers.parseCreationOptionsFromJSON(json);
  }

  return {
    ...json,
    challenge: base64UrlToBuffer(json.challenge),
    user: {
      ...json.user,
      id: base64UrlToBuffer(json.user.id),
    },
    excludeCredentials: json.excludeCredentials?.map((credential) => ({
      ...credential,
      id: base64UrlToBuffer(credential.id),
    })),
  };
}

/** Serializes assertion and attestation credentials when native `toJSON` is unavailable. */
export function credentialToJSON(cred: PublicKeyCredential): PublicKeyCredentialJSON {
  const credential = cred as CredentialWithJSON;
  if (typeof credential.toJSON === "function") {
    return credential.toJSON();
  }

  const response = cred.response;
  const common = {
    id: cred.id,
    rawId: bufferToBase64Url(cred.rawId),
    type: cred.type,
    authenticatorAttachment: cred.authenticatorAttachment ?? undefined,
    clientExtensionResults: cred.getClientExtensionResults(),
  };

  if ("attestationObject" in response) {
    const attestation = response as AuthenticatorAttestationResponse;
    const responseJSON: Record<string, unknown> = {
      clientDataJSON: bufferToBase64Url(attestation.clientDataJSON),
      attestationObject: bufferToBase64Url(attestation.attestationObject),
    };
    const transports = attestation.getTransports?.();

    if (transports) {
      responseJSON.transports = transports;
    }
    if (attestation.getAuthenticatorData) {
      responseJSON.authenticatorData = bufferToBase64Url(attestation.getAuthenticatorData());
    }
    if (attestation.getPublicKey) {
      const publicKey = attestation.getPublicKey();
      if (publicKey) {
        responseJSON.publicKey = bufferToBase64Url(publicKey);
      }
    }
    if (attestation.getPublicKeyAlgorithm) {
      responseJSON.publicKeyAlgorithm = attestation.getPublicKeyAlgorithm();
    }

    return { ...common, response: responseJSON };
  }

  const assertion = response as AuthenticatorAssertionResponse;
  return {
    ...common,
    response: {
      clientDataJSON: bufferToBase64Url(assertion.clientDataJSON),
      authenticatorData: bufferToBase64Url(assertion.authenticatorData),
      signature: bufferToBase64Url(assertion.signature),
      userHandle: assertion.userHandle ? bufferToBase64Url(assertion.userHandle) : undefined,
    },
  };
}

/** True for a dismissed prompt or a superseded request — callers show nothing. */
export function isUserCancelled(err: unknown): boolean {
  const name = (err as { name?: unknown } | null)?.name;
  return name === "NotAllowedError" || name === "AbortError";
}
