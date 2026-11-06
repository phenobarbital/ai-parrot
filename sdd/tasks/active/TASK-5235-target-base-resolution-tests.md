# TASK-5235: Cover `resolve_target` and `resolve_base_branch` against real worktrees

**Feature**: FEAT-820 — Close the FEAT-806 §4 Test Gaps in `test_worktree_sync.py`
**Spec**: `sdd/specs/fixgroup-d188effba3ca.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:87804bdfe153`

---

## Context

Spec §3 Module 1. `issue:87804bdfe153` (major) records that
`tests/sdd_scripts/test_worktree_sync.py` never calls `worktree_sync.resolve_target`
at all — target resolution is only ever reached with `worktree_sync._git`
monkeypatched, so the orphan, primary-refusal, ambiguity and Git-top-level-mismatch
branches of `resolve_target` (`worktree_sync.py:151-168`) have no coverage. The same
is true for the per-spec-index and brief-frontmatter branches of
`resolve_base_branch` (`worktree_sync.py:189-216`); only the hotfix refusal path is
covered today by `test_hotfix_slug_candidates_handle_hyphenated_keys`.

This task is first in the chain because it introduces `_as_primary`, the helper every
later task in FEAT-820 needs in order to point target discovery at a disposable
repository instead of the real one.

---

## Scope

- Add the module-level helper `_as_primary(monkeypatch, primary)` to
  `tests/sdd_scripts/test_worktree_sync.py`.
- Add `test_resolve_target_feat_id_and_ambiguity`.
- Add `test_orphan_and_mismatched_git_root_refused`.
- Add `test_base_branch_from_index_and_brief`.
- Append all four at the end of the file under a FEAT-820 banner comment.

**NOT in scope**:
- Any change to `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` or
  `remove_worktree.py` — this feature adds tests only (spec §1 Non-Goals).
- Live-process guards, never-pushes, the stale-base advisory (TASK-5236).
- Sandbox push protection and `gh` failures (TASK-5237).
- `main()` exit-code mapping (TASK-5238).
- Touching, renaming or reordering any test that already exists in the file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_worktree_sync.py` | MODIFY | Append the `_as_primary` helper and three resolution tests at EOF |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# already present at tests/sdd_scripts/test_worktree_sync.py:14 — do NOT re-import
from parrot.sdd.scripts import native_claude_sandbox, worktree_sync

# NEW import this task must add to the existing import block
from parrot.sdd.scripts import remove_worktree  # verified: packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py:1
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py
EXIT_OK, EXIT_TARGET, EXIT_DIRTY, EXIT_LIVE, EXIT_TRANSPORT, EXIT_CONFLICT = 0, 2, 3, 4, 5, 6  # line 24
class SyncError(Exception):                                       # line 51 — attribute: exit_code: int
def resolve_target(target: str) -> Path:                          # line 151
def resolve_base_branch(wt: Path, override: str | None) -> str:   # line 189
def _slug_candidates(wt: Path) -> list[str]:                      # line 171

# packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py
_ROOT: Path | None                                                # module global memoised by _root()
def _root() -> Path:                                              # line 63
def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:  # line 71 — cwd defaults to _root()
def discover() -> list[Worktree]:                                 # line 191 — scans _root()/".claude"/"worktrees" for orphans
def _match(worktrees: list[Worktree], target: str) -> list[Worktree]:  # line 269

# packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py
def _read_worktree_index(wt_path: Path, slug: str) -> tuple[list[WorktreeTaskStatus], str]:  # line 135
#   reads wt_path/"sdd"/"tasks"/"index"/f"{slug}.json", returns data["base_branch"] (default "dev")

# tests/sdd_scripts/test_worktree_sync.py (existing helpers — reuse verbatim)
def _run(path: Path, *args: str) -> str:                          # line 20
def _repository(tmp_path: Path) -> tuple[Path, Path, Path]:       # line 25 — (origin, primary, feature); feature branch is feat-FEAT-999-sync
def _refs(path: Path) -> str:                                     # line 184
```

Behaviour verified in the source and relied on by this task:

- `resolve_target` raises `SyncError(EXIT_TARGET, "target must resolve to one worktree (matches: …)")`
  when `_match` returns anything other than exactly one worktree (`worktree_sync.py:153-156`).
- It raises `SyncError(EXIT_TARGET, "target must be a registered non-primary linked worktree")`
  when the single match is `primary` or `not registered` (`worktree_sync.py:157-159`).
