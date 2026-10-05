# TASK-4076: Bootstrap CI wiring: --global dry-run legs + committed SHA256SUMS

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4074, TASK-4075
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 + §5 bootstrap AC ("CI dry-run legs cover the new mode; the documented install
command is a raw GitHub URL with a published checksum"). Distribution decision (spec §2 / §8
"Distribution — raw GitHub URL + published checksum"): users fetch
`scripts/install/install-parrot.{sh,ps1}` from `raw.githubusercontent.com` and verify them against
a **committed** `scripts/install/SHA256SUMS`. This task wires the `--global` / `-Global` dry runs
into the existing FEAT-586 `install-guide` CI job, commits the checksum file, and makes CI fail
when the scripts change without the checksums being regenerated.

---

## Scope

- Add to `.github/workflows/ci.yml` job `install-guide`:
  - a POSIX `--global --dry-run` leg;
  - a soft PowerShell `-Global -DryRun` leg (runs only when `pwsh` is present, same soft pattern
    as the existing parse step);
  - a step verifying `scripts/install/SHA256SUMS` (`cd scripts/install && sha256sum -c SHA256SUMS`).
- Create `scripts/install/SHA256SUMS` in `sha256sum` format for `install-parrot.sh` and
  `install-parrot.ps1`, generated with:
  `cd scripts/install && sha256sum install-parrot.sh install-parrot.ps1 > SHA256SUMS`
  (document this regeneration command in a comment in the CI step and in the Completion Note).
- Extend `packages/ai-parrot/tests/docs/test_ci_install_wiring.py`: assert the new CI legs exist
  and that `SHA256SUMS` matches the current bytes of both scripts.

**NOT in scope**:
- The scripts themselves (TASK-4074 / TASK-4075) — if a dry run fails, fix it there, not here.
- Docs that publish the URL + checksum (TASK-4095).
- Release-time workflow changes (`release.yml`, TASK-4094); an OS matrix for `install-guide`
  (FEAT-586 AC13 keeps it single-OS ubuntu).
- `.gitattributes` / line-ending policy (see Implementation Notes; report if it bites).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/ci.yml` | MODIFY | `--global --dry-run` POSIX leg, soft pwsh `-Global -DryRun` leg, SHA256SUMS check |
| `scripts/install/SHA256SUMS` | CREATE | committed sha256 of both installer scripts |
| `packages/ai-parrot/tests/docs/test_ci_install_wiring.py` | MODIFY | assert new CI legs + checksum file matches the scripts |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pathlib import Path     # verified: packages/ai-parrot/tests/docs/test_ci_install_wiring.py:5
import hashlib               # stdlib (new import in the test file)
```

### Existing Signatures to Use
```yaml
# .github/workflows/ci.yml
  install-guide:                                   # line 113 (runs-on: ubuntu-latest, line 115)
      - name: Doc-claim & script tests             # line 136 — runs `uv run pytest packages/ai-parrot/tests/docs/ -q`
      - name: POSIX installer syntax               # line 139
      - name: PowerShell installer parse (soft)    # line 142 — `if command -v pwsh ...; else echo ...; fi`
      - name: POSIX installer dry run              # line 154
        run: bash scripts/install/install-parrot.sh --dry-run --provider anthropic   # line 155
  test-core:                                       # line 157 (next job — insert above it)
```
```python
# packages/ai-parrot/tests/docs/test_ci_install_wiring.py  (verified path: tests/docs/, not tests/)
REPO_ROOT = Path(__file__).resolve().parents[4]          # line 7
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"      # line 8
def test_ci_runs_doc_and_script_checks() -> None:        # line 11 — asserts "--dry-run" etc. in CI text
```
- Script flags this task exercises (delivered by dependencies): `install-parrot.sh --global
  --dry-run` (TASK-4074), `install-parrot.ps1 -Global -DryRun` (TASK-4075).

