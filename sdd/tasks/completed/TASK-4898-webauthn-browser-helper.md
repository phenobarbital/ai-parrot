# TASK-4898: WebAuthn browser helper (`$lib/webauthn.ts`)

**Feature**: FEAT-772 — Passkey (WebAuthn) sign-in, enrollment and management in the Admin UI
**Spec**: `sdd/specs/passkey-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Every passkey ceremony in the SPA (sign-in in TASK-4901, enrollment in TASK-4902)
needs the same browser plumbing: capability detection, JSON ⇄ ArrayBuffer conversion and
classification of "the user dismissed the prompt". The spec decides **native WebAuthn Level-3
helpers first, hand-written base64url fallback otherwise, no npm dependency** (G5, AC13). The
fallback algorithm is a port of navigator-auth's own `templates/oauth/login.html`
(`b64urlToBuffer`, `bufferToB64url`, `toRequestOptions`, `credentialToJSON`), extended for
**creation** options and **attestation** responses, which that page never needed.

---

## Scope

- Create `packages/ai-parrot-server/ui/src/lib/webauthn.ts` with exactly the eight exports fixed in spec §2 "New Public Interfaces" plus the `PublicKeyCredentialJSON` type.
- Detect native helpers at **call time**, not module load, so tests can stub either path.
- Write `webauthn.test.ts` covering native and fallback paths, base64url round-trips, and `isUserCancelled`.

**NOT in scope**: any HTTP call (TASK-4899), any Svelte component (TASK-4901/TASK-4902), any change
to `vitest-setup.ts` (spec §7: no global WebAuthn stub — the "unsupported browser" branch must stay
testable), any npm dependency.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/ui/test_vitest_passkey_webauthn.py` | CREATE | pytest wrapper running the vitest file(s) (validation contract accepts pytest only) |
| `packages/ai-parrot-server/ui/src/lib/webauthn.ts` | CREATE | Capability detection + JSON/binary conversion + cancel classification |
| `packages/ai-parrot-server/ui/src/lib/webauthn.test.ts` | CREATE | Unit tests (jsdom + stubbed `PublicKeyCredential`) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ._vitest import run_vitest   # packages/ai-parrot-server/tests/ui/_vitest.py (run_vitest(*files) → pnpm exec vitest run, cwd ui/)
```
```ts
// None from the repo. Browser globals only: window.PublicKeyCredential, navigator.credentials,
// atob / btoa, DOMException. Test file:
import { afterEach, describe, expect, it, vi } from "vitest";   // ui/package.json "vitest": "^4.1.12"
```

### Existing Signatures to Use
```ts
// Reference algorithm (upstream, NOT in this repo): navigator-auth templates/oauth/login.html (dev branch)
//   b64urlToBuffer(value): replace -→+ _→/, pad with "=" to %4, atob → Uint8Array → .buffer
//   bufferToB64url(buffer): bytes → String.fromCharCode → btoa → +→- /→_ strip "="
//   toRequestOptions(publicKey): native parseRequestOptionsFromJSON else copy + decode challenge + allowCredentials[].id
//   credentialToJSON(cred): cred.toJSON() else {id, rawId, type, authenticatorAttachment, clientExtensionResults,
//     response: {clientDataJSON, authenticatorData, signature, userHandle}}
// packages/ai-parrot-server/ui/vitest.config.ts:38 — environment: 'jsdom'; :40 setupFiles: ['./vitest-setup.ts']
// Backend options shape (navigator_auth/backends/passkey.py:217-259, :335-395): py_webauthn options_to_json →
//   request: {challenge, timeout?, rpId, allowCredentials: [{id, type, transports?}], userVerification}
//   creation: {rp:{id,name}, user:{id,name,displayName}, challenge, pubKeyCredParams, timeout?, excludeCredentials:[{id,type}],
//              authenticatorSelection:{residentKey:"required", userVerification}, attestation:"none"}
//   — every binary field is base64url (no padding).
```

### Does NOT Exist
- ~~`$lib/webauthn.ts`~~ — created by this task.
- ~~`@simplewebauthn/browser`, `@github/webauthn-json`~~ — not in `ui/package.json`; must not be added (AC13).
- ~~a `PublicKeyCredential` / `navigator.credentials` stub in `vitest-setup.ts`~~ — jsdom has none; stub per test with `vi.stubGlobal`.
- ~~`PublicKeyCredentialRequestOptionsJSON` / `PublicKeyCredentialCreationOptionsJSON` guaranteed in the project's lib.dom~~ — declare local structural aliases if `tsc` does not resolve them (FILL IN below).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_passkey_webauthn.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/webauthn.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/webauthn.test.ts", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Native first, checked at call time: `typeof PublicKeyCredential.parseRequestOptionsFromJSON === "function"`.
- Fallback must handle **both** response shapes: assertion (`authenticatorData`, `signature`, `userHandle`) and attestation (`attestationObject`, `transports` via `getTransports?.()`, `publicKey`/`publicKeyAlgorithm`/`authenticatorData` when the getters exist).
- `isConditionalMediationAvailable()` never throws and resolves `false` when unsupported.
- No `console.*` noise; this is a pure utility module.

---

## Implementation Blueprint

### Steps (in order)
1. Create `webauthn.ts` with the block below — *why*: the signatures are fixed by spec §2 and consumed by TASK-4899/4901/4902.
2. Implement the base64url pair first and test the round-trip — *why*: every fallback path depends on them.
3. Fill the two option converters and `credentialToJSON` fallback — *why*: older browsers (pre Chrome 129 / Safari 18 / Firefox 119) take this path.
4. Write `webauthn.test.ts` — *why*: AC13 requires these files in the vitest Validation Contract.

### `packages/ai-parrot-server/ui/src/lib/webauthn.ts` (CREATE)
```ts
/**
 * WebAuthn browser helpers (FEAT-772, spec §3 Module 1).
 *
 * Native WebAuthn Level-3 JSON helpers are used when the browser has them
 * (Chrome 129+, Safari 18+, Firefox 119+); otherwise a hand-written base64url
 * fallback ported from navigator-auth's templates/oauth/login.html is used.
 * Native support is detected at CALL time so tests can stub either path.
 * No npm dependency on purpose (spec G5 / AC13).
 */