- It raises `SyncError(EXIT_TARGET, "target Git top-level does not match the registered worktree")`
  when `git rev-parse --show-toplevel` in the target does not resolve to the registered path
  (`worktree_sync.py:166-167`).
- `_slug_candidates` returns `["sync"]` for branch `feat-FEAT-999-sync`
  (`parts[0] == "feat" and len(parts) >= 4` → `["-".join(parts[3:])]`, `worktree_sync.py:181-182`).
- `_slug_candidates` returns `["1-widget", "widget"]` for branch `fix-ABC-1-widget`
  (`worktree_sync.py:183-184`), so `sdd/briefs/widget.brief.md` is the second candidate.
- `resolve_base_branch` checks the index file FIRST for each candidate slug, then the brief
  (`worktree_sync.py:195-207`); the `override` argument short-circuits both (`worktree_sync.py:192-194`).
- `sdd_meta.parse` loads `sdd/config.json` of the document's repository and falls back to
  defaults when absent. **Verified live in a temp repo with no `sdd/config.json`**: frontmatter
  `type: hotfix` / `base_branch: main` parses to `FlowMeta(type="hotfix", base_branch="main")`.

### Does NOT Exist

- ~~`remove_worktree.set_root()`~~ — there is no setter; `_ROOT` is assigned by `main()` or
  memoised by `_root()`. Use `monkeypatch.setattr(remove_worktree, "_ROOT", primary)`.
- ~~`worktree_sync.resolve_target(target, root=...)`~~ — it takes exactly one positional `str`.
- ~~`worktree_sync.resolve_base_branch(wt)`~~ — `override` is a required positional parameter.
- ~~`tests/sdd_scripts/conftest.py`~~ — this directory has no conftest; do not create one.
- ~~`worktree_sync.Worktree`~~ — the dataclass lives in `remove_worktree`, not `worktree_sync`.
- ~~a `_primary` or `_as_primary` helper already in the test file~~ — this task creates it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "tests/sdd_scripts/test_worktree_sync.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py#resolve_target",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py#resolve_base_branch",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#discover"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

Copy the style of the existing tests in the same file: build a real disposable
repository with `_repository(tmp_path)`, drive real `git` through `_run`, and assert on
`SyncError.exit_code` plus observable repository state. Never monkeypatch
`worktree_sync._git` in this task.

### Key Constraints

- `remove_worktree._ROOT` is a **module global**. A test that calls `discover()` without
  `_as_primary` memoises the real repository root and poisons every later test in the same
  pytest process. `monkeypatch.setattr` restores it at teardown — always go through it.
- `discover()` runs `git worktree list --porcelain` with `cwd=_root()` **and** scans
  `_root()/".claude"/"worktrees"` for orphan directories, so `_as_primary` must set both
  `_ROOT` and the process cwd.
- 120-column lines, Google-style one-line docstring on every test, `ruff check --fix` on the
  touched file before committing.
- Every test must end on a behavioural assertion — never a bare `exists()`, `st_size > 0` or
  truthiness check as the final line (spec §5).

### References in Codebase

- `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py:151` — `resolve_target`
- `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py:191` — `discover`
- `tests/sdd_scripts/test_worktree_sync.py:449` — `test_hotfix_slug_candidates_handle_hyphenated_keys`,
  the closest existing test; it shows how to add a second worktree to the disposable repo.

---

## Implementation Blueprint

### Steps (in order)

1. Add `from parrot.sdd.scripts import remove_worktree` to the existing import block at the top
   of the file — *why*: `_as_primary` must reach the `_ROOT` module global, and the file does
   not import that module yet.
2. Append a banner comment and the four blocks below at the **end of the file** — *why*:
   appending at EOF keeps this task's anchor stable while TASK-5236/5237/5238 append after it,
   so no blueprint in the chain has to re-locate a moving anchor.
3. Complete every `# FILL IN:` marker — *why*: the assertions are the deliverable; the
   scaffolding above them is mechanical.
4. Run `pytest tests/sdd_scripts/test_worktree_sync.py -q` from the worktree with an absolute
   `PYTHONPATH` — *why*: the shared venv is editable-installed against the main checkout, so a
   bare `pytest` imports the wrong branch's `parrot`.

### `tests/sdd_scripts/test_worktree_sync.py` (MODIFY — import block)

