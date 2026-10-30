# TASK-4899: Passkey API module (`$lib/api/passkey.ts`) and config URLs

**Feature**: FEAT-772 — Passkey (WebAuthn) sign-in, enrollment and management in the Admin UI
**Spec**: `sdd/specs/passkey-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4898
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 and §2 "transport rules". The six `PasskeyAuth` endpoints split in two groups:

1. **Public ceremony calls** — `POST /api/v1/auth/passkey/login/options` and `POST /api/v1/login`
   with `X-Auth-Method: PasskeyAuth` — go through **bare `axios`**, never `apiClient`. The shared
   interceptor (`http.ts:129-141`) calls `authStore.handle401()` on every non-"policy" 401, and the
   backend answers every sign-in failure with the same 401; through `apiClient` a failed attempt
   would clear the session and rewrite `?next=` (AC04).
2. **Authenticated calls** — `register/options`, `register/verify`, `credentials` GET/PATCH/DELETE —
   go through `apiClient` so the Bearer token is injected; Bearer requests skip navigator-auth's
   CSRF check (AC06).

Backend 4xx bodies are `{"reason": "..."}` (`passkey.py:36-56`), which `extractServerMessage` does
**not** read — `passkeyErrorMessage` must check `reason` first (spec §7).

---

## Scope

- Add `passkeyApiPrefix` and `accountSecurityPath` to `config` (`config.ts`).
- Create `lib/api/passkey.ts` with the exports fixed in spec §3 Module 2 (incl. `passkeyErrorMessage`).
- `encodeURIComponent` every credential id in a path; DELETE 204 has no body — never parse it; trim labels (S4).
- Write `lib/api/passkey.test.ts`.

**NOT in scope**: `AuthStore` changes (TASK-4900), UI (TASK-4901/4902), adding `"account"` to
`config.appSections` (TASK-4903 — same file, serialized after this task).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/ui/test_vitest_passkey_api.py` | CREATE | pytest wrapper running the vitest file(s) (validation contract accepts pytest only) |
| `packages/ai-parrot-server/ui/src/lib/api/passkey.ts` | CREATE | Typed wrappers for the six PasskeyAuth endpoints |
| `packages/ai-parrot-server/ui/src/lib/api/passkey.test.ts` | CREATE | Unit tests (mocked axios / apiClient) |
| `packages/ai-parrot-server/ui/src/lib/config.ts` | MODIFY | Add `passkeyApiPrefix`, `accountSecurityPath` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ._vitest import run_vitest   # packages/ai-parrot-server/tests/ui/_vitest.py (run_vitest(*files) → pnpm exec vitest run, cwd ui/)
```
```ts
import axios from "axios";                                                   // ui/package.json "axios": "^1.16.1"
import apiClient, { ApiError, extractServerMessage } from "$lib/api/http";  // http.ts:197 default, :31, :80
import { config } from "$lib/config";                                         // config.ts `export const config`
import type { PublicKeyCredentialJSON } from "$lib/webauthn";                 // TASK-4898
```

### Existing Signatures to Use
```ts
// packages/ai-parrot-server/ui/src/lib/api/http.ts
export class ApiError extends Error {                                       // :31
  constructor(message: string, public readonly code: "network"|"timeout"|"server"|"auth"|"unknown",
              public readonly status?: number, public readonly raw?: unknown)   // raw = { response: { status, data } , ... } (safeRaw)
}
export function extractServerMessage(data: unknown, status: number): string  // :80 — reads error | message | message.message | detail; else "HTTP <status>"
// interceptor (:114-160): adds Authorization: Bearer <ai_parrot_token>; 401 → authStore.handle401() unless /policy/i;
//   403 → ApiError("Forbidden","auth",403); 404 → ApiError("Not found","server",404); other → ApiError(extractServerMessage(...), "server", status)
const apiClient = axios.create({ baseURL: config.apiBaseUrl, timeout: 300000, withCredentials: config.apiWithCredentials, ... })  // :164
export default apiClient;                                                    // :197

// packages/ai-parrot-server/ui/src/lib/config.ts
loginUrl: "/api/v1/login",                // :63
authMethodsUrl: "/api/v1/auth/methods",   // :65  ← insert the two new keys right after this line
apiBaseUrl: string ("" default), apiWithCredentials: boolean, basePath: "" (const above `config`)

