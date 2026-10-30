# TASK-4906: Operator docs for passkeys and `docs/examples/passkey.settings.example`

**Feature**: FEAT-772 — Passkey (WebAuthn) sign-in, enrollment and management in the Admin UI
**Spec**: `sdd/specs/passkey-support.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (docs half), AC11, codex S10/S12. Operators need to enable `PasskeyAuth` from
ai-parrot alone. The brainstorm resolved **where**: a section in `docs/admin-ui.md` plus a tracked,
copy-ready `docs/examples/passkey.settings.example` (`/settings/` is git-ignored, `.gitignore:271`).
The relying party is resolved **only** from the browser `Origin` (exact match), so `pnpm dev`
(`http://localhost:5173`) and the backend (`http://localhost:5000`) are different RPs — the Vite
proxy's `changeOrigin: true` (`vite.config.ts:84`) rewrites `Host`, not `Origin`.

---

## Scope

- Create `docs/examples/passkey.settings.example` (dotenv style: one `KEY=value` per line, `#` comments; `PASSKEY_RELYING_PARTIES` as single-quoted one-line JSON).
- `docs/admin-ui.md`: a "Passkeys" bullet in **Auth model** (:44 block) and a passkey block in **Quick start** next to the `**Login**` bullet (:221).
- Add `packages/ai-parrot-server/tests/test_passkey_settings_example.py`: parse the example and validate the RP list with navigator-auth's real `RelyingPartyResolver`.

**NOT in scope**: `pyproject.toml` / `uv.lock` (TASK-4905), any code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/examples/passkey.settings.example` | CREATE | Copy-ready settings |
| `docs/admin-ui.md` | MODIFY | Auth model + Quick start passkey sections |
| `packages/ai-parrot-server/tests/test_passkey_settings_example.py` | CREATE | Validates the example against `RelyingPartyResolver` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import json
from pathlib import Path
from navigator_auth.passkey.rp import RelyingPartyResolver   # .venv/.../navigator_auth/passkey/rp.py:44 — no webauthn import needed
from navigator_auth.exceptions import ConfigError            # imported by rp.py:9
```

### Existing Signatures to Use
```python
# navigator_auth/passkey/rp.py
class RelyingPartyResolver:                       # :44
    def __init__(self, parties: list[dict]) -> None:   # :47 — ConfigError when empty, invalid entry,
        # rp_id not host/parent of origin host (:68-72), or duplicate origin (:74)
# navigator_auth/passkey/types.py — RelyingParty{origin, rp_id, rp_name="Navigator", org_id?, client_id?}
# navigator_auth/conf.py — PASSKEY_RELYING_PARTIES (:598, JSON list), PASSKEY_CHALLENGE_TTL=300 (:609),
#   PASSKEY_USER_VERIFICATION="required" (:611, required|preferred|discouraged), PASSKEY_TENANT_ATTRIBUTE (:613),
#   PASSKEY_DECOY_CREDENTIALS=1 (:615), PASSKEY_LOGIN_OPTIONS_RATE=0 (:617); AUTHENTICATION_BACKENDS comma list (:188-192)
```
```markdown
<!-- docs/admin-ui.md -->
:44   - Login: `POST /api/v1/login` with a `BasicAuth` username/password form.
:221  - **Login**: set `AUTHENTICATION_BACKENDS=navigator_auth.backends.BasicAuth`
```

