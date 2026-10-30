# TASK-4901: Passkey sign-in on the login page (`PasskeySignIn.svelte`)

**Feature**: FEAT-772 — Passkey (WebAuthn) sign-in, enrollment and management in the Admin UI
**Spec**: `sdd/specs/passkey-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4898, TASK-4899, TASK-4900
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, G1/G3, AC01–AC04, AC09, AC14. The login page gains a "Sign in with a passkey"
button and conditional UI (passkey autofill on the username field). Visibility is decided at
runtime — WebAuthn present **and** the public `login/options` call answers — with **one** request
per page load: the mount-time usernameless response is reused as the conditional-UI challenge. A
click aborts that pending conditional request and fetches a **fresh** challenge, username-scoped
when the field is filled (the backend only fills `allowCredentials` / `expected_user_id` when a
username is sent — codex S3). Today `ProviderButtons` would also render the `PasskeyAuth` backend
as a disabled "Not yet supported" button; it must filter it out like BasicAuth.

---

## Scope

- Create `lib/components/auth/PasskeySignIn.svelte` (props fixed by spec §3 M4) and its test.
- In `Login.svelte`: `autocomplete="username webauthn"`, mount `<PasskeySignIn>` above `<ProviderButtons>`.
- In `ProviderButtons.svelte`: add `isPasskeyAuth()` and filter it.
- Extend `Login.test.ts` (autocomplete, PasskeyAuth filtered, existing tests still green).

**NOT in scope**: `/account/security` (TASK-4902), Topbar/nav (TASK-4903), the inline admin page
(TASK-4907), any change to the BasicAuth `login()` path.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/ui/test_vitest_passkey_sign_in.py` | CREATE | pytest wrapper running the vitest file(s) (validation contract accepts pytest only) |
| `packages/ai-parrot-server/ui/src/lib/components/auth/PasskeySignIn.svelte` | CREATE | Probe + conditional UI + button + error |
| `packages/ai-parrot-server/ui/src/lib/components/auth/PasskeySignIn.test.ts` | CREATE | Component tests with stubbed WebAuthn |
| `packages/ai-parrot-server/ui/src/pages/Login.svelte` | MODIFY | `username webauthn` autocomplete; mount the component |
| `packages/ai-parrot-server/ui/src/pages/Login.test.ts` | MODIFY | New assertions; keep existing tests green |
| `packages/ai-parrot-server/ui/src/lib/components/ProviderButtons.svelte` | MODIFY | Filter the `PasskeyAuth` method |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ._vitest import run_vitest   # packages/ai-parrot-server/tests/ui/_vitest.py (run_vitest(*files) → pnpm exec vitest run, cwd ui/)
```
```ts
import { onDestroy, onMount } from "svelte";
import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";       // ui/button/index.ts exports Button
import { authStore } from "$lib/stores/auth.svelte";                         // + loginWithPasskey (TASK-4900)
import { fetchLoginOptions, type PasskeyLoginOptions } from "$lib/api/passkey";   // TASK-4899
import { credentialToJSON, isConditionalMediationAvailable, isUserCancelled, isWebAuthnSupported, toRequestOptions } from "$lib/webauthn"; // TASK-4898
// Login.svelte already imports: onMount, axios, config, ProviderButtons + AuthMethodInfo (:16), isInAppPath + router, authStore, Button, Card*, Input, Label
```

### Existing Signatures to Use
```svelte
<!-- packages/ai-parrot-server/ui/src/pages/Login.svelte -->
let username = $state(""); let loading = $state(false);
function nextTarget(): string                                  <!-- :28 — guarded ?next= else config.homePath -->
<Input id="username" type="text" bind:value={username} disabled={loading} required
       autocomplete="username" />                              <!-- autocomplete line :105 -->
<ProviderButtons {methods} />                                  <!-- :138 -->

<!-- packages/ai-parrot-server/ui/src/lib/components/ProviderButtons.svelte -->
export interface AuthMethodInfo { name; uri; description; icon; external: boolean; headers: Record<string,string> }  <!-- :20 -->
function isBasicAuth(info: AuthMethodInfo): boolean {          <!-- :36 -->
  const header = info.headers?.["x-auth-method"];
  return typeof header === "string" && header.toLowerCase() === "basicauth";
}
const providers = $derived(methods ? Object.entries(methods).map(([key, info]) => ({ key, info }))
  .filter(({ info }) => !isBasicAuth(info)) : []);              <!-- filter line :45 -->