// Bare-axios precedent: packages/ai-parrot-server/ui/src/pages/Login.svelte:49-57
//   axios.get(`${config.apiBaseUrl}${config.authMethodsUrl}`, { withCredentials: config.apiWithCredentials })

// Backend (navigator_auth 0.28.9, backends/passkey.py)
// PASSKEY_PREFIX = "/api/v1/auth/passkey" (:35)
// POST login/options  body {username?} → 200 {challenge_id, publicKey}; 429 when rate-limited; 4xx {reason} when origin not an RP   (:335)
// POST /api/v1/login  header X-Auth-Method: PasskeyAuth, body {challenge_id, credential} → login envelope (token, user fields, auth_method, mfa, amr) (:397)
// POST register/options body {} → creation options JSON (:217)
// POST register/verify  body {credential, label?≤128} → 201 {status:"registered", id}; 400; 401; 409 (:261)
// GET  credentials → [{id,label,created_at,last_used_at,device_type,backed_up,rp_id}] (:510)
// PATCH credentials/{id} body {label 1..128} → 200 {status:"renamed"}; 400; 404 (:532)
// DELETE credentials/{id} → 204 (no body); 404; 409 "Passkey: cannot delete the last login method" (:549)
```

### Does NOT Exist
- ~~`config.passkeyApiPrefix`~~, ~~`config.accountSecurityPath`~~ — added by this task.
- ~~`extractServerMessage` reading `reason`~~ — it does not (http.ts:80-106); check `reason` yourself.
- ~~a passkey method on `apiClient`~~ / ~~`$lib/api/auth.ts`~~ — no such module; create `passkey.ts` only.
- ~~`/api/v1/auth/passkey/login/verify`~~ — sign-in verification is `POST /api/v1/login` with `X-Auth-Method: PasskeyAuth`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/tests/ui/test_vitest_passkey_api.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/api/passkey.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/api/passkey.test.ts", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/ui/src/lib/config.ts", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/ui/src/lib/api/http.ts#ApiError",
    "sym:packages/ai-parrot-server/ui/src/lib/api/http.ts#extractServerMessage",
    "sym:packages/ai-parrot-server/ui/src/lib/config.ts#config"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the two config keys — *why*: every URL in `passkey.ts` derives from `passkeyApiPrefix`; `accountSecurityPath` is consumed by TASK-4903.
2. Create `passkey.ts` — *why*: fixed API surface for TASK-4900/4901/4902.
3. Write tests asserting **which transport** each call uses — *why*: AC04/AC06 are about the transport, not just the URL.

### `packages/ai-parrot-server/ui/src/lib/config.ts` (MODIFY)
```ts
// occurrences: 1 (verified: grep -c '  authMethodsUrl: "/api/v1/auth/methods",' config.ts)
// AFTER — insert below `  authMethodsUrl: "/api/v1/auth/methods",` (verified: config.ts:65)
  /** FEAT-772: navigator-auth PasskeyAuth route prefix (navigator_auth/backends/passkey.py:35 PASSKEY_PREFIX). */
  passkeyApiPrefix: "/api/v1/auth/passkey",
  /** FEAT-772: user-level passkey management page (route added by the account section). */
  accountSecurityPath: `${basePath}/account/security`,
```
**Why**: `basePath` is the module-level const already used by `loginPath`/`homePath`; keep keys inside the `config` object literal.

### `packages/ai-parrot-server/ui/src/lib/api/passkey.ts` (CREATE)
```ts
/**
 * navigator-auth PasskeyAuth client (FEAT-772, spec §3 Module 2).
 *
 * Transport rule (spec §2): the two PUBLIC ceremony calls use bare axios —
 * never apiClient — because apiClient's 401 interceptor calls
 * authStore.handle401(), and PasskeyAuth answers every sign-in failure with
 * the same 401 (it would clear the session and rewrite ?next=). Every
 * authenticated call uses apiClient so the Bearer token is injected (Bearer
 * requests skip navigator-auth's CSRF check).
 */
import axios from "axios";

import apiClient, { ApiError, extractServerMessage } from "$lib/api/http";
import { config } from "$lib/config";
import type { PublicKeyCredentialJSON } from "$lib/webauthn";

export interface PasskeyLoginOptions {
  challenge_id: string;
  publicKey: PublicKeyCredentialRequestOptionsJSON;
}

export interface PasskeyCredentialSummary {
  id: string;
  label: string | null;
  created_at: string | null;
  last_used_at: string | null;
  device_type: string | null;
  backed_up: boolean;
  rp_id: string;
}