### Does NOT Exist
- ~~`docs/examples/`~~ — created here.
- ~~`settings/settings.py` as a tracked file~~ — git-ignored; do not edit it.
- ~~Related Origin Requests support~~ — upstream limitation: each origin needs its own entry.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/examples/passkey.settings.example", "action": "CREATE"},
    {"path": "docs/admin-ui.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/test_passkey_settings_example.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write the example file — *why*: docs link to it; the test validates it.
2. Write the test — *why*: a wrong `rp_id` in docs would stop operators' servers at startup.
3. Edit `docs/admin-ui.md` — *why*: AC11 content list.

### `docs/examples/passkey.settings.example` (CREATE)
```bash
# Passkey (WebAuthn) sign-in for the AI-Parrot Admin UI (FEAT-772).
# Copy into your env/settings. Requires: pip install "ai-parrot-server[passkey]", Redis >= 6.2.
AUTHENTICATION_BACKENDS=navigator_auth.backends.BasicAuth,navigator_auth.backends.PasskeyAuth
# One entry per EXACT browser origin (scheme://host:port). rp_id = that host or a parent domain.
# The Vite dev server (pnpm dev, :5173) is a different origin from the backend (:5000).
PASSKEY_RELYING_PARTIES='[{"origin": "https://parrot.example.com", "rp_id": "parrot.example.com", "rp_name": "AI-Parrot"}, {"origin": "http://localhost:5000", "rp_id": "localhost", "rp_name": "AI-Parrot (dev)"}, {"origin": "http://localhost:5173", "rp_id": "localhost", "rp_name": "AI-Parrot (vite dev)"}]'
PASSKEY_USER_VERIFICATION=required
PASSKEY_CHALLENGE_TTL=300
PASSKEY_DECOY_CREDENTIALS=1
# Leave 0 behind a reverse proxy (it keys on the socket address); rate-limit login/options at the proxy.
PASSKEY_LOGIN_OPTIONS_RATE=0
```

### `packages/ai-parrot-server/tests/test_passkey_settings_example.py` (CREATE)
```python
"""FEAT-772: the documented passkey settings example is accepted by navigator-auth as-is."""
from __future__ import annotations

import json
from pathlib import Path

from navigator_auth.passkey.rp import RelyingPartyResolver

EXAMPLE = Path(__file__).resolve().parents[3] / "docs" / "examples" / "passkey.settings.example"


def _settings() -> dict[str, str]:
    """Parse KEY=value lines (``#`` comments skipped, one level of single quotes stripped)."""
    out: dict[str, str] = {}
    for raw in EXAMPLE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().removeprefix("'").removesuffix("'")
    return out


def test_relying_parties_pass_navigator_auth_validation() -> None:
    """RelyingPartyResolver raises ConfigError on a bad rp_id / duplicate origin / empty list."""
    parties = json.loads(_settings()["PASSKEY_RELYING_PARTIES"])
    RelyingPartyResolver(parties)
    assert "http://localhost:5173" in {p["origin"] for p in parties}


def test_backends_enable_passkey_next_to_basic() -> None:
    backends = _settings()["AUTHENTICATION_BACKENDS"].split(",")
    assert backends == ["navigator_auth.backends.BasicAuth", "navigator_auth.backends.PasskeyAuth"]
    # FILL IN: PASSKEY_USER_VERIFICATION ∈ {"required","preferred","discouraged"} (conf.py:611 + backend check)
```

### `docs/admin-ui.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c -e '- Login: `POST /api/v1/login` with a `BasicAuth` username/password form.' docs/admin-ui.md; :44)
     AFTER the 3-line bullet that starts there, add: -->
- Passkeys (FEAT-772): with navigator-auth's `PasskeyAuth` enabled, the login page offers
  "Sign in with a passkey" plus passkey autofill, and **Account** (`/account/security`) lets each
  user add, rename and delete passkeys. The passkey ceremony calls skip the 401 interceptor, so a
  failed passkey attempt never clears your session or `?next=`.

<!-- occurrences: 1 (verified: grep -c -e '- **Login**: set `AUTHENTICATION_BACKENDS=navigator_auth.backends.BasicAuth`' docs/admin-ui.md; :221)
     AFTER that bullet's 2 lines, add a "- **Passkeys**:" bullet that FILLS IN, in prose + a fenced block copied from
     docs/examples/passkey.settings.example (link it):
       · install: pip install "ai-parrot-server[passkey]" (pulls navigator-auth[passkey]>=0.28.9 → webauthn)
       · AUTHENTICATION_BACKENDS with PasskeyAuth; PASSKEY_RELYING_PARTIES JSON (one exact origin per entry; rp_id = host or parent)
       · pnpm dev: add http://localhost:5173 — the Vite proxy rewrites Host, not Origin; a passkey enrolled on :5173 is not offered on :5000
       · Redis >= 6.2 (GETDEL); AUTH_SECRET_KEY still mandatory for multi-worker tokens
       · startup failures: ConfigError when PASSKEY_RELYING_PARTIES is empty/invalid or `webauthn` is missing
       · PASSKEY_LOGIN_OPTIONS_RATE=0 behind a proxy -->
```

### FILL IN checklist
- [ ] `docs/admin-ui.md` Quick start "Passkeys" bullet — the six points above; bounded by AC11
- [ ] `test_passkey_settings_example.py` user-verification assertion

---

## Acceptance Criteria

- [ ] `docs/examples/passkey.settings.example` exists, is tracked, and passes `RelyingPartyResolver` (AC11)
- [ ] `docs/admin-ui.md` documents install, backends, RP JSON incl. `:5173`, Redis ≥ 6.2, `AUTH_SECRET_KEY`, `ConfigError` modes, rate-limit guidance, and links the example (AC11)

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/test_passkey_settings_example.py -q`

---

## Test Specification

See the test blueprint block above.

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
   `feat(passkey-support): TASK-4906 — <title>`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4906 passkey-support verified`
   — never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note


- Task: TASK-4906
- Feature: passkey-support
- Implementation SHA: 437774daffad9435c14ec35bd01dcc0a02b856d3
- Closed at (UTC): 2026-10-30T15:42:25+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: mistral · Backend: nova · Model: mistral.devstral-2-123b · Attempts: 1 · Duration: 86s · Tokens: n/a |