```
```ts
// Backend facts: PasskeyAuth advertises headers {"x-auth-method": "PasskeyAuth"} — _service = class name
//   (navigator_auth/backends/abstract.py:100, :130). Every sign-in failure → uniform 401 (passkey.py:327-333).
// Login.test.ts:20 beforeEach mocks axios.get (auth/methods discovery). jsdom has NO PublicKeyCredential,
//   so PasskeySignIn renders nothing in the existing Login tests (isWebAuthnSupported() === false).
```

### Does NOT Exist
- ~~`lib/components/auth/`~~ — directory created by this task.
- ~~`isPasskeyAuth`~~ — added here.
- ~~a global WebAuthn stub in `vitest-setup.ts`~~ — stub per test with `vi.stubGlobal("PublicKeyCredential", ...)` and `Object.defineProperty(navigator, "credentials", ...)`.
- ~~`authStore.loginWithPasskey` taking a username~~ — signature is `(challengeId, credential)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_passkey_sign_in.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/auth/PasskeySignIn.svelte", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/auth/PasskeySignIn.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/pages/Login.svelte", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/pages/Login.test.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/components/ProviderButtons.svelte", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/ui/src/lib/components/ProviderButtons.svelte#isBasicAuth",
    "sym:packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts#AuthStore"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `isPasskeyAuth` to `ProviderButtons` — *why*: otherwise a dead disabled button duplicates the new control (AC09).
2. Create `PasskeySignIn.svelte` — *why*: isolates the ceremony state machine from the password form.
3. Wire it into `Login.svelte` and change the autocomplete token — *why*: conditional UI only triggers on `autocomplete="... webauthn"`.
4. Write `PasskeySignIn.test.ts`, then extend `Login.test.ts` — *why*: spec §4 M4 rows.

### `packages/ai-parrot-server/ui/src/lib/components/ProviderButtons.svelte` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c '  function isBasicAuth(info: AuthMethodInfo): boolean {' ProviderButtons.svelte)
// AFTER the closing brace of isBasicAuth (starts at ProviderButtons.svelte:36), insert:
  /** PasskeyAuth gets its own control (PasskeySignIn) — never a generic provider button (FEAT-772). */
  function isPasskeyAuth(info: AuthMethodInfo): boolean {
    const header = info.headers?.["x-auth-method"];
    return typeof header === "string" && header.toLowerCase() === "passkeyauth";
  }

// occurrences: 1 (verified: grep -c '          .filter(({ info }) => !isBasicAuth(info))' ProviderButtons.svelte)
// REPLACE `          .filter(({ info }) => !isBasicAuth(info))` (verified: ProviderButtons.svelte:45) with:
          .filter(({ info }) => !isBasicAuth(info) && !isPasskeyAuth(info))
```
Also update the header comment's "BasicAuth is always excluded" sentence to mention PasskeyAuth.

### `packages/ai-parrot-server/ui/src/lib/components/auth/PasskeySignIn.svelte` (CREATE)
```svelte
<!--
  PasskeySignIn (FEAT-772, spec §3 Module 4) — passkey button + conditional UI.
  Renders NOTHING unless WebAuthn exists and POST login/options answers (one call
  per mount; that response doubles as the conditional-UI challenge). A click aborts
  the pending conditional request and fetches a fresh, username-scoped challenge.