const prefix = (): string => `${config.apiBaseUrl}${config.passkeyApiPrefix}`;

/** POST login/options via bare axios. Returns null on ANY failure (404 disabled, 429 rate-limited, 4xx origin, network). */
export async function fetchLoginOptions(username?: string): Promise<PasskeyLoginOptions | null> {
  try {
    const { data } = await axios.post(`${prefix()}/login/options`, username ? { username } : {}, {
      withCredentials: config.apiWithCredentials,
    });
    // FILL IN: validate shape (challenge_id string + publicKey object) else return null — bounded by AC01
    return data as PasskeyLoginOptions;
  } catch {
    return null;
  }
}

/** POST config.loginUrl with X-Auth-Method: PasskeyAuth via bare axios; resolves to the login envelope; rejects with the raw axios error. */
export async function postPasskeyLogin(body: {
  challenge_id: string;
  credential: PublicKeyCredentialJSON;
}): Promise<Record<string, unknown>> {
  const { data } = await axios.post(`${config.apiBaseUrl}${config.loginUrl}`, body, {
    headers: { "X-Auth-Method": "PasskeyAuth" },
    withCredentials: config.apiWithCredentials,
  });
  return data as Record<string, unknown>;
}

/** POST register/options with body {} through apiClient (Bearer). */
export async function fetchRegisterOptions(): Promise<PublicKeyCredentialCreationOptionsJSON> {
  const { data } = await apiClient.post(`${config.passkeyApiPrefix}/register/options`, {});
  return data as PublicKeyCredentialCreationOptionsJSON;
}

/** POST register/verify {credential, label?}; 201 → {status, id}. ApiError 409 = already registered, 400 = failed / label too long. */
export async function verifyRegistration(
  credential: PublicKeyCredentialJSON,
  label?: string,
): Promise<{ status: "registered"; id: string }> {
  // FILL IN: body {credential} plus label only when non-empty after trim — bounded by backend ≤128 (passkey.py:276-278)
  throw new Error("not implemented");
}

export async function listPasskeys(): Promise<PasskeyCredentialSummary[]> {
  const { data } = await apiClient.get(`${config.passkeyApiPrefix}/credentials`);
  return Array.isArray(data) ? (data as PasskeyCredentialSummary[]) : [];
}

export async function renamePasskey(id: string, label: string): Promise<void> {
  // FILL IN: PATCH `${config.passkeyApiPrefix}/credentials/${encodeURIComponent(id)}` with {label: label.trim()};
  //   reject client-side (throw Error) when trimmed length is not 1..128 — bounded by passkey.py:532-547
  throw new Error("not implemented");
}

export async function deletePasskey(id: string): Promise<void> {
  // FILL IN: DELETE `${config.passkeyApiPrefix}/credentials/${encodeURIComponent(id)}`; 204 has NO body — do not read data
  throw new Error("not implemented");
}

/** Human message for a passkey error: backend `{reason}` first, then extractServerMessage, then err.message. */
export function passkeyErrorMessage(err: unknown): string {
  // FILL IN: read (err as ApiError).raw?.response?.data?.reason (ApiError path) and
  //   (err as {response?: {data?: {reason?}}}).response?.data?.reason (bare axios path); fall back to
  //   extractServerMessage(data, status) and finally (err as Error).message || "Passkey request failed"
  void ApiError;
  void extractServerMessage;
  return "Passkey request failed";
}
```
**Why this shape**: the transport per function is the decision under test; do not route the two
public calls through `apiClient`, and do not add `${config.apiBaseUrl}` to `apiClient` URLs (its
`baseURL` already has it). Remove the two `void` lines once `passkeyErrorMessage` uses the imports.

### `packages/ai-parrot-server/ui/src/lib/api/passkey.test.ts` (CREATE)
```ts
import axios from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

import apiClient from "$lib/api/http";

import { fetchLoginOptions, listPasskeys, postPasskeyLogin } from "./passkey";

afterEach(() => vi.restoreAllMocks());