### Does NOT Exist
- ~~`scripts/install/SHA256SUMS`~~ — new here (only `install-parrot.sh` and `install-parrot.ps1` exist in `scripts/install/`).
- ~~`packages/ai-parrot/tests/test_ci_install_wiring.py`~~ — the file lives in `packages/ai-parrot/tests/docs/`.
- ~~a CI checksum or `--global` step~~ — none today.
- ~~`pwsh` guaranteed on `ubuntu-latest`~~ — treat it as optional (soft step), as the existing parse step does.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".github/workflows/ci.yml",
      "action": "MODIFY"
    },
    {
      "path": "scripts/install/SHA256SUMS",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/docs/test_ci_install_wiring.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/docs/test_ci_install_wiring.py#test_ci_runs_doc_and_script_checks"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```yaml
# ci.yml:142-153 — soft pwsh step: run when available, otherwise echo a skip notice and succeed.
      - name: PowerShell installer parse (soft)
        run: |
          if command -v pwsh >/dev/null 2>&1; then
            pwsh -NoProfile -Command '...'
          else
            echo "pwsh not available on this runner; skipping ..."
          fi
```

### Key Constraints
- The global dry-run legs must set a sandboxed `PARROT_HOME` (e.g. `"$RUNNER_TEMP/parrot-home"`)
  — *why*: the dry run must not depend on, or announce paths in, the runner's real `~/.parrot`.
- Generate `SHA256SUMS` LAST, after TASK-4074/4075 are merged into the worktree — *why*: any later
  byte change to either script invalidates it, and the test will fail by design.
- Line endings: the checksum is over the repo bytes that `raw.githubusercontent.com` serves (LF as
  committed). A Windows checkout with `core.autocrlf=true` would compute a different hash locally;
  CI runs on ubuntu, so this is a contributor-side concern only — note it in the CI comment.
- `sha256sum -c` output format: two spaces between hash and filename (text mode) — produce the file
  with `sha256sum`, never by hand.
- Keep the existing `--dry-run --provider anthropic` leg (project mode) — it guards FEAT-586.

### References in Codebase
- `.github/workflows/ci.yml:113-155` — the `install-guide` job.
- `packages/ai-parrot/tests/docs/test_ci_install_wiring.py` — string-assertion style.

---

## Implementation Blueprint

### Steps (in order)
1. Append the three new steps after the `POSIX installer dry run` step — *why*: same job already
   has Python/uv and runs single-OS (FEAT-586 AC13).
2. Regenerate `scripts/install/SHA256SUMS` with the documented command — *why*: the committed
   checksum is the published integrity anchor (spec §2 distribution).
3. Extend the wiring test — *why*: CI silently dropping a leg, or a stale checksum, must fail a test.

### `.github/workflows/ci.yml` (MODIFY)
```yaml
# occurrences: 1 (verified: grep -c '        run: bash scripts/install/install-parrot.sh --dry-run --provider anthropic' .github/workflows/ci.yml)
# AFTER — `        run: bash scripts/install/install-parrot.sh --dry-run --provider anthropic`
#         (verified: .github/workflows/ci.yml:155), i.e. right before the blank line + `  test-core:` (:157)

      # FEAT-633: global (managed-runtime) mode — dry run only; no network, no writes.
      - name: POSIX installer global dry run
        env:
          PARROT_HOME: ${{ runner.temp }}/parrot-home
        run: bash scripts/install/install-parrot.sh --global --dry-run --version 0.0.0 --with sdd

      - name: PowerShell installer global dry run (soft)
        env:
          PARROT_HOME: ${{ runner.temp }}/parrot-home
        run: |
          if command -v pwsh >/dev/null 2>&1; then
            pwsh -NoProfile -File scripts/install/install-parrot.ps1 -Global -DryRun -Version 0.0.0 -With sdd
          else
            echo "pwsh not available on this runner; skipping -Global dry run (single-OS scope)."
          fi

      # FEAT-633: published-checksum gate. After ANY change to either installer, regenerate with:
      #   cd scripts/install && sha256sum install-parrot.sh install-parrot.ps1 > SHA256SUMS
      # (hashes are over the committed LF bytes that raw.githubusercontent.com serves)
      - name: Installer checksums match SHA256SUMS
        working-directory: scripts/install
        run: sha256sum -c SHA256SUMS
```
**Why**: mirrors the existing soft-pwsh idiom; `--version 0.0.0` proves the pin is threaded into
the announced install spec without ever resolving it (dry run).

### `scripts/install/SHA256SUMS` (CREATE)
```text
<sha256-of-install-parrot.sh>  install-parrot.sh
<sha256-of-install-parrot.ps1>  install-parrot.ps1
```
**Why**: do NOT hand-write this file. FILL IN: generate it with
`cd scripts/install && sha256sum install-parrot.sh install-parrot.ps1 > SHA256SUMS` after the
TASK-4074/4075 scripts are final in the worktree — bounded by `test_sha256sums_match_scripts`.

### `packages/ai-parrot/tests/docs/test_ci_install_wiring.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from pathlib import Path' packages/ai-parrot/tests/docs/test_ci_install_wiring.py)
# REPLACE — `from pathlib import Path` (verified: packages/ai-parrot/tests/docs/test_ci_install_wiring.py:5) with:
import hashlib
from pathlib import Path

# occurrences: 1 (verified: grep -c 'CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"' packages/ai-parrot/tests/docs/test_ci_install_wiring.py)
# AFTER — `CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"` (verified: :8)
INSTALL_DIR = REPO_ROOT / "scripts" / "install"

# AFTER — end of file (after test_ci_runs_doc_and_script_checks, :11-17); append:


def test_ci_runs_global_dry_runs_and_checksum_gate() -> None:
    """ci.yml dry-runs --global / -Global and verifies SHA256SUMS (FEAT-633)."""
    text = CI.read_text(encoding="utf-8")
    assert "install-parrot.sh --global --dry-run" in text
    assert "install-parrot.ps1 -Global -DryRun" in text
    assert "sha256sum -c SHA256SUMS" in text


def test_sha256sums_match_scripts() -> None:
    """The committed SHA256SUMS covers both installers and matches their current bytes."""
    sums = INSTALL_DIR / "SHA256SUMS"
    assert sums.is_file(), "scripts/install/SHA256SUMS is missing"
    recorded: dict[str, str] = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        recorded[name.lstrip("*")] = digest
    assert set(recorded) == {"install-parrot.sh", "install-parrot.ps1"}
    for name, digest in recorded.items():
        actual = hashlib.sha256((INSTALL_DIR / name).read_bytes()).hexdigest()
        assert actual == digest, (
            f"{name} changed without regenerating SHA256SUMS — run: "
            "cd scripts/install && sha256sum install-parrot.sh install-parrot.ps1 > SHA256SUMS"
        )
```
**Why**: string-level assertions match the existing test's style; the checksum test gives a
local, actionable failure before CI's `sha256sum -c` does.

### FILL IN checklist
- [ ] `scripts/install/SHA256SUMS` — generate with the documented command after TASK-4074/4075 land; bounded by `test_sha256sums_match_scripts`.
- [ ] Confirm the pwsh dry-run leg passes on a runner that has pwsh (or stays a no-op skip); bounded by TASK-4075's dry-run contract.

---

## Acceptance Criteria

- [ ] `install-guide` runs `install-parrot.sh --global --dry-run` with a sandboxed `PARROT_HOME`.
- [ ] `install-guide` runs `install-parrot.ps1 -Global -DryRun` when pwsh exists, skips cleanly otherwise.
- [ ] `install-guide` fails when either script's bytes differ from `scripts/install/SHA256SUMS`.
- [ ] `scripts/install/SHA256SUMS` is in `sha256sum` format and covers exactly the two scripts.
- [ ] The existing project-mode dry-run leg is unchanged (FEAT-586).
- [ ] `test_ci_install_wiring.py` passes, including `test_sha256sums_match_scripts`.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/docs/test_ci_install_wiring.py -q`
- `pytest packages/ai-parrot/tests/docs/test_install_posix.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/docs/test_ci_install_wiring.py (additions — see blueprint)
def test_ci_runs_global_dry_runs_and_checksum_gate(): ...   # CI text has both legs + sha256sum -c
def test_sha256sums_match_scripts(): ...                    # SHA256SUMS == hashlib over both scripts
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4076 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
Record the regeneration command: `cd scripts/install && sha256sum install-parrot.sh install-parrot.ps1 > SHA256SUMS`.

**Deviations from spec**: none | describe if any