-->
<script lang="ts">
  import { onDestroy, onMount } from "svelte";

  import { fetchLoginOptions, type PasskeyLoginOptions } from "$lib/api/passkey";
  import { authStore } from "$lib/stores/auth.svelte";
  import { Button } from "$lib/ui/internal/shadcn/ui/button/index.js";
  import {
    credentialToJSON,
    isConditionalMediationAvailable,
    isUserCancelled,
    isWebAuthnSupported,
    toRequestOptions,
  } from "$lib/webauthn";

  interface Props {
    /** Current username field value (username-first when non-empty). */
    username: string;
    /** Called after a successful login; Login.svelte navigates to nextTarget(). */
    onSuccess: () => void;
    /** Disabled while the password form submits. */
    disabled?: boolean;
  }

  let { username, onSuccess, disabled = false }: Props = $props();

  const FAILED = "Passkey sign-in failed. Use your password instead.";
  let available = $state(false);
  let busy = $state(false);
  let error = $state("");
  let pending: AbortController | null = null;

  async function runCeremony(started: PasskeyLoginOptions, mediation?: "conditional"): Promise<void> {
    // FILL IN: controller = new AbortController(); pending = controller;
    //   cred = await navigator.credentials.get({ publicKey: toRequestOptions(started.publicKey), signal, ...(mediation && { mediation }) });
    //   if (!cred) return; result = await authStore.loginWithPasskey(started.challenge_id, credentialToJSON(cred as PublicKeyCredential));
    //   success → onSuccess(); failure → error = FAILED (never the server reason — AC14);
    //   catch: isUserCancelled(err) → silent, else error = FAILED; finally clear pending/busy for THIS controller only.
  }

  async function handleClick(): Promise<void> {
    error = "";
    pending?.abort();   // an explicit click supersedes the conditional request (two concurrent get() calls reject)
    pending = null;
    busy = true;
    const started = await fetchLoginOptions(username.trim() || undefined);
    if (!started) {
      busy = false;
      error = FAILED;
      return;
    }
    await runCeremony(started);
    // NOTE: conditional UI is NOT re-armed after a modal attempt (its challenge was consumed / aborted).
  }

  onMount(async () => {
    if (!isWebAuthnSupported()) return;
    const started = await fetchLoginOptions();
    if (!started) return;
    available = true;
    if (await isConditionalMediationAvailable()) void runCeremony(started, "conditional");
  });

  onDestroy(() => pending?.abort());
</script>

