import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as passkeyApi from "$lib/api/passkey";
import { authStore } from "$lib/stores/auth.svelte";

import PasskeySignIn from "./PasskeySignIn.svelte";

const OPTIONS = {
  challenge_id: "chal-1",
  publicKey: {
    challenge: "Y2hhbGxlbmdl",
    rpId: "localhost",
    allowCredentials: [],
    userVerification: "required",
  },
};

type CredentialsGet = (options?: CredentialRequestOptions) => Promise<Credential | null>;
const originalCredentials = Object.getOwnPropertyDescriptor(navigator, "credentials");

function stubWebAuthn({
  conditional = false,
  get = vi.fn<CredentialsGet>(),
}: {
  conditional?: boolean;
  get?: ReturnType<typeof vi.fn<CredentialsGet>>;
} = {}) {
  vi.stubGlobal(
    "PublicKeyCredential",
    Object.assign(function () {}, {
      isConditionalMediationAvailable: () => Promise.resolve(conditional),
    }),
  );
  Object.defineProperty(navigator, "credentials", { configurable: true, value: { get } });
  return get;
}

function credential(): PublicKeyCredential {
  return {
    toJSON: () => ({ id: "cred-1", rawId: "Y3JlZC0x", type: "public-key", response: {} }),
  } as unknown as PublicKeyCredential;
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  if (originalCredentials) {
    Object.defineProperty(navigator, "credentials", originalCredentials);
  } else {
    delete (navigator as { credentials?: CredentialsContainer }).credentials;
  }
});

describe("PasskeySignIn", () => {
  it("renders nothing when WebAuthn is unsupported", () => {
    const probe = vi.spyOn(passkeyApi, "fetchLoginOptions");
    const { queryByTestId } = render(PasskeySignIn, { username: "", onSuccess: vi.fn() });
    expect(queryByTestId("passkey-signin")).toBeNull();
    expect(probe).not.toHaveBeenCalled();
  });

  it("renders nothing when the probe fails", async () => {
    stubWebAuthn();
    vi.spyOn(passkeyApi, "fetchLoginOptions").mockResolvedValue(null);
    const { queryByTestId } = render(PasskeySignIn, { username: "", onSuccess: vi.fn() });
    await waitFor(() => expect(passkeyApi.fetchLoginOptions).toHaveBeenCalledTimes(1));
    expect(queryByTestId("passkey-signin")).toBeNull();
  });

  it("arms conditional UI once with the mount-time challenge", async () => {
    let abortObserved = false;
    const get = stubWebAuthn({
      conditional: true,
      get: vi.fn((options?: CredentialRequestOptions) =>
        new Promise<Credential | null>((_, reject) => {
          options?.signal?.addEventListener("abort", () => {
            abortObserved = true;
            reject(new DOMException("cancelled", "AbortError"));
          });
        }),
      ),
    });
    vi.spyOn(passkeyApi, "fetchLoginOptions").mockResolvedValue(OPTIONS);

    const view = render(PasskeySignIn, { username: "", onSuccess: vi.fn() });

    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    expect(passkeyApi.fetchLoginOptions).toHaveBeenCalledTimes(1);
    const request = get.mock.calls[0][0] as CredentialRequestOptions & { mediation?: string };
    expect(request.mediation).toBe("conditional");
    expect(request.publicKey?.challenge).toBeInstanceOf(ArrayBuffer);

    view.unmount();
    await waitFor(() => expect(abortObserved).toBe(true));
  });

  it("aborts conditional UI, fetches a username-scoped challenge, and signs in", async () => {
    let conditionalAborted = false;
    const get = stubWebAuthn({
      conditional: true,
      get: vi.fn((options?: CredentialRequestOptions) => {
        if ((options as { mediation?: string })?.mediation === "conditional") {
          return new Promise<Credential | null>((_, reject) => {
            options?.signal?.addEventListener("abort", () => {
              conditionalAborted = true;
              reject(new DOMException("superseded", "AbortError"));
            });
          });
        }
        return Promise.resolve(credential());
      }),
    });
    const fetchOptions = vi
      .spyOn(passkeyApi, "fetchLoginOptions")
      .mockResolvedValueOnce(OPTIONS)
      .mockResolvedValueOnce({ ...OPTIONS, challenge_id: "chal-2" });
    const login = vi.spyOn(authStore, "loginWithPasskey").mockResolvedValue({ success: true });
    const onSuccess = vi.fn();
    const { getByTestId } = render(PasskeySignIn, { username: " alice ", onSuccess });

    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    await fireEvent.click(getByTestId("passkey-signin"));

    await waitFor(() => expect(conditionalAborted).toBe(true));
    expect(fetchOptions).toHaveBeenNthCalledWith(1);
    expect(fetchOptions).toHaveBeenNthCalledWith(2, "alice");
    await waitFor(() => expect(login).toHaveBeenCalledWith("chal-2", expect.any(Object)));
    expect(onSuccess).toHaveBeenCalledOnce();
  });

  it("keeps cancellation silent and shows the generic failure message", async () => {
    const get = stubWebAuthn({ conditional: false, get: vi.fn().mockRejectedValue(new DOMException("cancelled", "NotAllowedError")) });
    vi.spyOn(passkeyApi, "fetchLoginOptions").mockResolvedValue(OPTIONS);
    const { getByTestId, queryByRole, findByRole } = render(PasskeySignIn, {
      username: "",
      onSuccess: vi.fn(),
    });

    await waitFor(() => expect(getByTestId("passkey-signin")).toBeTruthy());
    await fireEvent.click(getByTestId("passkey-signin"));
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    expect(queryByRole("alert")).toBeNull();

    get.mockResolvedValueOnce(credential());
    vi.spyOn(authStore, "loginWithPasskey").mockResolvedValue({ success: false, error: "server detail" });
    await fireEvent.click(getByTestId("passkey-signin"));
    expect((await findByRole("alert")).textContent).toBe("Passkey sign-in failed. Use your password instead.");
  });
});