```python
# occurrences: 1 (verified: grep -c 'from parrot.sdd.scripts import native_claude_sandbox, worktree_sync' tests/sdd_scripts/test_worktree_sync.py)
# AFTER — insert below `from parrot.sdd.scripts import native_claude_sandbox, worktree_sync` (verified: tests/sdd_scripts/test_worktree_sync.py:14)
from parrot.sdd.scripts import remove_worktree
```

**Why**: `_as_primary` needs the module object to rebind its `_ROOT` global. Keep it on its own
line after the existing combined import so `ruff` leaves the block alone.

### `tests/sdd_scripts/test_worktree_sync.py` (MODIFY — append at EOF)

```python
# --- FEAT-820 / TASK-5235: target and base-branch resolution ---------------------------------------


def _as_primary(monkeypatch: pytest.MonkeyPatch, primary: Path) -> None:
    """Point worktree discovery at a disposable clone instead of the real repository.

    ``discover()`` runs ``git worktree list`` with ``cwd=_root()`` and scans
    ``_root()/.claude/worktrees`` for orphans, and ``_root()`` memoises into the module
    global ``remove_worktree._ROOT``. Both are redirected so ``resolve_target`` can only
    ever see ``primary``'s own worktrees.
    """
    monkeypatch.setattr(remove_worktree, "_ROOT", primary)
    monkeypatch.chdir(primary)


def test_resolve_target_feat_id_and_ambiguity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One match resolves; an ambiguous substring and the primary checkout both exit 2."""
    _origin, primary, feature = _repository(tmp_path)
    second = tmp_path / "second"
    _run(primary, "worktree", "add", "-b", "feat-FEAT-998-sync-extra", str(second), "dev")
    _as_primary(monkeypatch, primary)

    assert worktree_sync.resolve_target("feat-FEAT-999-sync") == feature.resolve()

    with pytest.raises(worktree_sync.SyncError) as ambiguous:
        worktree_sync.resolve_target("sync")
    # FILL IN: assert ambiguous.value.exit_code == EXIT_TARGET and that the message names BOTH
    #          worktree paths — bounded by AC "ambiguity exits 2 naming the matches"

    with pytest.raises(worktree_sync.SyncError) as primary_refused:
        worktree_sync.resolve_target("dev")
    # FILL IN: assert exit_code == EXIT_TARGET and "registered non-primary linked worktree" in the
    #          message — bounded by worktree_sync.py:157-159


def test_orphan_and_mismatched_git_root_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An orphan directory and a Git-top-level mismatch exit 2 with the primary untouched."""
    _origin, primary, _feature = _repository(tmp_path)
    orphan = primary / ".claude" / "worktrees" / "orphan-dir"
    orphan.mkdir(parents=True)
    _as_primary(monkeypatch, primary)
    before = (
        _run(primary, "rev-parse", "HEAD"),
        _run(primary, "status", "--porcelain"),
        _refs(primary),
        _run(primary, "config", "--list"),
    )

    with pytest.raises(worktree_sync.SyncError) as orphan_refused:
        worktree_sync.resolve_target("orphan-dir")
    # FILL IN: assert exit_code == EXIT_TARGET — bounded by worktree_sync.py:157-159 (not registered)

    # A registered worktree whose directory is really a different repository.
    foreign = tmp_path / "foreign"
    _run(primary, "worktree", "add", "-b", "feat-FEAT-997-foreign", str(foreign), "dev")
    # FILL IN: replace `foreign`'s contents with an INDEPENDENT git repo (git init a sibling and
    #          move/copy its .git into place, or re-init in a nested subdir and register that),
    #          so `git rev-parse --show-toplevel` inside it no longer equals `foreign`
    #          — bounded by worktree_sync.py:163-167

    with pytest.raises(worktree_sync.SyncError) as mismatched:
        worktree_sync.resolve_target("feat-FEAT-997-foreign")
    # FILL IN: assert exit_code == EXIT_TARGET and "Git top-level does not match" in the message

    assert (
        _run(primary, "rev-parse", "HEAD"),
        _run(primary, "status", "--porcelain"),
        _refs(primary),
        _run(primary, "config", "--list"),
    ) == before


def test_base_branch_from_index_and_brief(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The per-spec index, a brief's frontmatter and the --base override resolve in precedence order."""
    _origin, primary, feature = _repository(tmp_path)
    index = feature / "sdd" / "tasks" / "index"
    index.mkdir(parents=True)
    (index / "sync.json").write_text(
        json.dumps({"feature": "sync", "base_branch": "staging", "tasks": []}), encoding="utf-8"
    )

    assert worktree_sync.resolve_base_branch(feature, None) == "staging"
    assert worktree_sync.resolve_base_branch(feature, "dev") == "dev"

    brief_worktree = tmp_path / "widget"
    _run(primary, "worktree", "add", "-b", "fix-ABC-1-widget", str(brief_worktree), "dev")
    briefs = brief_worktree / "sdd" / "briefs"
    briefs.mkdir(parents=True)
    (briefs / "widget.brief.md").write_text("---\ntype: hotfix\nbase_branch: main\n---\n\n# Brief\n", encoding="utf-8")

    # FILL IN: assert resolve_base_branch(brief_worktree, None) == "main" — bounded by
    #          _slug_candidates returning ["1-widget", "widget"] so the second candidate hits
```

