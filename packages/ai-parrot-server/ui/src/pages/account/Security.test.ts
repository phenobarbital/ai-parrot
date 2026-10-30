import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "$lib/api/http";
import * as passkeyApi from "$lib/api/passkey";
import { authStore } from "$lib/stores/auth.svelte";
import type { PublicKeyCredentialCreationOptionsJSON } from "$lib/webauthn";

import Security from "./Security.svelte";

const ROW = {
  id: "Y3JlZA",
  label: "Laptop",
  created_at: "2026-10-30T00:00:00+00:00",
  last_used_at: null,
  device_type: "multi_device",
  backed_up: true,
  rp_id: "localhost",
};

const CREDENTIAL_JSON = {
  id: "Y3JlZA",
  rawId: "Y3JlZA",
  type: "public-key",
  clientExtensionResults: {},
  response: { clientDataJSON: "Y2xpZW50", attestationObject: "YXR0ZXN0YXRpb24" },
};

const CREATION_OPTIONS: PublicKeyCredentialCreationOptionsJSON = {
  challenge: "Y2hhbGxlbmdl",
  rp: { id: "localhost", name: "AI-Parrot" },
  user: { id: "dXNlcg", name: "alice", displayName: "Alice" },
  pubKeyCredParams: [{ type: "public-key", alg: -7 }],
};

function stubWebAuthn(): ReturnType<typeof vi.fn> {
  const create = vi.fn().mockResolvedValue({
    ...CREDENTIAL_JSON,
    toJSON: () => CREDENTIAL_JSON,
  });
  vi.stubGlobal("PublicKeyCredential", {
    parseCreationOptionsFromJSON: vi.fn((options: unknown) => options),
  });
  vi.stubGlobal("navigator", { credentials: { create } });
  return create;
}

beforeEach(() => {
  localStorage.clear();
  authStore.user = { username: "alice", auth_method: "passkey" };
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Account › Security", () => {
  it("lists passkeys with label, device, synced badge, relying party and dates", async () => {
    vi.spyOn(passkeyApi, "listPasskeys").mockResolvedValue([ROW]);
    const { findByText, getAllByText, getByText } = render(Security);

    expect(await findByText("Laptop")).toBeTruthy();
    expect(getAllByText("Synced")).toHaveLength(2);
    expect(getByText("localhost", { exact: false })).toBeTruthy();
    expect(getByText("Added", { exact: false })).toBeTruthy();
    expect(getByText("Last used Never")).toBeTruthy();
  });

  it("states the current session method", async () => {
    vi.spyOn(passkeyApi, "listPasskeys").mockResolvedValue([]);
    const { findByTestId } = render(Security);

    expect((await findByTestId("session-method")).textContent).toContain("Signed in with a passkey");
  });

  it("shows the empty state", async () => {
    vi.spyOn(passkeyApi, "listPasskeys").mockResolvedValue([]);
    const { findByTestId } = render(Security);

    expect(await findByTestId("passkey-empty")).toBeTruthy();
  });

  it("adds a labelled passkey and refreshes the list", async () => {
    const create = stubWebAuthn();
    const list = vi.spyOn(passkeyApi, "listPasskeys").mockResolvedValueOnce([]).mockResolvedValue([ROW]);
    vi.spyOn(passkeyApi, "fetchRegisterOptions").mockResolvedValue(CREATION_OPTIONS);
    const verify = vi.spyOn(passkeyApi, "verifyRegistration").mockResolvedValue({
      status: "registered",
      id: ROW.id,
    });
    const { findByLabelText, getByTestId } = render(Security);

    await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
    await fireEvent.click(getByTestId("passkey-add"));
    const label = await findByLabelText("Name (optional)");
    await fireEvent.input(label, { target: { value: "Work" } });
    await fireEvent.click(getByTestId("passkey-save"));

    await waitFor(() => expect(verify).toHaveBeenCalledWith(CREDENTIAL_JSON, "Work"));
    expect(create).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
  });

  it("renames, refreshes, and keeps the row when delete returns 409", async () => {
    const list = vi.spyOn(passkeyApi, "listPasskeys").mockResolvedValue([ROW]);
    const rename = vi.spyOn(passkeyApi, "renamePasskey").mockResolvedValue();
    vi.spyOn(passkeyApi, "deletePasskey").mockRejectedValue(
      new ApiError("Last login method", "server", 409),
    );
    const { findByText, findByRole, getByLabelText, getByRole, getByTestId, getByText } = render(Security);

    await findByText("Laptop");
    await fireEvent.click(getByRole("button", { name: "Rename" }));
    await fireEvent.input(getByLabelText("Passkey name"), { target: { value: "Office key" } });
    await fireEvent.click(getByRole("button", { name: "Save" }));
    await waitFor(() => expect(rename).toHaveBeenCalledWith(ROW.id, "Office key"));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));

    await fireEvent.click(getByRole("button", { name: "Delete" }));
    await fireEvent.click(getByTestId("passkey-confirm-delete"));

    expect((await findByRole("alert")).textContent).toContain(
      "You can't delete your only way to sign in. Set a password or add another passkey first.",
    );
    await waitFor(() => expect(list).toHaveBeenCalledTimes(3));
    expect(getByText("Laptop")).toBeTruthy();
  });

  it("shows the relying-party operator hint when registration options return 400", async () => {
    stubWebAuthn();
    vi.spyOn(passkeyApi, "listPasskeys").mockResolvedValue([]);
    vi.spyOn(passkeyApi, "fetchRegisterOptions").mockRejectedValue(
      new ApiError("Origin not configured", "server", 400),
    );
    const { findByRole, getByTestId } = render(Security);

    await fireEvent.click(getByTestId("passkey-add"));

    expect((await findByRole("alert")).textContent).toContain(
      "This site is not configured for passkeys — ask your administrator to add its origin to PASSKEY_RELYING_PARTIES.",
    );
  });
});