{#if available}
  <div class="flex flex-col gap-2">
    <Button
      type="button"
      variant="outline"
      class="w-full"
      data-testid="passkey-signin"
      disabled={disabled || busy}
      onclick={handleClick}
    >
      {busy ? "Waiting for passkey…" : "Sign in with a passkey"}
    </Button>
    {#if error}
      <div
        class="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        role="alert"
        data-testid="passkey-error"
      >
        {error}
      </div>
    {/if}
  </div>
{/if}
```
**Why this shape**: the state machine is decided (spec §3 M4, §7). `onSuccess` takes no argument —
`Login.svelte` already owns `nextTarget()`, so the component never re-derives `?next=`. The
conditional request must not set `busy` (the button stays usable while autofill is armed).

### `packages/ai-parrot-server/ui/src/pages/Login.svelte` (MODIFY)
```svelte
<!-- occurrences: 1 (verified: grep -c '  import ProviderButtons, { type AuthMethodInfo } from "$lib/components/ProviderButtons.svelte";' Login.svelte) -->
<!-- AFTER — insert below that import (verified: Login.svelte:16) -->
  import PasskeySignIn from "$lib/components/auth/PasskeySignIn.svelte";

<!-- occurrences: 1 (verified: grep -c '            autocomplete="username"' Login.svelte) -->
<!-- REPLACE `            autocomplete="username"` (verified: Login.svelte:105) with: -->
            autocomplete="username webauthn"

<!-- occurrences: 1 (verified: grep -c '      <ProviderButtons {methods} />' Login.svelte) -->
<!-- BEFORE — insert above `      <ProviderButtons {methods} />` (verified: Login.svelte:138) -->
      <PasskeySignIn
        {username}
        disabled={loading}
        onSuccess={() => router.navigate(nextTarget(), { replace: true })}
      />
```
**Why**: same navigation as the password path (`Login.svelte:72-73`), so `?next=` handling stays in one place.

### `packages/ai-parrot-server/ui/src/lib/components/auth/PasskeySignIn.test.ts` (CREATE)
```ts
import { fireEvent, render, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as passkeyApi from "$lib/api/passkey";
import { authStore } from "$lib/stores/auth.svelte";

import PasskeySignIn from "./PasskeySignIn.svelte";

const OPTIONS = { challenge_id: "chal-1", publicKey: { challenge: "Y2hhbGxlbmdl", rpId: "localhost", allowCredentials: [], userVerification: "required" } };

function stubWebAuthn({ conditional = false, get = vi.fn() } = {}) {
  vi.stubGlobal("PublicKeyCredential", Object.assign(function () {}, {
    isConditionalMediationAvailable: () => Promise.resolve(conditional),
  }));
  Object.defineProperty(navigator, "credentials", { configurable: true, value: { get } });
  return get;
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
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

  // FILL IN: conditional armed once — exactly one fetchLoginOptions call on mount, get() called with mediation "conditional"
  //   and the mount-time publicKey (toRequestOptions may be the fallback: assert challenge is an ArrayBuffer)
  // FILL IN: click aborts the conditional signal, calls fetchLoginOptions("alice") when username="alice",
  //   calls authStore.loginWithPasskey("chal-…", …) (spy) and onSuccess on {success:true}
  // FILL IN: NotAllowedError from get() → no [role=alert]; loginWithPasskey {success:false} → exact FAILED text
  void fireEvent;
  void authStore;
  void OPTIONS;
});
```

### `packages/ai-parrot-server/ui/src/pages/Login.test.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c '    vi.spyOn(axios, "get").mockResolvedValue({ data: {} });' Login.test.ts)
// The beforeEach at Login.test.ts:20 stays as is. APPEND two tests at the end of describe("Login"):
  it("marks the username input for passkey autofill", () => {
    const { getByLabelText } = render(Login);
    expect(getByLabelText("Username").getAttribute("autocomplete")).toBe("username webauthn");
  });

  it("never renders the PasskeyAuth discovery entry as a provider button", async () => {
    vi.spyOn(axios, "get").mockResolvedValue({
      data: {
        passkey: { name: "PasskeyAuth", uri: "/api/v1/login", description: "Passkey (WebAuthn) authentication",
                   icon: "", external: false, headers: { "x-auth-method": "PasskeyAuth" } },
      },
    });
    const { queryByText, queryByTestId } = render(Login);
    await waitFor(() => expect(axios.get).toHaveBeenCalled());
    expect(queryByText("Passkey (WebAuthn) authentication")).toBeNull();
    expect(queryByTestId("provider-buttons")).toBeNull();
  });
```

### `packages/ai-parrot-server/tests/ui/test_vitest_passkey_sign_in.py` (CREATE)
```python
"""FEAT-772 (TASK-4901): run the vitest file(s) from pytest (validation contract)."""

from ._vitest import run_vitest


def test_passkey_sign_in_vitest() -> None:
    """Login page passkey button, conditional UI, ProviderButtons filtering."""
    run_vitest("src/lib/components/auth/PasskeySignIn.test.ts", "src/pages/Login.test.ts")
```
**Why**: `check_task_graph` accepts pytest validation commands only; this is the established wrapper
pattern (`tests/ui/_vitest.py::run_vitest`, e.g. `test_vitest_suggestion_chips.py`). It skips when
`pnpm`/`node_modules` is absent.

### FILL IN checklist
- [ ] `PasskeySignIn.svelte::runCeremony` — controller ownership, silent cancel, generic failure; bounded by AC02–AC04, AC14
- [ ] `PasskeySignIn.test.ts` — the three FILL IN groups, then delete the `void` lines; bounded by spec §4 M4 rows

---

## Acceptance Criteria

- [ ] Unsupported browser or failed probe ⇒ nothing rendered, no retry (AC01)
- [ ] One `login/options` call on mount, reused for conditional UI (AC02)
- [ ] Click aborts conditional, sends `{username}` when typed, navigates via `nextTarget()` on success (AC03)
- [ ] Cancel is silent; any failure shows exactly "Passkey sign-in failed. Use your password instead." (AC04, AC14)
- [ ] `PasskeyAuth` never rendered by `ProviderButtons` (AC09)
- [ ] Existing `Login.test.ts` cases still pass

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_passkey_sign_in.py -q`

---

## Test Specification

See the two test blueprint blocks above (spec §4 rows for Module 4).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug passkey-support --feature-id FEAT-772`)
2. **Read the spec** at `sdd/specs/passkey-support.spec.md` (§2 transport rules, §6 contract, §7 risks)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/passkey-support.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Re-run `grep -c` for every MODIFY anchor in the blueprint; a count that differs means the anchor moved — re-locate it; a count of `0` means drift — stop and report
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/passkey-support.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `FILL IN` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria — run the Validation Commands. Vitest commands run from
   `packages/ai-parrot-server/ui` (`pnpm exec vitest run <file>`); pytest commands from the worktree
   root with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`):
   `feat(passkey-support): TASK-4901 — <title>`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4901 passkey-support verified`
   — never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note


- Task: TASK-4901
- Feature: passkey-support
- Implementation SHA: 1f95ee033d91ebb07317eec4becdfb8b93edac62
- Closed at (UTC): 2026-10-30T16:00:46+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 112s · Tokens: n/a |
