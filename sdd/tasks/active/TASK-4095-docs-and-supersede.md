# TASK-4095: Docs: global install path, portable config note; stamp FEAT-583 superseded

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4076, TASK-4080, TASK-4082, TASK-4083, TASK-4084, TASK-4091
**Assigned-to**: unassigned

---

## Context

Closes spec §5's last two bullets: "`sdd/specs/portable-sdd-flow.spec.md` is stamped
`Status: superseded` referencing FEAT-633" and "docs updated (`INSTALL.md`, `docs/INSTALL.md`, …)".
By the time this runs, every documented behavior exists: the `--global`/`-Global` bootstrap and its
published checksum (TASK-4074/4075/4076), `parrot self add|env|doctor|update|uninstall`
(TASK-4080), `--portable` on the three host installers (TASK-4082/4083/4084) and
`parrot sdd install|uninstall|status` (TASK-4091). This task writes one user-facing page
(`docs/install/global-runtime.md`), links it from both install guides, adds a doc-claim test that
keeps every cited `parrot …` command/flag honest against the real click CLI, and stamps FEAT-583's
spec superseded (FEAT-583's satellite/`sdd`-binary design was rejected — spec Non-Goals).

---

## Scope

- Create `docs/install/global-runtime.md` covering: install commands (raw GitHub URL +
  `SHA256SUMS` verification, POSIX and PowerShell), what lands in `~/.parrot` (and what is never
  touched), `parrot self add|env|doctor|update|uninstall`, the launcher resolution order,
  `--portable` per host and its stickiness rule, `parrot sdd install`, Windows notes, and the wiki
  store version-skew gate message + fix.
- Add a "Quick global install" section + TOC entry to `INSTALL.md`, linking the new page.
- Add a "Global install (managed runtime)" section to `docs/INSTALL.md`, and correct its stale
  prerequisite line (`Python 3.10–3.12` → `Python 3.11–3.13`, matching `requires-python`).
- In `sdd/specs/portable-sdd-flow.spec.md`, change ONLY the status: the `**Status**:` line and the
  frontmatter `status:` field → `superseded`, the bold line pointing at FEAT-633.
- Create `packages/ai-parrot/tests/docs/test_global_runtime_docs.py`: every `parrot <group> <cmd>`
  invocation and `--flag` cited in the new page resolves in the click CLI; the page cites the raw
  URL and `SHA256SUMS`; FEAT-583 is stamped superseded.

**NOT in scope**:
- `.mcp.json.example` is deliberately NOT changed — monorepo developers keep the FEAT-495
  resolver form; the portable form only works once the global install puts `wikitoolkit` on PATH.
  The page explains this instead (spec §5 mentions a ".mcp.json.example note"; the note lives in
  the new page, not in the example file).
- `mkdocs.yml` navigation (not in this task's file list — the page is reachable via links; report
  if `mkdocs build --strict` complains).
- Any behavior change; README edits; any other line of `portable-sdd-flow.spec.md`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `INSTALL.md` | MODIFY | "Quick global install" section + TOC entry linking the new page |
| `docs/INSTALL.md` | MODIFY | "Global install (managed runtime)" section; fix stale Python range |
| `docs/install/global-runtime.md` | CREATE | managed-runtime user guide |
| `sdd/specs/portable-sdd-flow.spec.md` | MODIFY | status → superseded (FEAT-633) |
| `packages/ai-parrot/tests/docs/test_global_runtime_docs.py` | CREATE | doc-claim test against the click CLI |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import click                                   # core dep; used at packages/ai-parrot/src/parrot/cli/__init__.py:16
from parrot.cli import cli                     # verified: packages/ai-parrot/src/parrot/cli/__init__.py:103-104
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):                              # line 19
    def list_commands(self, ctx): ...                      # line 37 — sorted(_lazy_commands)
    def get_command(self, ctx, cmd_name): ...              # line 71 — imports module, returns
        # getattr(mod, cmd_name.replace("-", "_")) or getattr(mod, cmd_name)   (line 99-100)
@click.group(cls=LazyGroup)
def cli(): ...                                             # line 103-104
cli._lazy_commands = {...}                                 # line 109 — "claude" :120, "codex" :121,
                                                           #   "google" :122, "gemini" :123, "toolkits" :117
