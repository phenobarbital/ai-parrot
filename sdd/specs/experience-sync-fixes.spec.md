---
type: feature
base_branch: dev
feature_id: FEAT-905
projects: [ai-parrot]
tags: [sdd-tooling, ledger-fix, experience-memory]
discovered_from: issue:ebd9db5806f2
docs:
  policy: none
  pages: []
  api_modules: []
---

# Feature Specification: `parrot sdd experience export` writes into the checkout it runs in, without home paths

**Feature ID**: FEAT-905
**Date**: 2026-11-17
**Author**: Jesus Lara
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

Ledger `issue:ebd9db5806f2` (minor bug, discovered from `spec:FEAT-904`): `/sdd-done` step 7 runs
`parrot sdd experience export` inside the feature worktree. It stages the returned path only when the path is
under `<worktree>/sdd/experience/lessons/`, and otherwise exits 2 with `refusing unexpected experience export path`.
The Codex twin (`.agents/skills/sdd-done/SKILL.md`) states the same contract.

The FEAT-887 spec agrees (`sdd-experience-memory.spec.md`, "Sharing"): `export` writes "into **one new file** under
`sdd/experience/lessons/` of the checkout it runs in".

The code does not. `experience_cli._dispatch` (`experience_cli.py:198`) calls
`export_shared(service.plane_dir, service.root)`. `ExperienceService.from_root()` resolves `root` with
`find_shared_root`, which is the **primary checkout** even when the command runs in a linked worktree. So:

- the export lands in `<primary checkout>/sdd/experience/lessons/<digest>.jsonl` and leaves an untracked
  `sdd/experience/` directory in the shared checkout, which other sessions see as dirty;
- the `/sdd-done` path check can never pass from a worktree, so step 7 always exits 2 once anything is pending.

Seen in `/sdd-done FEAT-904`. The exported file also held 15 absolute `/home/<user>` paths. Today the repo log
holds 38 events whose text contains the user's home directory, mostly in `fix_example`, `scope_paths` and
`command_example`. A shared lesson file is git-tracked, so staging it would publish the local username and
directory layout.

Decision taken with the user on 2026-11-17: the export **scope stays repo-wide**, as FEAT-887 specifies. Every
not-yet-exported definition and attestation in the repo log is exported, whichever feature runs `/sdd-done`.
Readers de-duplicate by `event_id`, so the same event exported by two branches is harmless.

### Goals
- Run from a linked worktree, `parrot sdd experience export` writes its new file under
  `<worktree>/sdd/experience/lessons/` and prints that path. The primary checkout is not touched.
- Run from the primary checkout, or from any directory below it, the export behaves as today.
- The export de-duplicates against the lessons directory of the checkout it writes into, as `export_shared`
  already does for its `checkout` argument.
- Canonical experience events never contain a user home-directory prefix. `/home/<user>`, `/var/home/<user>`,
  `/Users/<user>` and `<drive>:/Users/<user>` become `~` when an event is validated, so exported files never
  contain one.
- Event identity stays stable. Validating an already-canonical event again yields the same `event_id`. A legacy
  raw line that still holds a home path gets the same canonical identity in every source (repo log, global log,
  shared files), so the export does not export it again.

### Non-Goals (explicitly out of scope)
- Scoping the export to one feature, by changed files or by recorded provenance. The user chose repo-wide.
- Changing `/sdd-done`, its Codex twin or their installer copies. They already describe the fixed behaviour.
- Changing `redact()` in `fastpath.py`, `failure_signature`, `lesson_id_for` or `solution_rev_for`. Lesson
  identity, revision identity and trigger matching keep their current inputs (see §7).
- Rewriting raw repo-log lines on disk. Normalization happens when an event is validated (read or record).
- Normalizing absolute paths outside a home directory (`/tmp/...`, `/opt/...`) or Windows backslash paths.
- The `actor` value (for example `human:<name>`), which is the same identity git already records as the author.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:537ad011cfc7cd8844cf5a3dfcbc98430d0caca8abb428024b83f6186c9be0a4 evaluation_digest=sha256:ee79a38fbc97fd3197ca543f26f89d635eb8421a64957f97991bf87ca833e09d rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Two independent changes:

1. **Export target** (`packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py`). A new private helper
   `_export_checkout(shared_root: Path) -> Path` walks up from `Path.cwd().resolve()` to the nearest directory
   that has a `.git` entry (a directory for the primary checkout, a file for a linked worktree). When
   `find_shared_root(candidate)` equals `shared_root` (both resolved), that directory is returned. Otherwise
   `shared_root` is returned. That covers a nested repository or a submodule, whose shared root differs, and the
   case of no `.git` entry at all. The `export` branch passes `_export_checkout(service.root)` as the `checkout`
   argument of `export_shared`. The plane (`service.plane_dir`), graduation and the ledger stay on the shared
   root. The `export` help text says the file goes into the current checkout.

2. **Home-path normalization** (`packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py`). A new
   compiled pattern `_HOME_PATH_RE` and a private recursive function `_strip_home(value: Any) -> Any` (strings,
   lists and dicts, like `_redact_text`). Every match becomes `~`. `validate_event` applies it to the canonical
   payload, **after** `_normalize_payload` (so `normalize_error` has already removed the absolute paths from
   `error_signature`), and to the redacted envelope. Both happen before `_event_id_for`.

   ```python
   _HOME_PATH_RE = re.compile(
       r"(?<![\w.~-])(?:/var)?/(?:home|Users)/[^/\s'\"`:;,)\]}>]+"
       r"|(?<![\w.~/:-])[A-Za-z]:/Users/[^/\s'\"`:;,)\]}>]+"
   )
   ```

   The drive-letter form is a separate alternative that cannot start right after `/` or `:`, so
   `PATH=/home/a/p:/home/a/q` keeps its `p:` separator.

   Examples: `/home/alice/repo/x.py` → `~/repo/x.py`; `PYTHONPATH=/home/alice/p:/home/alice/q` →
   `PYTHONPATH=~/p:~/q`; `/Users/bob` → `~`; `/var/home/carol/.cache` → `~/.cache`; `C:/Users/dave/src` →
   `~/src`. Unchanged: `src/home/alice/x`, `/srv/home/alice`, `/tmp/project`, `~/x`. The function is idempotent.

### Component Diagram
```
/sdd-done (cd <worktree>) ─→ parrot sdd experience export
   └─ experience_cli._dispatch("export")
         ├─ ExperienceService.from_root()          → root = shared root, plane = <shared>/.parrot/experience (unchanged)
         ├─ graduate(service, LedgerService(root))  (unchanged)
         └─ export_shared(plane, _export_checkout(root))   ← new: the invoking checkout
               └─ reads repo/global/shared events via validate_event
                     └─ _strip_home(...)  ← new, before event identity
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `experience_cli._dispatch` | modifies | `export` branch passes the invoking checkout |
| `experience_cli._parser` | modifies | `export` help text |
| `experience_cli._export_checkout` | new private function | before `_dispatch` |
| `project.find_shared_root` | reused, unchanged | `project.py:1568` |
| `sync.export_shared` | consumer, unchanged | `sync.py:121`; already writes under its `checkout` argument |
| `models.validate_event` | modifies | applies `_strip_home` to payload and envelope before identity |
| `models._strip_home`, `models._HOME_PATH_RE` | new private | next to `_redact_text` |
| `/sdd-done` step 7 and its Codex twin | consumer, unchanged | path check now passes from a worktree |

### Data Models
None. The event schema is unchanged; only the canonical text of path-bearing values changes.

### New Public Interfaces
None. The CLI arguments are unchanged.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: export into the invoking checkout | yes | helper contract, fallback rule and tests are fixed in §2 and §4 | — |
| M2: home-path normalization before identity | yes | pattern, placement after `_normalize_payload` and tests are fixed in §2 and §4 | — |

### Module 1: export into the invoking checkout
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py`,
  `packages/ai-parrot/tests/sdd/test_experience_cli.py`
- **Responsibility**: `export` writes into the primary checkout or linked worktree it runs in.
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  from parrot.knowledge.wiki.project import find_shared_root

  def _export_checkout(shared_root: Path) -> Path:
      """Return the checkout `export` writes into: the invoking primary checkout or linked worktree."""

  # _dispatch, export branch
  exported = export_shared(service.plane_dir, _export_checkout(service.root))
  ```