// FILL IN: local structural aliases for PublicKeyCredentialRequestOptionsJSON /
//   PublicKeyCredentialCreationOptionsJSON when the project's lib.dom does not declare them —
//   bounded by: `pnpm exec svelte-check`/tsc must pass; export them so TASK-4899 can import them.

/** Wire shape sent to the backend (`credential` in login and register/verify bodies). */
export type PublicKeyCredentialJSON = {
  id: string;
  rawId: string;
  type: string;
  authenticatorAttachment?: string;
  clientExtensionResults: Record<string, unknown>;
  response: Record<string, unknown>;
};

/** True when `window.PublicKeyCredential` and `navigator.credentials` exist. */
export function isWebAuthnSupported(): boolean {
  return typeof window !== "undefined" && "PublicKeyCredential" in window && !!navigator.credentials;
}

/** Resolves `PublicKeyCredential.isConditionalMediationAvailable()`; false when missing or throwing. */
export async function isConditionalMediationAvailable(): Promise<boolean> {
  // FILL IN: guard isWebAuthnSupported(); typeof check on the static method; try/catch → false
  return false;
}

export function base64UrlToBuffer(value: string): ArrayBuffer {
  // FILL IN: -→+, _→/, pad "=" to a multiple of 4, atob, Uint8Array → .buffer (upstream b64urlToBuffer)
  throw new Error("not implemented");
}

export function bufferToBase64Url(buffer: ArrayBuffer): string {
  // FILL IN: Uint8Array → String.fromCharCode → btoa → +→-, /→_, strip trailing "=" (upstream bufferToB64url)
  throw new Error("not implemented");
}

/** Native parseRequestOptionsFromJSON when present, else decode `challenge` and `allowCredentials[].id`. */
export function toRequestOptions(json: PublicKeyCredentialRequestOptionsJSON): PublicKeyCredentialRequestOptions {
  // FILL IN: native branch; fallback copies json and decodes the two binary fields — bounded by the upstream toRequestOptions
  throw new Error("not implemented");
}

/** Native parseCreationOptionsFromJSON when present, else decode `challenge`, `user.id`, `excludeCredentials[].id`. */
export function toCreationOptions(json: PublicKeyCredentialCreationOptionsJSON): PublicKeyCredentialCreationOptions {
  // FILL IN: same pattern as toRequestOptions; keep rp/pubKeyCredParams/authenticatorSelection/attestation untouched
  throw new Error("not implemented");
}

/** `cred.toJSON()` when present, else a hand-built object covering assertion AND attestation responses. */
export function credentialToJSON(cred: PublicKeyCredential): PublicKeyCredentialJSON {
  // FILL IN: fallback — detect attestation by `"attestationObject" in cred.response`; encode every ArrayBuffer
  //   field with bufferToBase64Url; include transports via (response as AuthenticatorAttestationResponse).getTransports?.();
  //   userHandle → undefined when null — bounded by the backend reading rawId|id and response.userHandle (passkey.py:404-420)
  throw new Error("not implemented");
}