# After TASK-4080 / TASK-4091: "self" -> parrot.self_.cli, "sdd" -> parrot.sdd.cli
```
```python
# Host CLI groups (each has an `install` subcommand; --portable added by TASK-4082/4083/4084)
@click.group(name="claude") def claude()   # packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py:49-50
@click.group(name="codex")  def codex()    # packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py:37-38
@click.group(name="google") def google()   # packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py:37-38
gemini = google                            # packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py:137
```
```python
# packages/ai-parrot/tests/docs/test_getting_started_claims.py — style to follow
REPO_ROOT = Path(__file__).resolve().parents[4]            # line 20
def extract_claims(path: Path) -> list[DocClaim]:          # line 40 — line-numbered extraction, loud failures
```
- Doc targets: `INSTALL.md` TOC line `- [Python Environment Setup](#python-environment-setup)` (:9),
  heading `## Python Environment Setup` (:158); `docs/INSTALL.md` `[Back to README](../README.md)` (:3),
  `- Python 3.10–3.12` (:8), `## Install with uv (recommended)` (:20).
- `sdd/specs/portable-sdd-flow.spec.md`: frontmatter `status: draft` (:8), `**Status**: draft` (:17).
- Raw URL base: `https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install/`
  (repo `phenobarbital/ai-parrot`, verified from `docs/INSTALL.md:16` clone URL); checksum file
  `scripts/install/SHA256SUMS` (TASK-4076).
- Launcher resolution order (spec §2/§5): `PARROT_VENV` → project venv (worktree `.venv` first, then
  main checkout) → `VIRTUAL_ENV` → managed; warn once per session on stderr.
- `--portable` stickiness (brief cross-cutting decision): `parrot toolkits` re-emits a host's toolkit
  entries in portable form iff that host's current managed `wikitoolkit` entry is portable.
- Store gate: `WikiStoreVersionError` (TASK-4092) — message names both versions and the fix
  (`parrot self update` / `parrot self add --here`).

### Does NOT Exist
- ~~`docs/install/`~~ — directory is new (created with the page).
- ~~a `parrot status` self-diagnostic~~ — `status` is agentd's daemon status; diagnostics are `parrot self doctor`.
- ~~`parrot env` / `parrot doctor` top-level commands~~ — they are `parrot self env` / `parrot self doctor`.
- ~~an `sdd` console script / `ai-parrot-sdd` package~~ — rejected FEAT-583 design; never document them.
- ~~a root-level `install.sh` / `install.ps1`~~ — scripts live in `scripts/install/`.
- ~~`--portable` as default~~ — default emission stays baked absolute paths (spec Non-Goals).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "INSTALL.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/INSTALL.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/install/global-runtime.md",
      "action": "CREATE"
    },
    {
      "path": "sdd/specs/portable-sdd-flow.spec.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/docs/test_global_runtime_docs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup",
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup.get_command",
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#cli",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py#claude",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py#codex",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py#google",
    "sym:packages/ai-parrot/tests/docs/test_getting_started_claims.py#extract_claims"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# test_getting_started_claims.py: parse the doc once, keep 1-based line numbers, and make every
# failure message name "<file>:<line>" plus the offending claim.
assert c.value in scripts, f"{c.source}:{c.line} unknown script '{c.value}'"
```

### Key Constraints
- Write the page from the CODE as merged (run `parrot self --help`, `parrot sdd --help`,
  `parrot claude install --help`, …) — *why*: the test fails on any flag the CLI does not register.
- Every command example lives in a fenced ```bash / ```powershell block, one command per line,
  starting with `parrot ` (no `$ ` prompt) — *why*: that is what the test extracts.
- Quote the store-gate message only as the code emits it (TASK-4092) — FILL IN the exact text.
- Keep `INSTALL.md` / `docs/INSTALL.md` edits additive and short; the detail lives in one page.
- `LazyGroup.get_command` resolves `getattr(module, "self")` / `getattr(module, "sdd")`, so the
  test exercises the real lazy registration of TASK-4080 / TASK-4091.
- Importing the host CLI modules may need navconfig's `env/` scaffold — CI's `install-guide` job
  already creates it (`ci.yml` "Scaffold NavConfig environment").

### References in Codebase
- `packages/ai-parrot/tests/docs/test_getting_started_claims.py` — doc-claim test style.
- `scripts/install/SHA256SUMS`, `scripts/install/install-parrot.{sh,ps1}` — what the page documents.

---

## Implementation Blueprint

### Steps (in order)
1. Collect the real command surface from `--help` output of the merged CLI — *why*: docs must not
   invent flags.
2. Write `docs/install/global-runtime.md` — *why*: single detailed page.
3. Link it from `INSTALL.md` and `docs/INSTALL.md`; fix the stale Python range — *why*: discoverability.
4. Stamp `portable-sdd-flow.spec.md` superseded — *why*: spec §5 AC.
5. Write the doc-claim test and run it — *why*: keep the page honest as the CLI evolves.

### `docs/install/global-runtime.md` (CREATE)
```markdown
# Global install: the parrot-managed runtime

`--global` installs AI-Parrot once per machine under `~/.parrot` (or `$PARROT_HOME`): a pinned
`uv`, a uv-managed Python 3.12, `~/.parrot/venv`, and `parrot` / `wikitoolkit` / `bookstore` on PATH.
Your existing `~/.parrot` data (wikis.json, library/, skills/, brains/, parrot.db) is never touched;
the installer only adds `bin/`, `venv/` and `python/`, and a failed run removes only what it created.

### Install (Linux / macOS)

    ```bash
    curl -fsSLO https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install/install-parrot.sh
    curl -fsSLO https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install/SHA256SUMS
    sha256sum -c --ignore-missing SHA256SUMS   # macOS: shasum -a 256 -c --ignore-missing SHA256SUMS
    bash install-parrot.sh --global --with sdd
    ```

### Install (Windows, PowerShell)
<!-- FILL IN: Invoke-WebRequest both files; compare (Get-FileHash install-parrot.ps1).Hash with the
     SHA256SUMS line; then `powershell -ExecutionPolicy Bypass -File install-parrot.ps1 -Global -With sdd`.
     Note: user PATH is edited (never Machine) — reopen the terminal. — bounded by TASK-4075 -->

Flags: `--version <X>` pins ai-parrot, `--python 3.12` (default) picks the managed Python,
`--with a,b` runs `parrot self add` per component, `--dry-run` prints the plan only.

### Managing the runtime

    ```bash
    parrot self env
    parrot self doctor
    parrot self add scraping
    parrot self add scraping --here
    parrot self update
    parrot self uninstall --yes
    ```
<!-- FILL IN: one sentence per command from the merged --help; `--here` is the ONLY way a
     dependency enters a project venv — bounded by TASK-4080 -->

### Which venv runs? (launcher resolution)
From the managed venv, `parrot`/`wikitoolkit`/`bookstore` re-exec into, in order: `PARROT_VENV`;
the project venv (a worktree's own `.venv` first, then the main checkout's); `VIRTUAL_ENV`; else
the managed venv. A project `.venv` without the command is skipped with one stderr warning per
session. Outside the managed venv nothing changes.

### Committable host config: `--portable`

    ```bash
    parrot claude install --portable
    parrot codex install --portable
    parrot google install --portable
    ```
<!-- FILL IN: per-host field contract (bare commands, relative --config, PARROT_PROJECT where the
     host's cwd is unreliable — per TASK-4082/4083/4084); stickiness: `parrot toolkits` keeps a
     host portable iff its wikitoolkit entry already is; default stays absolute paths. Explain that
     `.mcp.json.example` keeps the FEAT-495 resolver form for monorepo developers on purpose. -->

### The SDD flow in any repository

    ```bash
    parrot sdd install --host claude
    parrot sdd status
    parrot sdd uninstall
    ```
<!-- FILL IN: helpers run as `python -m parrot.sdd.scripts.<name>`; conflict rule (identical → skip,
     differs → skip+warn unless --force) — bounded by TASK-4091 -->

### Version skew
<!-- FILL IN: quote WikiStoreVersionError's message as emitted (TASK-4092) and the fix
     (`parrot self update`, or `parrot self add --here` for a project venv); note that runtimes
     older than this release have no gate. -->
```
**Why this shape**: one page owns the managed-runtime story. Rendering conventions of THIS task
file: the inner code fences are indented only to nest inside the block, and every heading inside
the Markdown blocks of this blueprint (here and in the two INSTALL blocks below) is shown one
level deeper (`###`) so SDD task parsers that split on `^## ` are not confused — write them as
normal top-level fences and `##` headings in the real files.

### `INSTALL.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '- [Python Environment Setup](#python-environment-setup)' INSTALL.md) -->
<!-- REPLACE — `- [Python Environment Setup](#python-environment-setup)` (verified: INSTALL.md:9) with: -->
- [Quick global install](#quick-global-install)
- [Python Environment Setup](#python-environment-setup)

<!-- occurrences: 1 (verified: grep -cF '## Python Environment Setup' INSTALL.md) -->
<!-- REPLACE — `## Python Environment Setup` (verified: INSTALL.md:158) with: -->
### Quick global install

Want `parrot`, `wikitoolkit` and `bookstore` for your coding assistant without a project venv?
`scripts/install/install-parrot.sh --global` (or `install-parrot.ps1 -Global`) installs a managed
runtime under `~/.parrot` — verified download, pinned uv, Python 3.12. See
[docs/install/global-runtime.md](docs/install/global-runtime.md).

---

### Python Environment Setup
```

### `docs/INSTALL.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '- Python 3.10–3.12' docs/INSTALL.md) -->
<!-- REPLACE — `- Python 3.10–3.12` (verified: docs/INSTALL.md:8) with: -->
- Python 3.11–3.13

<!-- occurrences: 1 (verified: grep -cF '## Install with uv (recommended)' docs/INSTALL.md) -->
<!-- REPLACE — `## Install with uv (recommended)` (verified: docs/INSTALL.md:20) with: -->
### Global install (managed runtime)
No Python needed up front: `bash scripts/install/install-parrot.sh --global` (Windows:
`install-parrot.ps1 -Global`) installs pinned uv + Python 3.12 + ai-parrot under `~/.parrot`.
Details, checksum verification and `parrot self …`: [install/global-runtime.md](install/global-runtime.md).

### Install with uv (recommended)
```

### `sdd/specs/portable-sdd-flow.spec.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^status: draft$' sdd/specs/portable-sdd-flow.spec.md) -->
<!-- REPLACE — frontmatter `status: draft` (verified: sdd/specs/portable-sdd-flow.spec.md:8) with: -->
status: superseded
<!-- occurrences: 1 (verified: grep -c '^\*\*Status\*\*: draft$' sdd/specs/portable-sdd-flow.spec.md) -->
<!-- REPLACE — `**Status**: draft` (verified: sdd/specs/portable-sdd-flow.spec.md:17) with: -->
**Status**: superseded — by FEAT-633 (`sdd/specs/parrot-installer.spec.md`, parrot-installer); this design was rejected.
```
**Why**: spec §5 AC; touch nothing else in that file (its line 630 prose stays as history).

### `packages/ai-parrot/tests/docs/test_global_runtime_docs.py` (CREATE)
```python
"""Doc-claim checks for docs/install/global-runtime.md (FEAT-633, TASK-4095)."""

from __future__ import annotations

import re
from pathlib import Path

import click
import pytest

from parrot.cli import cli

REPO_ROOT = Path(__file__).resolve().parents[4]
PAGE = REPO_ROOT / "docs" / "install" / "global-runtime.md"
SUPERSEDED_SPEC = REPO_ROOT / "sdd" / "specs" / "portable-sdd-flow.spec.md"
CMD_RE = re.compile(r"^\s*parrot\s+(?P<group>[\w-]+)\s+(?P<sub>[\w-]+)(?P<rest>.*)$")
FLAG_RE = re.compile(r"(?<!\S)(--[\w-]+)")


def _cited_commands(path: Path) -> list[tuple[int, str, str, list[str]]]:
    """Return (line, group, subcommand, flags) for every `parrot <group> <sub>` line in a fence."""
    found: list[tuple[int, str, str, list[str]]] = []
    in_fence = False
    for i, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if text.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        m = CMD_RE.match(text) if in_fence else None
        if m:
            rest = m["rest"].split("#", 1)[0]
            found.append((i, m["group"], m["sub"], FLAG_RE.findall(rest)))
    return found


def _resolve(group: str, sub: str) -> click.Command | None:
    """Resolve `parrot <group> <sub>` through the real lazy CLI."""
    ctx = click.Context(cli)
    grp = cli.get_command(ctx, group)
    if not isinstance(grp, click.Group):
        return None
    return grp.get_command(click.Context(grp, parent=ctx), sub)


def test_page_cites_commands() -> None:
    """The page exists and cites at least the self/sdd/portable commands."""
    groups = {g for _, g, _, _ in _cited_commands(PAGE)}
    assert {"self", "sdd", "claude", "codex", "google"} <= groups


@pytest.mark.parametrize("line,group,sub,flags", _cited_commands(PAGE) if PAGE.is_file() else [])
def test_cited_command_and_flags_exist(line: int, group: str, sub: str, flags: list[str]) -> None:
    """Every cited command is registered and every cited flag is one of its options."""
    cmd = _resolve(group, sub)
    assert cmd is not None, f"{PAGE}:{line} unknown command 'parrot {group} {sub}'"
    opts = {o for p in cmd.params for o in (*p.opts, *p.secondary_opts)}
    for flag in flags:
        assert flag in opts, f"{PAGE}:{line} 'parrot {group} {sub}' has no option {flag}"


def test_page_documents_verified_download() -> None:
    """The install section uses the raw GitHub URL and the committed SHA256SUMS."""
    text = PAGE.read_text(encoding="utf-8")
    assert "raw.githubusercontent.com/phenobarbital/ai-parrot/" in text
    assert "SHA256SUMS" in text


def test_feat_583_spec_superseded() -> None:
    """portable-sdd-flow.spec.md is stamped superseded and points at FEAT-633."""
    text = SUPERSEDED_SPEC.read_text(encoding="utf-8")
    assert re.search(r"^\*\*Status\*\*: superseded.*FEAT-633", text, re.MULTILINE)
```
**Why**: mirrors `test_getting_started_claims.py` (file:line in every failure) but checks against
the live click tree, so a renamed flag in TASK-4080/4082-4084/4091 breaks this test, not users.

### FILL IN checklist
- [ ] `global-runtime.md` Windows section — exact PowerShell download/verify/run lines; bounded by TASK-4075.
- [ ] `global-runtime.md` `parrot self …` descriptions and real flag names (e.g. `uninstall --yes`, `update --version`); bounded by TASK-4080 `--help`.
- [ ] `global-runtime.md` `--portable` per-host field contract + stickiness + `.mcp.json.example` rationale; bounded by TASK-4082/4083/4084.
- [ ] `global-runtime.md` `parrot sdd` conflict rule; bounded by TASK-4091.
- [ ] `global-runtime.md` version-skew message text; bounded by TASK-4092's `WikiStoreVersionError`.

---

## Acceptance Criteria

- [ ] `docs/install/global-runtime.md` documents: raw-URL install + `SHA256SUMS` verification (POSIX
      and PowerShell), `parrot self add|env|doctor|update|uninstall`, launcher resolution order,
      `--portable` per host with the stickiness rule, `parrot sdd install`, Windows notes, and the
      version-skew gate message + fix.
- [ ] `INSTALL.md` and `docs/INSTALL.md` link the page; `docs/INSTALL.md` states Python 3.11–3.13.
- [ ] `sdd/specs/portable-sdd-flow.spec.md` reads `**Status**: superseded` referencing FEAT-633
      (and `status: superseded` in frontmatter); no other line changed (spec §5 AC).
- [ ] `.mcp.json.example` is unchanged (deliberate; rationale in the page).
- [ ] `test_global_runtime_docs.py` passes: every cited `parrot <group> <sub> --flag` is registered.
- [ ] `test_getting_started_claims.py` still passes.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/docs/test_global_runtime_docs.py -q`
- `pytest packages/ai-parrot/tests/docs/test_getting_started_claims.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/docs/test_global_runtime_docs.py — see blueprint (whole file)
def test_page_cites_commands(): ...
def test_cited_command_and_flags_exist(line, group, sub, flags): ...   # parametrized per cited line
def test_page_documents_verified_download(): ...
def test_feat_583_spec_superseded(): ...
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4095 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