describe("passkey api", () => {
  it("fetchLoginOptions uses bare axios, never apiClient, and sends {} without a username", async () => {
    const opts = { challenge_id: "c1", publicKey: { challenge: "Y2g", rpId: "localhost", allowCredentials: [] } };
    const bare = vi.spyOn(axios, "post").mockResolvedValue({ data: opts });
    const client = vi.spyOn(apiClient, "post");
    expect(await fetchLoginOptions()).toEqual(opts);
    expect(bare).toHaveBeenCalledWith("/api/v1/auth/passkey/login/options", {}, expect.any(Object));
    expect(client).not.toHaveBeenCalled();
  });

  it("fetchLoginOptions returns null on 404", async () => {
    vi.spyOn(axios, "post").mockRejectedValue({ response: { status: 404 } });
    expect(await fetchLoginOptions("alice")).toBeNull();
  });

  it("postPasskeyLogin posts to /api/v1/login with X-Auth-Method: PasskeyAuth via bare axios", async () => {
    const bare = vi.spyOn(axios, "post").mockResolvedValue({ data: { token: "t" } });
    await postPasskeyLogin({ challenge_id: "c1", credential: { id: "x", rawId: "x", type: "public-key", clientExtensionResults: {}, response: {} } });
    expect(bare).toHaveBeenCalledWith(
      "/api/v1/login",
      expect.objectContaining({ challenge_id: "c1" }),
      expect.objectContaining({ headers: { "X-Auth-Method": "PasskeyAuth" } }),
    );
  });

  it("listPasskeys goes through apiClient", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: [] });
    expect(await listPasskeys()).toEqual([]);
    expect(get).toHaveBeenCalledWith("/api/v1/auth/passkey/credentials");
  });

  // FILL IN: fetchLoginOptions sends {username} when given
  // FILL IN: fetchRegisterOptions / verifyRegistration(label trimmed, omitted when empty) / renamePasskey / deletePasskey
  //   use apiClient with the right method + URL; ids are encodeURIComponent'ed (use an id containing "/")
  // FILL IN: renamePasskey rejects "" and a 129-char label without calling apiClient
  // FILL IN: passkeyErrorMessage — {reason} from ApiError.raw.response.data, {reason} from a bare axios error, fallback
});
```

### `packages/ai-parrot-server/tests/ui/test_vitest_passkey_api.py` (CREATE)
```python
"""FEAT-772 (TASK-4899): run the vitest file(s) from pytest (validation contract)."""

from ._vitest import run_vitest


def test_passkey_api_vitest() -> None:
    """Passkey API: bare-axios public calls, apiClient authenticated calls, error messages."""
    run_vitest("src/lib/api/passkey.test.ts")
```
**Why**: `check_task_graph` accepts pytest validation commands only; this is the established wrapper
pattern (`tests/ui/_vitest.py::run_vitest`, e.g. `test_vitest_suggestion_chips.py`). It skips when
`pnpm`/`node_modules` is absent.

### FILL IN checklist
- [ ] `passkey.ts::fetchLoginOptions` — shape check; bounded by AC01 (anything unexpected ⇒ null ⇒ UI hidden)
- [ ] `passkey.ts::verifyRegistration` — label handling; bounded by passkey.py:276-278
- [ ] `passkey.ts::renamePasskey` / `deletePasskey` — encodeURIComponent, 1..128 trim, no body read on 204; bounded by spec §9 S4
- [ ] `passkey.ts::passkeyErrorMessage` — `reason` precedence; bounded by spec §7 "extractServerMessage ignores {reason}"
- [ ] `passkey.test.ts` — the four FILL IN groups; bounded by spec §4 M2 rows

---

## Acceptance Criteria

- [ ] `fetchLoginOptions` and `postPasskeyLogin` never touch `apiClient` (asserted by tests) — AC04
- [ ] Authenticated calls use `apiClient` and send no CSRF header — AC06
- [ ] Credential ids are URL-encoded; DELETE does not parse a body; labels trimmed and bounded
- [ ] `config.passkeyApiPrefix === "/api/v1/auth/passkey"`, `config.accountSecurityPath === "/account/security"`
- [ ] `pnpm exec vitest run src/lib/api/passkey.test.ts` passes

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/ui/test_vitest_passkey_api.py -q`

---

## Test Specification

See the `passkey.test.ts` blueprint block above (spec §4 rows for Module 2).

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
   `feat(passkey-support): TASK-4899 — <title>`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4899 passkey-support verified`
   — never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note


- Task: TASK-4899
- Feature: passkey-support
- Implementation SHA: f90edd91145007037d12982a9fe71c71e36972bc
- Closed at (UTC): 2026-10-30T15:47:35+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 190s · Tokens: n/a |