### Module 2: home-path normalization before identity
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py`,
  `packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py`,
  `packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py`
- **Responsibility**: no canonical event, and so no exported file, contains a home-directory prefix.
- **Depends on**: nothing new (independent of M1).
- **Interface Skeleton**:
  ```python
  import re

  _HOME_PATH_RE = re.compile(
      r"(?<![\w.~-])(?:/var)?/(?:home|Users)/[^/\s'\"`:;,)\]}>]+"
      r"|(?<![\w.~/:-])[A-Za-z]:/Users/[^/\s'\"`:;,)\]}>]+"
  )

  def _strip_home(value: Any) -> Any:
      """Recursively replace user home-directory prefixes with ``~``."""

  # validate_event
  canonical_payload = _strip_home(_normalize_payload(envelope.kind, payload))
  canonical_envelope = _strip_home(_redact_text(envelope.model_dump(mode="json")))
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_cli_export_from_linked_worktree_writes_into_worktree` | M1 | a real primary repository with a commit and a `git worktree add` linked worktree; the repo log in `<primary>/.parrot/experience/` holds one recorded lesson; `main(["export"])` with the cwd inside the worktree exits 0, prints `<worktree>/sdd/experience/lessons/<digest>.jsonl`, that file exists, and `<primary>/sdd/experience` does not exist. A second run prints nothing |
| `test_cli_export_ignores_nested_foreign_repository` | M1 | the cwd is inside a nested directory with its own `.git` directory under the primary checkout (a different shared root) → `export_shared` receives the service root |
| `test_cli_export_order`, `test_cli_export_writes_under_checkout_root` | M1 | existing, unchanged: the primary checkout and its subdirectories still export into the service root |
| `test_strip_home_normalizes_home_prefixes` | M2 | parametrized over the §2 examples, including the unchanged inputs; applying it twice gives the same result |
| `test_event_strips_home_paths_before_identity` | M2 | a recorded lesson whose `solution`, `fix_example`, `command_example`, `error_excerpt` and `scope_paths` contain `/home/alice/...` → the validated event contains no `/home/alice`, contains `~/`, `error_signature` equals the value without home normalization, and validating the dumped event again returns an equal event |
| `test_export_strips_home_paths_without_reexport` | M2 | a legacy raw line holding `/home/alice/...` and its stale `event_id`, appended with `append_event`, is exported once: the file contains no `/home/alice`, `shared_event_ids` equals the exported ids, and a second `export_shared` returns `None` |
| existing `test_models.py` and `test_sync.py` tests | M2 | unchanged: redaction, revision identity, export and sync behaviour hold |

### Integration Tests
None.

### Validation Contract

tests:
- packages/ai-parrot/tests/sdd/test_experience_cli.py
- packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py
- packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py
markers: none

### Test Data / Fixtures

M1's worktree test builds a real repository with `git init`, an empty commit
(`git -c user.name=t -c user.email=t@example.com commit --allow-empty -m init`) and
`git worktree add -b linked <tmp>/linked`, as `test_fastpath.py::test_worktree_uses_primary_plane` does. It
sets `PARROT_HOME` to a temporary directory and writes the lesson with the `test_sync.py` style (a
`validate_event` canonical `lesson.recorded` appended with `append_event`). No config file is needed:
`load_project_config` returns defaults when `.parrot/wiki.json` is absent.

---

## 5. Acceptance Criteria

- [ ] From a linked worktree, `parrot sdd experience export` writes and prints a path under
      `<worktree>/sdd/experience/lessons/`, and the primary checkout gains no `sdd/experience/` directory.
- [ ] From the primary checkout or one of its subdirectories, the export target is unchanged.
- [ ] Inside a nested repository with a different shared root, the export falls back to the service root.
- [ ] Validated events contain no `/home/<user>`, `/var/home/<user>`, `/Users/<user>` or `<drive>:/Users/<user>`
      prefix, and `error_signature` is unchanged by the normalization.
- [ ] Validating a canonical event again yields the same `event_id`. A legacy home-path line is exported once
      and a second export returns nothing.
- [ ] The new tests fail on `origin/dev` without the fix and pass with it. The existing tests in the three
      Validation Contract files pass.
- [ ] `ruff check` passes on the changed files. `black` (line length 120) leaves the changed lines unchanged.

---

## 6. Codebase Contract

### Verified Imports
```python
# packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py — already imported
from pathlib import Path  # line 11
from parrot.knowledge.wiki.experience.sync import export_shared, register_namespace, sync_global  # line 16
from parrot.knowledge.wiki.ledger.service import LedgerService  # line 17
# to add (exists at packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1568)
from parrot.knowledge.wiki.project import find_shared_root

# packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py — already imported
import hashlib  # line 5
import json  # line 6
from typing import Any, Literal  # line 8
from parrot.knowledge.wiki.experience.fastpath import MAX_EVENT_BYTES, leading_command, normalize_error, redact  # line 12
# to add: import re (standard library)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py
def _parser() -> argparse.ArgumentParser  # line 31; export subparser at line 64
def _available(service: ExperienceService) -> bool  # line 113
async def _dispatch(args: argparse.Namespace) -> int  # line 139; service = ExperienceService.from_root() at line 141
    # export branch, lines 193-200:
    #   elif args.verb == "export":
    #       if service.root is not None and service.plane_dir is not None:
    #           await service.refresh()
    #           ledger = LedgerService.from_root(service.root)
    #           await graduate(service, ledger, ledger_name=service.root.name)
    #           exported = export_shared(service.plane_dir, service.root)   # line 198
def main(argv: Sequence[str] | None = None) -> int

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
def find_shared_root(start: Path | None = None) -> Path | None  # line 1568; primary checkout for a linked worktree

# packages/ai-parrot/src/parrot/knowledge/wiki/experience/sync.py
def export_shared(repo_plane: Path, checkout: Path) -> Path | None  # line 121; writes checkout / SHARED_DIR / <digest>.jsonl
def shared_event_ids(checkout: Path) -> set[str]  # line 106
SHARED_DIR = Path("sdd") / "experience" / "lessons"  # line 22

# packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py
def validate_event(line: Mapping[str, Any]) -> ExperienceEvent | None  # line 225
    # line 254: canonical_payload = _normalize_payload(envelope.kind, payload)
    # line 255: canonical_envelope = _redact_text(envelope.model_dump(mode="json"))
    # line 256: canonical_envelope["payload"] = canonical_payload
    # line 257: canonical_envelope["event_id"] = _event_id_for(canonical_envelope)
def _normalize_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]  # line 297; normalize_error on error_signature
def _redact_text(value: Any) -> Any  # line 317

# packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py
def append_event(plane_dir: Path, record: Mapping[str, Any]) -> bool  # line 584; writes the mapping as given (no validation)
def normalize_error(text: str) -> str  # line 370; replaces absolute paths with a space
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_export_checkout` | `find_shared_root` | direct call | `project.py:1568` |
| `_dispatch` export branch | `_export_checkout` | direct call | `experience_cli.py:198` |
| `validate_event` | `_strip_home` | direct call | `models.py:254-255` |

### Does NOT Exist (Anti-Hallucination)
- ~~`experience_cli._export_checkout`, `models._strip_home`, `models._HOME_PATH_RE`~~ — created by this feature.
- ~~a `--checkout` flag on `parrot sdd experience export`~~ — none is added; the cwd decides.
- ~~`find_checkout_root` / `find_worktree_root` in `parrot.knowledge.wiki.project`~~ — no such helper;
  `find_project_root` is not usable here, because it returns the primary checkout for a worktree nested under
  `.parrot/worktrees/` (it walks up to the primary's `.parrot/wiki.json`).
- ~~home-path handling in `fastpath.redact`~~ — `redact` is unchanged.
- ~~tracked files under `sdd/experience/` on `origin/dev`~~ — none exist yet.

### Edit Sites (Blueprint Anchors)

Verified against: `c929bcd814`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py` | ADD AFTER | `from parrot.knowledge.wiki.ledger.service import LedgerService` | `experience_cli.py:17` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py` | MODIFY | `    verbs.add_parser("export", help="Export shared lesson definitions.")` | `experience_cli.py:64` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py` | ADD BEFORE | `def _available(service: ExperienceService) -> bool:` | `experience_cli.py:113` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py` | MODIFY | `            exported = export_shared(service.plane_dir, service.root)` | `experience_cli.py:198` | 1 |
| `packages/ai-parrot/tests/sdd/test_experience_cli.py` | ADD BEFORE | `def test_cli_brief_missing_task_file_is_usage_error(` | `test_experience_cli.py:135` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py` | ADD AFTER | `import json` | `models.py:6` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py` | MODIFY | `    canonical_payload = _normalize_payload(envelope.kind, payload)` | `models.py:254` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py` | MODIFY | `    canonical_envelope = _redact_text(envelope.model_dump(mode="json"))` | `models.py:255` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py` | ADD AFTER | `def _redact_text(value: Any) -> Any:` (after the function body) | `models.py:317` | 1 |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py` | ADD BEFORE | `def test_solution_revision_identity(tmp_path: Path) -> None:` | `test_models.py:235` | 1 |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_sync.py` | ADD BEFORE | `def test_export_creates_new_file_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:` | `test_sync.py:285` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Pure functions, no new I/O beyond `Path.exists()` in `_export_checkout`. Logging through the module `logger`,
  never `print`.
- `black` line length 120, Google-style docstrings, strict type hints.

### Known Risks / Gotchas
- **Do not normalize inside `redact()` or before `_normalize_payload`.** `service.record` runs `redact()` and
  then `failure_signature` / `lesson_id_for` / `solution_rev_for`. A `~` residue there would change lesson ids,
  revision ids and the stored trigger signature for path-bearing errors, and existing lessons would stop
  matching live failures. `normalize_error` turns `/home/u/x` into a space, but `~/x` into `~`.
- `validate_event` recomputes `event_id` on every read, so a legacy raw line with a home path gets one new,
  consistent id in every source. Nothing persists event ids that are later compared with freshly computed ones:
  `export_shared` and `sync_global` read every source fresh.
- `fastpath.py` is a hook control file and is not touched. `models.py` is not on the OS-denied list.
- In a worktree the shared venv imports the main checkout. Run pytest from the worktree root with
  `PYTHONPATH=packages/ai-parrot/src`.
- Until this lands on `dev` and the main checkout is updated, `/sdd-done` in any worktree still runs the old
  export and exits 2 at step 7 when something is pending. For this feature's own `/sdd-done`, run the export
  with the worktree's `PYTHONPATH`.

### External Dependencies
None.

---

## Consequences

<!-- decision-audit: input_digest=sha256:537ad011cfc7cd8844cf5a3dfcbc98430d0caca8abb428024b83f6186c9be0a4 evaluation_digest=sha256:ee79a38fbc97fd3197ca543f26f89d635eb8421a64957f97991bf87ca833e09d rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/38f1e376-4234-4a53-8912-f5625500dc42/scratchpad/dev-clone/sdd/specs/experience-sync-fixes.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: experience-memory, ledger-fix, sdd-tooling
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "experience-memory",
      "ledger-fix",
      "sdd-tooling"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/38f1e376-4234-4a53-8912-f5625500dc42/scratchpad/dev-clone/sdd/specs/experience-sync-fixes.spec.md"
    }
  ],
  "evaluation_digest": "sha256:ee79a38fbc97fd3197ca543f26f89d635eb8421a64957f97991bf87ca833e09d",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:537ad011cfc7cd8844cf5a3dfcbc98430d0caca8abb428024b83f6186c9be0a4",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Q1. Export into the invoking worktree, or make `/sdd-done` stop expecting a worktree path? — *Resolved*:
  into the invoking checkout. FEAT-887's spec and both `/sdd-done` twins already state it; the CLI was the outlier.
- [x] Q2. Scope the export to the feature? — *Resolved (user, 2026-11-17)*: no. Repo-wide, as FEAT-887 specifies.
- [x] Q3. Where to remove absolute paths? — *Resolved*: in `validate_event`, after `_normalize_payload` and
  before identity. That is the only place every source passes through. Only home-directory prefixes are
  rewritten, which removes the username; other absolute paths stay.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; spec authored by /sdd-fix from a ledger issue)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `none`. The CLI now does what the FEAT-887 spec and the `/sdd-done` text already document. The
  normalization is internal to event canonicalization.
- **Pages**: none.
- **API modules**: none.

---

## Worktree Strategy

One feature worktree `feat-FEAT-905-experience-sync-fixes` off `origin/dev`.

- Module graph: two modules, no edges (M1 and M2 touch disjoint files).
- Shared files: none.
- Exclusive resources: none.
- Cross-feature: none known.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-17 | Jesus Lara | Created by /sdd-fix from `issue:ebd9db5806f2` (fixgroup:616e1d264438; its sibling `issue:8a57d1b3aaa1` was already fixed by PR #2156 and closed) |
