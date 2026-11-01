# TASK-4095: Docs: canonical install guide (getting-started) + global runtime reference, kept true by CI

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4074, TASK-4075, TASK-4076, TASK-4080, TASK-4082, TASK-4083, TASK-4084, TASK-4089, TASK-4091, TASK-4299
**Assigned-to**: unassigned

---

## Context

Closes spec §5's docs bullet ("docs updated (`INSTALL.md`, `docs/INSTALL.md`, …)") as amended by
spec rev 0.2 (C13/C14a): there is ONE canonical, CI-verified install and first-use guide —
FEAT-586's `docs/getting-started.md` — and one reference page for the managed runtime. By the
time this runs, every documented behavior exists: the `--global`/`-Global` bootstrap with its
pre-install gate, plan paragraph and published checksum (TASK-4074/4075/4076),
`parrot self add|env|doctor|update|uninstall` incl. `doctor --sdd` / `--runtime-only`
(TASK-4080), `--portable` on the three host installers (TASK-4082/4083/4084), the shipped
markdown that calls helpers as `parrot sdd run <name>` (TASK-4089) and
`parrot sdd install|uninstall|status|run` with `--dry-run`/`--force`, `sdd/config.json` and the
`sdd/CONVENTIONS.md` seed (TASK-4091 and the C6 task). This task (a) extends `docs/getting-started.md`
with the global path, `parrot self`, `parrot sdd` and a "Use the SDD flow in your repo" section,
every claim carrying a `<!-- verify: … -->` anchor; (b) extends FEAT-586's claim harness
(`test_getting_started_claims.py`) with `cli-verb` and `flag` kinds resolved against the real
click CLI, over both the guide and the reference page; (c) writes the reference page
`docs/install/global-runtime.md`; (d) turns `INSTALL.md` and `docs/INSTALL.md` into short pointers.

---

## Amendments — spec rev 0.2 (2026-10-14)

Folded in from `sdd/proposals/parrot-installer-amendments.proposal.md` (§3 C13, C14a; §5
resolved by Jesus Lara). Every section below already reflects these deltas; this list is the
audit trail.

- **FEAT-583 stamping step dropped.** `sdd/specs/portable-sdd-flow.spec.md` is already
  `status: superseded` / `**Status**: superseded by FEAT-633` (commit `2ed09515e`, verified on
  `dev` 2026-10-14). Nothing in this task touches that file; the H1 lost its "supersede" half
  (file name kept — the index points at it).