**Why this shape**: `_as_primary` is the single mechanism FEAT-820 introduces, and it is defined
here because TASK-5236 and TASK-5238 both consume it. The `before`/`after` tuple in the orphan test
is what proves spec AC "a refused `resolve_target` leaves the primary unchanged" — keep all four
components. The index test uses slug `sync` because branch `feat-FEAT-999-sync` yields exactly that
candidate; do not rename the branch. `json` is already imported at the top of the file (line 5).

### FILL IN checklist

- [ ] `test_resolve_target_feat_id_and_ambiguity` — ambiguity assertion names both paths; bounded by AC "ambiguity exits 2"
- [ ] `test_resolve_target_feat_id_and_ambiguity` — primary-refusal message assertion; bounded by `worktree_sync.py:157-159`
- [ ] `test_orphan_and_mismatched_git_root_refused` — orphan exit-code assertion; bounded by `worktree_sync.py:157-159`
- [ ] `test_orphan_and_mismatched_git_root_refused` — how the foreign repo is planted so `--show-toplevel` differs; bounded by `worktree_sync.py:163-167`
- [ ] `test_orphan_and_mismatched_git_root_refused` — mismatch message assertion
- [ ] `test_base_branch_from_index_and_brief` — brief resolution assertion; bounded by `_slug_candidates` returning `["1-widget", "widget"]`

---

## Acceptance Criteria

- [ ] `_as_primary` exists at module level in `tests/sdd_scripts/test_worktree_sync.py` and sets both
      `remove_worktree._ROOT` and the process cwd through `monkeypatch`.
- [ ] `test_resolve_target_feat_id_and_ambiguity`, `test_orphan_and_mismatched_git_root_refused` and
      `test_base_branch_from_index_and_brief` exist and pass.
- [ ] No test added by this task monkeypatches `worktree_sync._git`.
- [ ] The orphan/mismatch test asserts the primary's HEAD, porcelain status, refs and config are all
      unchanged across both refusals.
- [ ] `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` and `remove_worktree.py` are unchanged.
- [ ] Every pre-existing test in the file still passes and none was edited.
- [ ] `ruff check tests/sdd_scripts/test_worktree_sync.py` is clean.
- [ ] No test ends on a vacuous assertion (bare `exists()`, `st_size > 0`, length truthiness).

---

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_sync.py -q`
- `pytest tests/sdd_scripts/test_worktree_sync.py::test_resolve_target_feat_id_and_ambiguity -q`
- `pytest tests/sdd_scripts/test_worktree_sync.py::test_orphan_and_mismatched_git_root_refused -q`
- `pytest tests/sdd_scripts/test_worktree_sync.py::test_base_branch_from_index_and_brief -q`

---

## Test Specification

This task *is* the test specification — see the Implementation Blueprint. Run the validation
commands from inside the feature worktree with an absolute `PYTHONPATH`:

```bash
PYTHONPATH=$PWD/packages/ai-parrot/src pytest tests/sdd_scripts/test_worktree_sync.py -q
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug fixgroup-d188effba3ca --feature-id FEAT-820`)
2. **Read the spec** at `sdd/specs/fixgroup-d188effba3ca.spec.md` (§3 Module 1, §4, §6)
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — re-check every line number above before writing code
5. **Update status** in `sdd/tasks/index/fixgroup-d188effba3ca.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only `tests/sdd_scripts/test_worktree_sync.py`
9. **Close the task** with `parrot sdd task close TASK-5235 fixgroup-d188effba3ca verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
