# TASK-5358: `docs/sdd/AGY.md` — the Antigravity Adaptation Contract, packaged for google and codex

**Feature**: FEAT-847 — SDD Antigravity CLI (AGY) Operational Compatibility
**Spec**: `sdd/specs/sdd-agy-compatibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5355
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, item 1 (and the "Official install only" pattern in §7). The shared `.agents/skills/sdd-*`
skills (used by Codex **and** agy) only point at `docs/sdd/CODEX.md`. This task writes `docs/sdd/AGY.md` and
ships it; TASK-5359 then links it from the skill headers.

**Packaging decision.** `docs/sdd/CODEX.md` ships through `PACKAGED_ONLY` in `scripts/sdd/check_asset_sync.py`
(`("docs/sdd/CODEX.md", "sdd/CODEX.md", ("codex", "google"))`): the `_assets/sdd/CODEX.md` file is the source of
truth and `docs/` is not in `PREFIX_MAP`. Follow the same pattern for `AGY.md`, with hosts **`("codex", "google")`**,
not google only — because the skill files are shared by both hosts and
`test_installer.py::test_non_claude_host_skills_have_every_file_they_read` requires a codex-only install to ship
every file a skill links. Keep `docs/sdd/AGY.md` byte-identical to `_assets/sdd/AGY.md` (a test enforces it).
`pyproject.toml`'s explicit `"parrot.sdd"` package-data list needs `"_assets/sdd/AGY.md"`
(`test_package_data_covers_every_manifest_entry`).

---

## Scope

- Write `docs/sdd/AGY.md` (contents below) and its identical packaged copy `_assets/sdd/AGY.md`.
- Register it: `PACKAGED_ONLY` entry + package-data pattern; regenerate `manifest.json` with
  `python scripts/sdd/check_asset_sync.py --write --root .`.
- Tests in `test_installer.py`: Google (and Codex) installs ship it; repo and packaged copies identical; required
  contract sections present; representative worktree examples run in two fresh shells.

**NOT in scope**: skill headers (TASK-5359); the wiki page (TASK-5360).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/sdd/AGY.md` | CREATE | Antigravity Adaptation Contract |
| `packages/ai-parrot/src/parrot/sdd/_assets/sdd/AGY.md` | CREATE | packaged copy (source of truth for the wheel) |
| `scripts/sdd/check_asset_sync.py` | MODIFY | `PACKAGED_ONLY` entry |
| `packages/ai-parrot/pyproject.toml` | MODIFY | package-data `"_assets/sdd/AGY.md"` |
| `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` | MODIFY | regenerated |
| `packages/ai-parrot/tests/sdd/test_installer.py` | MODIFY | ship/identity/sections/fresh-shell tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ae3b48c7f3` (2026-11-09).

### Verified Imports
```python
# test_installer.py imports today (lines 1-29): json, re, subprocess, Path, pytest, and from parrot.sdd.installer
#   GUARD_HOOK_LINE, RECEIPT_PATH, dangerous_hook_command, guard_hook_command, install_sdd_integration,
#   load_manifest, sdd_status, uninstall_sdd_integration
```

### Existing Signatures to Use
```python
# scripts/sdd/check_asset_sync.py
PACKAGED_ONLY: tuple[tuple[str, str, tuple[str, ...]], ...] = (          # line 51
    ...,
    ("docs/sdd/CODEX.md", "sdd/CODEX.md", ("codex", "google")),          # line 55
)
# --check / --write also run the publication + monorepo gates on PACKAGED_ONLY bytes (find_problems, line 201)
# packages/ai-parrot/pyproject.toml — [tool.setuptools.package-data] "parrot.sdd" list:
#     "_assets/sdd/CODEX.md",                                             # line 1032
# packages/ai-parrot/tests/sdd/test_installer.py
def empty_repo(tmp_path: Path) -> Path:                                   # line 31 fixture (git init, README)
_LINK_RE = re.compile(r"\]\((\.\./[^)#\s]+)")                             # line 471
def test_non_claude_host_skills_have_every_file_they_read(empty_repo, host)   # line 475 — codex AND google
```

### Does NOT Exist
- ~~A `docs/` prefix in `check_asset_sync.PREFIX_MAP`~~ — use `PACKAGED_ONLY`, like CODEX.md.
- ~~A snap backend, vendored `.agents/hooks/*.py`, or a second SDD hook~~ — dropped in spec v0.3; document none of them as supported.
- ~~Hook `allow` as an approval~~; ~~`force_ask` as a block under `--dangerously-skip-permissions`~~ — see the spec §1 table.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/sdd/AGY.md", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/sdd/AGY.md", "action": "CREATE"},
    {"path": "scripts/sdd/check_asset_sync.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/manifest.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_installer.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration"
  ]
}
```

---

## Implementation Notes

### Shipped-content gates (the file is installed into other repositories)
- Never write `packages/…`, `scripts/…` (so do **not** name `scripts/sdd/agy_hook.sh` — say "the repository's hook
  launcher" or `parrot sdd hooks agy-permissions --hook`), `PYTHONPATH=` (write "a PYTHONPATH assignment"),
  `tests/sdd_scripts/`, `CLAUDE.md`, `origin/dev`-style branch literals, or ticket keys other than `FEAT-`/`TASK-`.
- Probe workspace paths from the spec (`~/snap/...`) are evidence, not instructions — leave them out.

### Required sections (spec §3 M5 item 1, §5 AC)
1. `## Antigravity Adaptation Contract` (anchor `#antigravity-adaptation-contract`, linked by TASK-5359):
   tool mapping (`Bash -> run_command`, `Read -> view_file`, `Write/Edit -> write_file/edit_file`,
   `Agent -> invoke_subagent(TypeName, Role, Prompt, Model, Workspace)`, `TaskStop -> manage_subagents(Action="kill")`);
   `subagent_type: "fork" -> TypeName="self"` only (why not `research`); model mapping `haiku -> flash`, every
   other value `-> inherit`, never `pro`/`flash_lite` automatically.
2. Worktree commands across fresh shells: absolute path, or `WT=<abs> && cd "$WT" && …` in one call; `Workspace`
   = the same absolute path; never rely on a previous call's `cd`, variables or activation.
3. Background work is reactive (check status on the next turn; no monitors).
4. Approval semantics: the verified hook-answer table (spec §1); `overwrite` applies with `allow`/`ask` and rules
   match the rewritten command; the worker's unattended mode (`PARROT_SDD_AGY_UNATTENDED=1`: `force_ask -> deny`,
   commands wrapped in Bubblewrap); interactive sessions use the managed allow-rules plus operator approval;
   **only `parrot sdd launch worker <FEAT-ID> --host google` is a supported unattended mode** — a hand-started
   `agy --dangerously-skip-permissions` lets `force_ask` calls through; `--mode auto` is account-gated.
5. Installation: `curl -fsSL https://antigravity.google/cli/install.sh | bash` (`~/.local/bin/agy`, self-updating,
   settings at `~/.gemini/antigravity-cli/settings.json`); the community `antigravity-cli` snap is unsupported
   (no project Python, `bwrap` or `ssh`; `~/.gitconfig` invisible) and every Google launch refuses it.
6. Re-verification: facts verified on agy 1.4.12 and 1.5.3; re-run the hook probes after an update that touches
   hooks or permissions (describe the probe: a logging `PreToolUse` hook answering `deny` for one command).

---

## Implementation Blueprint

### Steps (in order)
1. Write `docs/sdd/AGY.md`, then copy it byte-for-byte to `_assets/sdd/AGY.md` — *why*: PACKAGED_ONLY asset + repo copy.
2. Add the `PACKAGED_ONLY` entry and the package-data pattern — *why*: manifest + wheel coverage tests.
3. Run `python scripts/sdd/check_asset_sync.py --write --root .`, then `--check` — *why*: regenerates `manifest.json` and runs the gates.
4. Write the tests.

### `docs/sdd/AGY.md` (CREATE) — identical bytes in `_assets/sdd/AGY.md`
```markdown
# SDD in Google Antigravity CLI (AGY)

How the SDD skills and agents run under `agy`. Codex uses `docs/sdd/CODEX.md`; Claude Code needs neither.

## Antigravity Adaptation Contract

<!-- FILL IN: sections 1-6 of "Required sections" above, as prose + tables. Include at least two worktree examples,
     each in its own ```bash block preceded by the marker line `<!-- agy-fresh-shell-example -->`, using the
     placeholder path `/abs/path/to/worktree`, e.g.
       WT=/abs/path/to/worktree && cd "$WT" && git rev-parse --show-toplevel
       git -C /abs/path/to/worktree status --short
     — bounded by spec §3 M5 items 1 and 6 and the shipped-content gates. -->
```

### `scripts/sdd/check_asset_sync.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    ("docs/sdd/CODEX.md", "sdd/CODEX.md", ("codex", "google")),' scripts/sdd/check_asset_sync.py) — line 55
# AFTER — insert:
    ("docs/sdd/AGY.md", "sdd/AGY.md", ("codex", "google")),  # FEAT-847 — linked by the shared .agents/skills
```

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '    "_assets/sdd/CODEX.md",' packages/ai-parrot/pyproject.toml) — line 1032
# AFTER — insert:
    "_assets/sdd/AGY.md",
```

### `packages/ai-parrot/tests/sdd/test_installer.py` (MODIFY)
```python
# AFTER — append at end of file
_REPO_ROOT = Path(__file__).resolve().parents[4]
_AGY_DOC = "docs/sdd/AGY.md"


@pytest.mark.parametrize("host", ["google", "codex"])
def test_install_ships_agy_contract(empty_repo: Path, host: str) -> None:
    install_sdd_integration(empty_repo, hosts=(host,))
    text = (empty_repo / _AGY_DOC).read_text(encoding="utf-8")
    assert "## Antigravity Adaptation Contract" in text


def test_agy_contract_repo_copy_matches_package() -> None:
    packaged = _REPO_ROOT / "packages/ai-parrot/src/parrot/sdd/_assets/sdd/AGY.md"
    assert (_REPO_ROOT / _AGY_DOC).read_bytes() == packaged.read_bytes()


# FILL IN tests:
#  - required content present: "invoke_subagent", "manage_subagents", 'TypeName="self"', "flash", "inherit",
#    "PARROT_SDD_AGY_UNATTENDED", "parrot sdd launch worker", "install.sh", "snap"
#  - test_agy_worktree_examples_run_in_fresh_shells: extract every ```bash block preceded by
#    "<!-- agy-fresh-shell-example -->" (>= 2), replace "/abs/path/to/worktree" with a tmp `git init` repo, run each
#    block in its own `bash -c` (cwd = tmp_path, env without WT/VIRTUAL_ENV/OLDPWD), assert exit 0; a block that
#    prints a path must print the worktree's
```

### FILL IN checklist
- [ ] `docs/sdd/AGY.md` content; bounded by spec §3 M5 + shipped-content gates
- [ ] remaining tests

---

## Acceptance Criteria

- [ ] `docs/sdd/AGY.md` documents everything in "Required sections" and passes the asset gates.
- [ ] Google and Codex installs ship it; repo and packaged copies are identical; `check_asset_sync.py --check` exits 0.
- [ ] The worktree examples run in two fresh shells with no inherited `WT`, activation or cwd.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_installer.py -q`
- `pytest tests/sdd_scripts/test_check_asset_sync.py -q`

---

## Test Specification

See the test block in the Implementation Blueprint.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug sdd-agy-compatibility --feature-id FEAT-847`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/sdd-agy-compatibility.json`
4. **Verify the Codebase Contract** before writing any code; fix stale entries first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands (prefix `PYTHONPATH=packages/ai-parrot/src` in a worktree)
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5358 sdd-agy-compatibility verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