/** True for a dismissed prompt or a superseded request — callers show nothing (spec §7 "Silent cancel"). */
export function isUserCancelled(err: unknown): boolean {
  const name = (err as { name?: unknown } | null)?.name;
  return name === "NotAllowedError" || name === "AbortError";
}
```
**Why this shape**: the export list and names are fixed by spec §2 and imported by three later
tasks; `isUserCancelled` is complete because its rule is decided (spec §7). Do not add exports,
do not read `navigator.credentials` at module load (tests stub per case).

### `packages/ai-parrot-server/ui/src/lib/webauthn.test.ts` (CREATE)
```ts
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

describe("webauthn helpers", () => {
  it("round-trips base64url for padded and unpadded lengths", () => {
    for (const s of ["", "Zg", "Zm8", "Zm9v", "Y2hhbGxlbmdl", "_-8"]) {
      expect(bufferToBase64Url(base64UrlToBuffer(s))).toBe(s);
    }
  });

  it("isUserCancelled is true only for NotAllowedError / AbortError", () => {
    expect(isUserCancelled(new DOMException("x", "NotAllowedError"))).toBe(true);
    expect(isUserCancelled(new DOMException("x", "AbortError"))).toBe(true);
    expect(isUserCancelled(new Error("boom"))).toBe(false);
    expect(isUserCancelled(null)).toBe(false);
  });

  // FILL IN: isWebAuthnSupported false without PublicKeyCredential, true with vi.stubGlobal stubs
  // FILL IN: isConditionalMediationAvailable → false when the static is missing / throws, true when it resolves true
  // FILL IN: toRequestOptions — native branch delegates (spy), fallback decodes challenge + allowCredentials[].id to ArrayBuffer
  // FILL IN: toCreationOptions — fallback decodes challenge, user.id, excludeCredentials[].id
  // FILL IN: credentialToJSON — prefers toJSON(); fallback for an assertion and for an attestation (transports included)
});
```
**Why**: the two complete cases pin the decided rules; the FILL IN cases are the spec §4 rows for M1.

### `packages/ai-parrot-server/tests/ui/test_vitest_passkey_webauthn.py` (CREATE)
```python
"""FEAT-772 (TASK-4898): run the vitest file(s) from pytest (validation contract)."""

from ._vitest import run_vitest


def test_passkey_webauthn_vitest() -> None:
    """WebAuthn helper: native/fallback conversion, base64url, cancel classification."""
    run_vitest("src/lib/webauthn.test.ts")
```
**Why**: `check_task_graph` accepts pytest validation commands only; this is the established wrapper
pattern (`tests/ui/_vitest.py::run_vitest`, e.g. `test_vitest_suggestion_chips.py`). It skips when
`pnpm`/`node_modules` is absent.

### FILL IN checklist
- [ ] `webauthn.ts` — JSON option type aliases if lib.dom lacks them; bounded by svelte-check/tsc passing
- [ ] `webauthn.ts::isConditionalMediationAvailable` — never throws; bounded by spec §7 browser matrix
- [ ] `webauthn.ts::base64UrlToBuffer` / `bufferToBase64Url` — upstream algorithm; bounded by the round-trip test
- [ ] `webauthn.ts::toRequestOptions` / `toCreationOptions` — native-first at call time; bounded by spec §7 "Native-first conversion"
- [ ] `webauthn.ts::credentialToJSON` — assertion + attestation fallback; bounded by passkey.py:404-420 field reads
- [ ] `webauthn.test.ts` — the five FILL IN groups; bounded by spec §4 M1 rows

---

## Acceptance Criteria

- [ ] All eight functions and `PublicKeyCredentialJSON` exported with the spec §2 signatures
- [ ] Native helpers used when present, fallback otherwise — both covered by tests
- [ ] No new dependency in `ui/package.json`; `vitest-setup.ts` unchanged (AC13)
- [ ] `pnpm exec vitest run src/lib/webauthn.test.ts` passes

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_passkey_webauthn.py -q`

---

## Test Specification

See the `webauthn.test.ts` blueprint block above (spec §4 rows for Module 1).

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
   `feat(passkey-support): TASK-4898 — <title>`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4898 passkey-support verified`
   — never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note


- Task: TASK-4898
- Feature: passkey-support
- Implementation SHA: 333cc3adf91cc4dba3739b8e44e10a59d5d6a334
- Closed at (UTC): 2026-10-30T15:41:17+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 197s · Tokens: n/a |