- **C13 — one canonical guide.** `docs/getting-started.md` is THE install and first-use guide
  (it is the one FEAT-586 already verifies in CI's `install-guide` job). It gains the `--global`
  path, `parrot self`, `parrot sdd install` (with `--dry-run`, `--force`, `status`, `run`) and
  a "Use the SDD flow in your repo" section. `docs/install/global-runtime.md` holds the reference
  detail; `INSTALL.md` and `docs/INSTALL.md` become short pointers to the guide. The task's
  former `test_global_runtime_docs.py` is MERGED into the claim harness — no second verifier:
  `test_getting_started_claims.py` gains the `cli-verb` and `flag` claim kinds, checked against
  the real click commands through the lazy `parrot.cli:cli`, over both documents.
- **C14a — every install command explained** (FEAT-586 AC8, `sdd/specs/parrot-install-guide.spec.md`
  §5: "every command block is accompanied by an explanation of what it does … and a non-piped
  alternative where one exists"). Each documented install command states what it downloads
  (pinned uv `0.11.28`, the release URL, its `.sha256`; the raw-URL script and `SHA256SUMS`),
  where it writes (`PARROT_HOME/{bin,venv,python}`, the PATH block / user PATH), how it is
  verified, and the non-piped alternative (download, inspect, verify the checksum, run). Covers
  the raw-URL bootstrap AND the pinned-uv download the bootstrap performs.
- **Rev-0.2 behaviours the docs now describe**: helpers run as `parrot sdd run <name>` (Q1);
  the repo config `sdd/config.json` (C6); the `sdd/CONVENTIONS.md` seed (C10);
  `parrot sdd status` states `missing | current | outdated | edited | foreign`, seeds
  `seed-present | missing` (C4/C10; spec :521, TASK-4091); `parrot sdd install
  --dry-run` (C5); `parrot self doctor --sdd` readiness checks and the bootstrap's
  `--runtime-only` scope (C14/C15). Dependencies grew accordingly (TASK-4074/4075 for the gate +
  plan text, TASK-4089 for the `parrot sdd run` form in shipped markdown).

---

## Readiness review — 2026-10-19 (dev 9f51c7735)
- Refreshed against dev 9f51c7735: no commit since `0b92bda42` touches this task's files and every line anchor still holds; `DocClaim` described as the pydantic `BaseModel` it is (`test_getting_started_claims.py:31`); the `parrot sdd status` states now include `foreign` and the seed states `seed-present | missing` (spec :521, TASK-4091).
- Resolved by spec rev 0.5 (2026-10-20):
  - C21 — the guide documents the `test_command` switch. When `sdd/config.json` sets it, shipped
    test steps run it once from the repo root instead of the FEAT-699 selection/report steps, and a
    run with no tests shows "⚠️ not run". When it is null (ai-parrot), the FEAT-699 path applies.
    `parrot sdd install` warns when it is null. A foreign-repo validation phase is v1.1, not documented as available.
  - C20 — the `--global` sections say the managed runtime installs `ai-parrot-tools` alongside
    `ai-parrot` at the same version, needed by `wikitoolkit mcp`.
  - C22 — `/sdd-insight` is not among the installed commands. The seed `sdd/CONVENTIONS.md` has
    `## Repository layout` and `## Project areas`, and `sdd/config.json` may set `projects`.
  - C23 — `parrot sdd install` writes a marked `.gitattributes` block (`merge=union` for the
    ledger log) and installs the four ledger git hooks, and `doctor --sdd` checks both.
  - D2 (→ C21) — document `test_command` exactly as TASK-4089 (a dependency) ships it, and only once
    that has landed: the skipped steps are `cache_test_contract` in `/sdd-task` and `select_tests` /
    `test_report` in `/sdd-done`; when it is unset and the FEAT-699 kernel cannot be loaded, those steps
    stop with a clear message (no traceback). Re-read the shipped `sdd-task` / `sdd-done` text before
    writing the sentence; do not describe more than they say. Spec §4 holds the curated FEAT-633
    Validation Contract (scope map), not a fallback.
  - D5 (→ C23) — the `.gitattributes` block is recorded in `sdd/.sdd-installed.json` and the hooks are
    the `parrot-ledger` ones; the reference page's list of what install writes includes both.
  - D8 (→ C24, corrected 2026-10-20): the gate compares `schema_version` only; `min_runtime_version` is
    stamped but informational (quoted in the error). The version-skew text must say the store refuses only
    a runtime with an older **schema**; a same-schema store opens whatever release wrote it.
  - Counts / anchors re-verified 2026-10-20 on dev `69fb12a41`: every anchor in the Codebase Contract
    holds (`cli/__init__.py:16,19,37,71,99-100,103-104,109,117,120-123`; host CLI groups
    `claude_code/cli.py:49`, `codex/cli.py:37`, `google/cli.py:37,137`; harness
    `:17,20,21,28,31,34,40,59,125,161,183`; guide `:13,84,134,266,272,291,319`; `ci.yml:113,133`;
    `INSTALL.md:9,158`; `docs/INSTALL.md:3,8,16,20`; `parrot-install-guide.spec.md:332-335`). Stale:
    "spec :521" (the status states) → **`:557`** (C4 clause; also `:237`).

## Scope

- Extend `docs/getting-started.md` (canonical guide) with: a "Global install (managed runtime)"
  path next to the existing project-venv path (POSIX + PowerShell one-liners, each with the
  C14a explanation and the non-piped alternative); a "Manage the runtime: `parrot self`"
  section; and a "Use the SDD flow in your repo" section (`parrot sdd install --host … --dry-run`
  then the real install, edit `sdd/config.json`, `parrot self doctor --sdd`, first `/sdd-*`
  command, `parrot sdd status`, upgrades keep edits). Every cited command/flag carries a
  `<!-- verify: cli-verb=… -->` / `<!-- verify: flag=… -->` anchor; the raw URL + `SHA256SUMS`
  are cited.
- Extend `packages/ai-parrot/tests/docs/test_getting_started_claims.py`: add the `cli-verb` and
  `flag` kinds to `DocClaim`, a `_resolve_verb()` that walks the lazy click tree, two tests that
  verify every such claim in BOTH `docs/getting-started.md` and `docs/install/global-runtime.md`,
  a parse test for the two kinds, and a test that each install one-liner in the guide is followed
  by its explanation + non-piped alternative (C14a).
- Create `docs/install/global-runtime.md` (reference detail): what lands in `~/.parrot` (and what
  is never touched), the pre-install gate conditions and the plan paragraph the script prints,
  `parrot self add|env|doctor|update|uninstall` (incl. `doctor --sdd` / `--runtime-only`), the
  launcher resolution order, `--portable` per host and its stickiness rule, `parrot sdd
  install|uninstall|status|run` with the conflict rule, the installed-record states, `--dry-run`,
  the `.gitattributes` ledger block and ledger git hooks (D5) *[rev 0.5]*, `sdd/config.json` fields (incl. the
  D2 `test_command` rule) *[rev 0.5]*, the `sdd/CONVENTIONS.md` seed, Windows notes, and the wiki store
  version-skew gate message + fix. Same claim anchors as the guide.
- Reduce `INSTALL.md` and `docs/INSTALL.md` to short pointers: one paragraph each sending the
  reader to `docs/getting-started.md` (and the reference page), keeping any content that is not
  about installation; correct `docs/INSTALL.md`'s stale prerequisite line
  (`Python 3.10–3.12` → `Python 3.11–3.13`, matching `requires-python`).

**NOT in scope**:
- `sdd/specs/portable-sdd-flow.spec.md` — already stamped superseded (commit `2ed09515e`); do
  not touch it.
- A second doc verifier (`test_global_runtime_docs.py` is NOT created); `mkdocs.yml`.
- `.mcp.json.example` is deliberately NOT changed — monorepo developers keep the FEAT-495
  resolver form; the portable form only works once the global install puts `wikitoolkit` on PATH.
  The page explains this instead (spec §5 mentions a ".mcp.json.example note"; the note lives in
  the new page, not in the example file).
- `mkdocs.yml` navigation (not in this task's file list — the page is reachable via links; report
  if `mkdocs build --strict` complains).
- Any behavior change; README edits; the bootstrap scripts' own plan text (TASK-4074/4075 — the
  docs quote what they print, they do not define it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/getting-started.md` | MODIFY | canonical guide: global install path (C14a-explained), `parrot self`, "Use the SDD flow in your repo"; claim anchors |
| `packages/ai-parrot/tests/docs/test_getting_started_claims.py` | MODIFY | `cli-verb` + `flag` claim kinds over guide + reference page; C14a explanation test |
| `docs/install/global-runtime.md` | CREATE | managed-runtime reference page (claim anchors) |
| `INSTALL.md` | MODIFY | short pointer to the canonical guide |
| `docs/INSTALL.md` | MODIFY | short pointer to the canonical guide; fix stale Python range |

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
# packages/ai-parrot/tests/docs/test_getting_started_claims.py — the claim harness to EXTEND (verified 2026-10-14)
REPO_ROOT = Path(__file__).resolve().parents[4]            # line 20
GUIDE = REPO_ROOT / "docs" / "getting-started.md"          # line 21
ANCHOR_RE = re.compile(r"<!--\s*verify:\s*(?P<kind>[\w-]+)=(?P<value>.+?)\s*-->")   # line 28
class DocClaim(BaseModel):                                 # line 31 (pydantic BaseModel, `from pydantic import BaseModel` :17)
    kind: Literal["python-range", "extra", "script", "provider", "envvar", "dep"]   # line 34 — grows by 2 kinds here
    value: str; line: int; source: Path
def extract_claims(path: Path) -> list[DocClaim]:          # line 40 — line-numbered extraction, loud failures
def test_extract_claims_parses_all_kinds(tmp_path): ...    # line 59 — fixture doc with the 6 kinds; stays as is
def _claims(kind: str) -> list[DocClaim]:                  # line 125 — GUIDE only
def test_named_scripts_exist() -> None:                    # line 161 — style: f"{c.source}:{c.line} …" failures
def test_named_dep_floors_match() -> None:                 # line 183 — last claim test before the hello-world block
```
- Guide anchors in use today (style to copy): `<!-- verify: python-range=>=3.11,<3.14 -->` (:13),
  `<!-- verify: extra=anthropic -->` (:134), `<!-- verify: script=wikitoolkit -->` (:272). Guide
  headings: `## 2. Install the package` (:84), `## 5. Building and querying the codebase knowledge
  graph` (:266), `## 6. Optional extras` (:291), `## 7. Verification checklist & troubleshooting` (:319).
- CI: `.github/workflows/ci.yml` job `install-guide` (:113) runs the docs tests after "Scaffold
  NavConfig environment" (:133) — the harness extension is CI-verified by construction.
- Doc targets: `INSTALL.md` TOC line `- [Python Environment Setup](#python-environment-setup)` (:9),
  heading `## Python Environment Setup` (:158); `docs/INSTALL.md` `[Back to README](../README.md)` (:3),
  `- Python 3.10–3.12` (:8), `## Install with uv (recommended)` (:20).
- FEAT-586 AC8 (`sdd/specs/parrot-install-guide.spec.md:332-335`): "Every command block is
  accompanied by an explanation of what it does … non-piped alternative where one exists."
- Bootstrap facts to quote (TASK-4074/4075): pinned uv `0.11.28`, download URL
  `https://github.com/astral-sh/uv/releases/download/0.11.28/uv-<target>.{tar.gz,zip}` + `.sha256`,
  writes `PARROT_HOME/{bin,venv,python}`, gate conditions (platform, download + checksum tool, `git`,
  writable `PARROT_HOME` with `MIN_FREE_KB` = 2 GiB free, GitHub/PyPI reachable), post-install
  `parrot self doctor --runtime-only` with rollback on runtime failure only.
- Raw URL base: `https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install/`
  (repo `phenobarbital/ai-parrot`, verified from `docs/INSTALL.md:16` clone URL); checksum file
  `scripts/install/SHA256SUMS` (TASK-4076).
- Launcher resolution order (spec §2/§5): `PARROT_VENV` → project venv (worktree `.venv` first, then
  main checkout) → `VIRTUAL_ENV` → managed; warn once per session on stderr.
- `--portable` stickiness (brief cross-cutting decision): `parrot toolkits` re-emits a host's toolkit
  entries in portable form iff that host's current managed `wikitoolkit` entry is portable.
- Store gate: `WikiStoreVersionError` (TASK-4092) — raised only when the store's `schema_version` is
  newer than the runtime's (schema number, never release number); message names both schemas, the
  release that wrote the store, the running version and the fix (`parrot self update` /
  `parrot self add --here`). *[rev 0.5]*
- `parrot sdd` surface (TASK-4091 + C6 task, rev 0.2): `install [--host …] [--dry-run] [--force]`,
  `uninstall [--dry-run]`, `status` (per-file `missing | current | outdated | edited | foreign` from the
  committed record `sdd/.sdd-installed.json`; seed entries `seed-present | missing`), `run <name> [args…]`; seeds `sdd/config.json`,
  `sdd/CONVENTIONS.md`, `sdd/tasks/.id_ledger.json`, the `.claude/worktrees/` ignore block; *[rev 0.5 D5]* also
  writes the `.gitattributes` ledger block (recorded in the receipt) and the `parrot-ledger` git hooks.
- `parrot self doctor` scopes (TASK-4080, rev 0.2): default, `--sdd` (repo readiness: `origin`,
  base branch, committed ledger, worktrees ignore, `gh` auth, `jq`, SDD files current, host CLIs
  informational), `--runtime-only` (bootstrap scope); `--sdd` and `--runtime-only` are mutually
  exclusive.

### Does NOT Exist
- ~~`docs/install/`~~ — directory is new (created with the page).
- ~~`cli-verb` / `flag` claim kinds, `_resolve_verb`, `CLI_DOCS` in the harness~~ — new here.
- ~~`packages/ai-parrot/tests/docs/test_global_runtime_docs.py`~~ — never created (merged into
  the harness, C13).
- ~~`python -m parrot.sdd.scripts.<name>` as the documented helper form~~ — rev 0.2 replaced it
  with `parrot sdd run <name>` (Q1); docs never show `python -m` for helpers.
- ~~`sdd/CONFIG.md`~~ — rejected in the C6 decision; the only repo config file is `sdd/config.json`.
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
      "path": "docs/getting-started.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/docs/test_getting_started_claims.py",
      "action": "MODIFY"
    },
    {
      "path": "docs/install/global-runtime.md",
      "action": "CREATE"
    },
    {
      "path": "INSTALL.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/INSTALL.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup",
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup.get_command",
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#cli",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py#claude",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py#codex",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py#google",
    "sym:packages/ai-parrot/tests/docs/test_getting_started_claims.py#extract_claims",
    "sym:packages/ai-parrot/tests/docs/test_getting_started_claims.py#DocClaim",
    "sym:packages/ai-parrot/tests/docs/test_getting_started_claims.py#test_named_scripts_exist"
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
- Write both pages from the CODE as merged (run `parrot self --help`, `parrot sdd --help`,
  `parrot sdd install --help`, `parrot claude install --help`, …) — *why*: the harness fails on
  any verb or flag the CLI does not register.
- **Claims, not greps**: every documented `parrot …` command gets `<!-- verify: cli-verb=<group>
  <sub> -->` and every documented flag `<!-- verify: flag=<group> <sub>:--flag -->`, in both
  documents — *why*: the harness verifies anchors, exactly like FEAT-586's six kinds; nothing is
  verified by scraping code fences.
- **C14a explanation shape** (testable): in `docs/getting-started.md`, each install one-liner
  fence (the `curl … | bash` / `irm … | iex` forms) is immediately followed by a paragraph
  containing the literal phrases `Downloads:`, `Writes:`, `Verified by:` and `Without piping:`
  — *why*: `test_install_commands_are_explained` finds the fence and asserts those four labels in
  the next paragraph (file:line in the failure).
- Quote the plan paragraph the bootstrap prints and the gate conditions as TASK-4074/4075
  implement them; quote the store-gate message only as the code emits it (TASK-4092) — FILL IN
  the exact texts.
- `INSTALL.md` / `docs/INSTALL.md` become pointers: delete their install walkthroughs (they are
  the duplicates C13 removes), keep non-install content, link `docs/getting-started.md` first and
  `docs/install/global-runtime.md` second.
- Never document `python -m parrot.sdd.scripts.<name>`; helpers are `parrot sdd run <name>` (Q1).
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
2. Extend the claim harness (`cli-verb`, `flag`, C14a explanation test) and run it against the
   unchanged guide — *why*: it must stay green before the docs grow.
3. Extend `docs/getting-started.md` (canonical guide) — *why*: C13, one verified entry point.
4. Write `docs/install/global-runtime.md` — *why*: reference detail, same anchors.
5. Reduce `INSTALL.md` and `docs/INSTALL.md` to pointers; fix the stale Python range — *why*: C13.
6. Run the harness again — *why*: every new claim must resolve.

### `packages/ai-parrot/tests/docs/test_getting_started_claims.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'kind: Literal\["python-range", "extra", "script", "provider", "envvar", "dep"\]' packages/ai-parrot/tests/docs/test_getting_started_claims.py)
# REPLACE — :34 with:
    kind: Literal["python-range", "extra", "script", "provider", "envvar", "dep", "cli-verb", "flag"]

# AFTER — `def test_named_dep_floors_match() -> None:` block (:183-…; anchor occurrences: 1) — insert
# before `def _make_stub_client_class` (:198):
GLOBAL_RUNTIME = REPO_ROOT / "docs" / "install" / "global-runtime.md"
CLI_DOCS = (GUIDE, GLOBAL_RUNTIME)   # C13: both documents are verified by the same harness
INSTALL_ONE_LINER_RE = re.compile(r"\|\s*(bash|sh|iex)\b")   # a piped install command inside a fence


def _cli_claims(kind: str) -> list[DocClaim]:
    """`cli-verb` / `flag` claims across every CLI-bearing document that exists."""
    return [c for doc in CLI_DOCS if doc.is_file() for c in extract_claims(doc) if c.kind == kind]


def _resolve_verb(path: str) -> click.Command | None:
    """Walk `parrot <group> [<sub> …]` through the REAL lazy CLI (`LazyGroup.get_command` imports on demand)."""
    from parrot.cli import cli  # imported lazily: needs navconfig's env/ scaffold (CI install-guide job)

    cmd: click.Command = cli
    ctx = click.Context(cli)
    for part in path.split():
        if not isinstance(cmd, click.Group):
            return None
        nxt = cmd.get_command(ctx, part)
        if nxt is None:
            return None
        ctx = click.Context(nxt, parent=ctx)
        cmd = nxt
    return cmd


def test_extract_claims_parses_cli_kinds(tmp_path: Path) -> None:
    """The two rev-0.2 kinds parse with the `group sub` / `group sub:--flag` value shapes."""
    doc = tmp_path / "d.md"
    doc.write_text("<!-- verify: cli-verb=sdd install -->\n<!-- verify: flag=sdd install:--dry-run -->\n", encoding="utf-8")
    kinds = {c.kind: c.value for c in extract_claims(doc)}
    assert kinds == {"cli-verb": "sdd install", "flag": "sdd install:--dry-run"}


def test_cited_cli_verbs_exist() -> None:
    """Every `cli-verb` claim resolves to a registered click command (C13)."""
    claims = _cli_claims("cli-verb")
    assert claims, "no cli-verb claims found — the guide must anchor its parrot commands"
    for c in claims:
        assert _resolve_verb(c.value) is not None, f"{c.source}:{c.line} unknown command 'parrot {c.value}'"


def test_cited_flags_exist() -> None:
    """Every `flag` claim (`<verb>:<--flag>`) is an option of that command (C13)."""
    for c in _cli_claims("flag"):
        verb, _, flag = c.value.partition(":")
        cmd = _resolve_verb(verb)
        assert cmd is not None, f"{c.source}:{c.line} unknown command 'parrot {verb}'"
        opts = {o for p in cmd.params for o in (*p.opts, *p.secondary_opts)}
        assert flag in opts, f"{c.source}:{c.line} 'parrot {verb}' has no option {flag}"


def test_install_commands_are_explained() -> None:
    """C14a / FEAT-586 AC8: each piped install one-liner is followed by Downloads/Writes/Verified by/Without piping."""
    lines = GUIDE.read_text(encoding="utf-8").splitlines()
    found = 0
    for i, text in enumerate(lines, start=1):
        if not INSTALL_ONE_LINER_RE.search(text):
            continue
        found += 1
        # FILL IN: locate the paragraph after the closing fence and assert the four labels — bounded by
        #          failure messages of the form f"{GUIDE}:{i} install command lacks '<label>'"
    assert found >= 2, "the guide must document the POSIX and PowerShell one-liners"
```
**Why**: FEAT-586's harness is already the CI-verified source of truth for the guide; adding two
kinds (instead of a parallel `test_global_runtime_docs.py`) keeps one verifier and lets the
reference page share it. `_resolve_verb` exercises the real lazy registration of TASK-4080
(`self`) and TASK-4091 (`sdd`), so a renamed flag breaks this test, not users. `click` is a core
dependency (`cli/__init__.py:16`); add `import click` to the test's imports.

### `docs/getting-started.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^## 3. Install a provider (REQUIRED)' docs/getting-started.md) -->
<!-- AFTER — the end of `## 2. Install the package` (i.e. immediately BEFORE `## 3. Install a provider (REQUIRED)`, :132) — insert: -->
### Global install (managed runtime, no project venv)
<!-- verify: cli-verb=self doctor -->
<!-- verify: flag=self doctor:--runtime-only -->

One command installs `parrot`, `wikitoolkit` and `bookstore` for your coding assistant, machine-wide:

    ```bash
    curl -fsSL https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install/install-parrot.sh | bash -s -- --global --with sdd
    ```
**Downloads:** the script above and, from GitHub, pinned `uv 0.11.28` plus its `.sha256`.
**Writes:** `~/.parrot/bin`, `~/.parrot/venv` (Python 3.12 + ai-parrot) and `~/.parrot/python`,
plus a `# >>> parrot >>>` PATH block in your shell profile; nothing else in `~/.parrot` is touched.
**Verified by:** the uv checksum, then `parrot self doctor --runtime-only` (a failure removes only
what the run created). Before writing anything the script checks platform, `curl`/`wget`,
`sha256sum`, `git`, free space (2 GiB) and GitHub/PyPI reachability.
**Without piping:** download `install-parrot.sh` and `SHA256SUMS` from the same folder, run
`sha256sum -c --ignore-missing SHA256SUMS`, read the script, then `bash install-parrot.sh --global`.
<!-- FILL IN: the PowerShell one-liner (`irm … | iex` or Invoke-WebRequest + -File) with the same four
     labels (Get-FileHash, user PATH never Machine) — bounded by TASK-4075 -->

### Manage the runtime: `parrot self`
<!-- verify: cli-verb=self add --> <!-- verify: cli-verb=self env --> <!-- verify: cli-verb=self update --> <!-- verify: cli-verb=self uninstall -->
<!-- FILL IN: one line per command; `--here` is the only way a dependency enters a project venv — bounded by TASK-4080 --help -->

<!-- occurrences: 1 (verified: grep -c '^## 6. Optional extras' docs/getting-started.md) -->
<!-- AFTER — the end of section 5 (immediately BEFORE `## 6. Optional extras`, :291) — insert: -->
### Use the SDD flow in your repo
<!-- verify: cli-verb=sdd install --> <!-- verify: flag=sdd install:--host --> <!-- verify: flag=sdd install:--dry-run -->
<!-- verify: flag=sdd install:--force --> <!-- verify: cli-verb=sdd status --> <!-- verify: cli-verb=sdd run -->
<!-- verify: cli-verb=self doctor --> <!-- verify: flag=self doctor:--sdd -->

    ```bash
    parrot sdd install --host claude --dry-run   # preview: write / skip / upgrade per file
    parrot sdd install --host claude
    parrot self doctor --sdd                      # origin, base branch, ledger, gh, jq, host CLI
    parrot sdd status                             # missing | current | outdated | edited | foreign
    ```
<!-- FILL IN: edit `sdd/config.json` (base_branch, hotfix_base, issue_tracker, test_command — set it
     unless the repo uses ai-parrot's FEAT-699 selection: shipped test steps then run it, rev 0.5 C21), the
     `sdd/CONVENTIONS.md` seed (`## Repository layout`, `## Project areas`, rev 0.5 C22), first `/sdd-*` command, helpers run as `parrot sdd run <name>`,
     re-running install upgrades untouched files and keeps edited ones — bounded by TASK-4091 + C6 task -->
```
**Why**: the guide is the canonical entry point (C13); every command is explained in the AC8 shape
(C14a) and anchored for the harness. Rendering note for THIS task file: inner fences are indented
and headings shown one level deeper (`###`) so task parsers splitting on `^## ` are not confused —
write them as `##`/normal fences in the real file, matching the guide's numbering.

### `docs/install/global-runtime.md` (CREATE)
```markdown
# Global install: the parrot-managed runtime (reference)

> The guide is [docs/getting-started.md](../getting-started.md); this page holds the detail.

`--global` installs AI-Parrot once per machine under `~/.parrot` (or `$PARROT_HOME`): a pinned
`uv`, a uv-managed Python 3.12, `~/.parrot/venv`, and `parrot` / `wikitoolkit` / `bookstore` on PATH.
Your existing `~/.parrot` data (wikis.json, library/, skills/, brains/, parrot.db) is never touched;
the installer only adds `bin/`, `venv/` and `python/`, and a failed run removes only what it created.

### What the installer checks and prints
<!-- FILL IN: the gate list (platform matrix, download/checksum tool, git, writable PARROT_HOME with
     2 GiB free, GitHub/PyPI reachable; network skipped under --dry-run) and the plan paragraph,
     quoted as TASK-4074/4075 print them; post-install `parrot self doctor --runtime-only` and what
     rolls back (runtime failures only — repo readiness never does) -->

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
<!-- verify: cli-verb=self env --> <!-- verify: cli-verb=self doctor --> <!-- verify: flag=self doctor:--sdd -->
<!-- verify: flag=self doctor:--runtime-only --> <!-- verify: cli-verb=self add --> <!-- verify: flag=self add:--here -->
<!-- verify: cli-verb=self update --> <!-- verify: cli-verb=self uninstall --> <!-- verify: flag=self uninstall:--yes -->

    ```bash
    parrot self env
    parrot self doctor            # runtime + host configs + components (+ SDD readiness when sdd/ exists)
    parrot self doctor --sdd      # repo readiness only: origin, base branch, ledger, worktrees ignore, gh, jq, host CLIs
    parrot self add scraping
    parrot self add scraping --here
    parrot self update
    parrot self uninstall --yes
    ```
<!-- FILL IN: one sentence per command from the merged --help; `--here` is the ONLY way a
     dependency enters a project venv; `--runtime-only` is the bootstrap's scope and is mutually
     exclusive with `--sdd` — bounded by TASK-4080 -->

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
<!-- verify: cli-verb=sdd install --> <!-- verify: flag=sdd install:--host --> <!-- verify: flag=sdd install:--dry-run -->
<!-- verify: flag=sdd install:--force --> <!-- verify: cli-verb=sdd status --> <!-- verify: cli-verb=sdd uninstall -->
<!-- verify: flag=sdd uninstall:--dry-run --> <!-- verify: cli-verb=sdd run -->

    ```bash
    parrot sdd install --host claude --dry-run
    parrot sdd install --host claude
    parrot sdd status
    parrot sdd run reserve_ids --kind task --count 1 --base-branch dev --label demo
    parrot sdd uninstall --dry-run
    ```
<!-- FILL IN: helpers run as `parrot sdd run <name>` (never `python -m …`: in a global-only install the
     repo's `python` cannot import parrot); the record `sdd/.sdd-installed.json` and the status states
     missing | current | outdated | edited | foreign, and seeds as seed-present | missing; upgrade rule (recorded hash matches → upgrade; differs → kept
     with a warning unless --force; not ours → skipped); `sdd/config.json` fields (base_branch,
     staging_branch, hotfix_base, issue_tracker, jira_host, reviewer, test_command, projects); what
     `test_command` switches (rev 0.5 C21/D2: when set, /sdd-task and /sdd-done skip the FEAT-699
     selection/report steps and run it; zero tests → "⚠️ not run"; install warns when null); the
     `.gitattributes` ledger block and the four ledger hooks `parrot sdd install` adds (rev 0.5 C23);
     `/sdd-insight` is not shipped (rev 0.5 C22); the managed runtime includes `ai-parrot-tools`
     (rev 0.5 C20); the `sdd/CONVENTIONS.md` seed (created once, never overwritten, even with --force)
     — bounded by TASK-4091, TASK-4299 and the C6 task -->

### Version skew
<!-- FILL IN: quote WikiStoreVersionError's message as emitted (TASK-4092) and the fix
     (`parrot self update`, or `parrot self add --here` for a project venv); say the gate compares
     the store's schema number only — a store written by a newer release with the same schema
     opens normally [rev 0.5]; note that runtimes older than this release have no gate. -->
```
**Why this shape**: one page owns the managed-runtime story. Rendering conventions of THIS task
file: the inner code fences are indented only to nest inside the block, and every heading inside
the Markdown blocks of this blueprint (here and in the two INSTALL blocks below) is shown one
level deeper (`###`) so SDD task parsers that split on `^## ` are not confused — write them as
normal top-level fences and `##` headings in the real files.

### `INSTALL.md` (MODIFY — becomes a pointer, C13)
```markdown
<!-- occurrences: 1 (verified: grep -cF '- [Python Environment Setup](#python-environment-setup)' INSTALL.md) -->
<!-- The install walkthrough sections (the TOC entry `- [Python Environment Setup](#python-environment-setup)`,
     :9, through the end of that section, :158-…) are REPLACED by one pointer paragraph; non-install
     content stays. FILL IN: the exact span after reading the file — bounded by "no install
     walkthrough remains here". -->
## Installing

The install and first-use guide is [docs/getting-started.md](docs/getting-started.md) — project
venv or the machine-wide managed runtime (`--global`), providers, verification. Reference detail for
the managed runtime, `parrot self …` and the SDD flow: [docs/install/global-runtime.md](docs/install/global-runtime.md).
```

### `docs/INSTALL.md` (MODIFY — becomes a pointer, C13)
```markdown
<!-- occurrences: 1 (verified: grep -cF '- Python 3.10–3.12' docs/INSTALL.md) -->
<!-- REPLACE — `- Python 3.10–3.12` (verified: docs/INSTALL.md:8) with: -->
- Python 3.11–3.13

<!-- occurrences: 1 (verified: grep -cF '## Install with uv (recommended)' docs/INSTALL.md) -->
<!-- REPLACE — `## Install with uv (recommended)` (:20) and the install walkthrough that follows it with: -->
## Install

Follow the canonical guide: [getting-started.md](getting-started.md). It covers the project-venv
install, the machine-wide managed runtime (`install-parrot.sh --global` / `install-parrot.ps1
-Global`, with what each command downloads, writes and verifies, and a non-piped alternative),
providers and verification. Managed-runtime reference: [install/global-runtime.md](install/global-runtime.md).
<!-- FILL IN: exact span to delete (through the end of the install walkthrough; keep `[Back to README]`
     and any non-install sections) — bounded by "no install walkthrough remains here" -->
```
**Why**: C13 — four install documents became one verified guide plus one reference page; the two
INSTALL files only point.

### FILL IN checklist
- [ ] `getting-started.md` PowerShell one-liner + its four C14a labels; bounded by TASK-4075.
- [ ] `getting-started.md` `parrot self` one-liners and the SDD section prose; bounded by TASK-4080/4091 `--help` + C6 task.
- [ ] `test_getting_started_claims.py::test_install_commands_are_explained` — paragraph-after-fence location + the four labels; bounded by FEAT-586 AC8.
- [ ] `global-runtime.md` gate list + plan paragraph quoted from the scripts; bounded by TASK-4074/4075.
- [ ] `global-runtime.md` Windows section — exact PowerShell download/verify/run lines; bounded by TASK-4075.
- [ ] `global-runtime.md` `parrot self …` descriptions and real flag names (e.g. `uninstall --yes`, `update --version`, `doctor --sdd/--runtime-only`); bounded by TASK-4080 `--help`.
- [ ] `global-runtime.md` `--portable` per-host field contract + stickiness + `.mcp.json.example` rationale; bounded by TASK-4082/4083/4084.
- [ ] `global-runtime.md` `parrot sdd` upgrade rule, status states, `run`, `sdd/config.json` fields, `CONVENTIONS.md` seed; bounded by TASK-4091 + C6 task.
- [ ] `global-runtime.md` version-skew message text; bounded by TASK-4092's `WikiStoreVersionError`.
- [ ] `INSTALL.md` / `docs/INSTALL.md` — exact spans replaced by the pointer paragraphs.

---

## Acceptance Criteria

- [ ] **C13**: `docs/getting-started.md` is the canonical guide — it documents the `--global`
      path (POSIX + PowerShell), `parrot self add|env|doctor|update|uninstall`, `parrot sdd
      install` (`--host`, `--dry-run`, `--force`), `parrot sdd status`, `parrot sdd run`,
      `parrot self doctor --sdd`, and a "Use the SDD flow in your repo" section; every
      `parrot …` command and flag it cites carries a `cli-verb` / `flag` anchor.
- [ ] **C14a / FEAT-586 AC8**: every documented install one-liner (raw-URL bootstrap, which
      itself downloads pinned uv) is followed by what it downloads, where it writes, how it is
      verified (checksums + `doctor --runtime-only`) and a non-piped alternative (download,
      inspect, verify, run) — asserted by `test_install_commands_are_explained`.
- [ ] `docs/install/global-runtime.md` documents: the pre-install gate + plan paragraph, raw-URL
      install + `SHA256SUMS` verification (POSIX and PowerShell), `parrot self …` incl. `doctor
      --sdd` / `--runtime-only`, launcher resolution order, `--portable` per host with the
      stickiness rule, `parrot sdd install|uninstall|status|run` with the upgrade rule and status
      states, `sdd/config.json`, the `sdd/CONVENTIONS.md` seed, Windows notes, and the
      version-skew gate message + fix; same anchors.
- [ ] `INSTALL.md` and `docs/INSTALL.md` contain no install walkthrough — only pointers to the
      guide (first) and the reference page; `docs/INSTALL.md` states Python 3.11–3.13.
- [ ] No document shows `python -m parrot.sdd.scripts.<name>` as the helper form; helpers are
      `parrot sdd run <name>`.
- [ ] `sdd/specs/portable-sdd-flow.spec.md` is untouched (already superseded in `2ed09515e`).
- [ ] `.mcp.json.example` is unchanged (deliberate; rationale in the page).
- [ ] `test_getting_started_claims.py` passes with the `cli-verb` / `flag` kinds verifying BOTH
      documents against the real click CLI (`_resolve_verb` through `parrot.cli:cli`), and no
      `test_global_runtime_docs.py` exists.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/docs/test_getting_started_claims.py -q`
Also, outside the pytest contract: `packages/ai-parrot/tests/docs/test_global_runtime_docs.py` must NOT exist
(`test ! -e …`), and `grep -rn "python -m parrot.sdd.scripts" docs/getting-started.md docs/install/global-runtime.md INSTALL.md docs/INSTALL.md`
must find nothing.

---

## Test Specification

```python
# packages/ai-parrot/tests/docs/test_getting_started_claims.py — additions (see blueprint)
def test_extract_claims_parses_cli_kinds(tmp_path): ...   # cli-verb / flag value shapes
def test_cited_cli_verbs_exist(): ...                      # every cli-verb claim (guide + reference page) resolves via parrot.cli:cli
def test_cited_flags_exist(): ...                          # every flag claim is an option of its command
def test_install_commands_are_explained(): ...             # C14a: Downloads / Writes / Verified by / Without piping after each one-liner
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

**Completed by**: sdd-worker (claude-sonnet-5-5)
**Date**: 2026-10-26
**Notes**: Extended getting-started.md (global install POSIX+PowerShell with Downloads/Writes/Verified by/Without piping, parrot self, SDD section); harness gained cli-verb/flag kinds + test_install_commands_are_explained; created docs/install/global-runtime.md; INSTALL.md and docs/INSTALL.md are pointers (Python 3.11-3.13). 14 harness tests pass.

**Deviations from spec**: PowerShell one-liner uses a child-process scriptblock form (irm|iex cannot pass -Global; exit would close the session), so INSTALL_ONE_LINER_RE also matches [scriptblock]::Create; the explanation test only inspects lines inside code fences (prose mentioned 'curl | bash'). INSTALL.md kept system-dependency sections, removed uv/venv/install sections.
