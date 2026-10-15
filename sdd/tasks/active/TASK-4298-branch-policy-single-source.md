# TASK-4298: One source for the SDD branch policy in core (sdd_meta)

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.2, §3 M6 amendment **C8**)
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Amendment C8 of `sdd/proposals/parrot-installer-amendments.proposal.md` (§2.2-5, §3 C8;
approved 2026-10-14). The branch policy of the Git Parrot Flow is defined **four** times:

| Copy | Where | Why it exists |
|---|---|---|
| `KNOWN_BRANCHES`, `WORK_KIND_FLOW`, `FlowMeta._hotfix_implies_main`, `parse()` default, `resolve_flow()` fallback | `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:30,35,106,152,314-315` | the authoritative module (re-exported by `scripts/sdd/sdd_meta.py`) |
| `_LONG_LIVED_BRANCHES` | `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/base.py:44` | "LOCAL copy of scripts.sdd.sdd_meta.KNOWN_BRANCHES — NOT an import" (TASK-2504: `scripts.sdd` was not importable from the package) |
| `_WORK_KIND_BASE_BRANCH` + `_parse_flow_frontmatter` | `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py:63,159` | same reason (TASK-2504) |
| `_parse_flow_frontmatter` (second copy) | `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py:69`, used at `:391` with `or "dev"` | TASK-2505: `research.py` was not in that task's file list |

The reason for the copies no longer holds: the authoritative module now lives in core
(`parrot.knowledge.wiki.ledger.sdd_meta`), importable from the installed package. Once
amendment C6 (TASK-4299) makes the policy configurable per repo, every hardcoded copy
would silently ignore the configuration. This task collapses the copies **first**, with
behaviour unchanged, so TASK-4299 has exactly one place to parameterize.

The two dev-loop callers rely on a distinction that must survive: `None` when a document
declares **no** branch (missing file, no frontmatter, malformed YAML, non-string/empty
value) versus the `"dev"` default they apply themselves. FEAT-583's
`read_declared_base_branch(doc_path) -> str | None` is the shape that keeps it.

---

## Scope

- Add to `knowledge/wiki/ledger/sdd_meta.py`:
  - `DEFAULT_FEATURE_BASE: str = "dev"` and `DEFAULT_HOTFIX_BASE: str = "main"`;
    `WORK_KIND_FLOW`, `parse()`'s default, `resolve_flow()`'s fallback and
    `_hotfix_implies_main` use the constants instead of literals (values unchanged).
  - `read_declared_base_branch(doc_path: Path) -> str | None`: the body of today's
    `nodes/research.py:_parse_flow_frontmatter`, built on the existing
    `_read_frontmatter()` plus an `OSError`/`yaml.YAMLError` guard; returns `None` for
    missing file, no frontmatter, malformed YAML, non-mapping block, or a non-string /
    empty `base_branch`; never raises.
- `nodes/base.py`: delete `_LONG_LIVED_BRANCHES`; import `KNOWN_BRANCHES` from
  `parrot.knowledge.wiki.ledger.sdd_meta` and use it where `_LONG_LIVED_BRANCHES` was used
  (`:153` docstring, `:179`). Keep the `siblings` parameter semantics.
- `nodes/research.py`: delete `_WORK_KIND_BASE_BRANCH` and `_parse_flow_frontmatter`;
  use `read_declared_base_branch(spec_path)` at `:615` and
  `WORK_KIND_FLOW.get(kind, ("feature", DEFAULT_FEATURE_BASE))[1]` at `:618`. Drop the
  now-unused `yaml` import (and `Dict` if unused).
- `nodes/feature_handoff.py`: delete `_parse_flow_frontmatter`; `:391` becomes
  `read_declared_base_branch(spec_path) or DEFAULT_FEATURE_BASE`. Drop the unused `yaml`
  import.
- `scripts/sdd/sdd_meta.py`: add `DEFAULT_FEATURE_BASE`, `DEFAULT_HOTFIX_BASE`,
  `read_declared_base_branch` to the re-export list (`# noqa: F401` block).
- Tests (two new files, see Test Specification).

**NOT in scope**:
- Reading `sdd/config.json` or any configuration (TASK-4299 adds the `config` hook).
- Changing `FlowMeta`'s fields, `emit()`, `plan_worktree()`, `resolve_flow()`'s precedence
  or any CLI output of `scripts/sdd/*`.
- Touching `.claude/`, `sdd/` markdown, or the TASK-4085 move of `sdd_meta` into
  `parrot.sdd.scripts` (that task re-exports whatever this module exports).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` | MODIFY | constants + `read_declared_base_branch`; literals → constants |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/base.py` | MODIFY | `_LONG_LIVED_BRANCHES` → `KNOWN_BRANCHES` import |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` | MODIFY | remove both local copies; use `sdd_meta` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py` | MODIFY | remove local copy; use `sdd_meta` |
| `scripts/sdd/sdd_meta.py` | MODIFY | re-export the three new names |
| `tests/sdd_scripts/test_sdd_meta_branch_policy.py` | CREATE | `read_declared_base_branch` + constants |
| `packages/ai-parrot/tests/flows/dev_loop/test_branch_policy_single_source.py` | CREATE | callers use the single definition |

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` @ `ad54fde59` (2026-10-14).

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.sdd_meta import (          # sdd_meta.py
    KNOWN_BRANCHES,      # :30  frozenset({"main", "staging", "dev"})
    WORK_KIND_FLOW,      # :35  {"bug": ("hotfix", "main"), "enhancement": ("feature", "dev"), "new_feature": ("feature", "dev")}
    FlowMeta,            # :99  (type: Literal["feature","hotfix"], base_branch: str)
    parse,               # :129 -> FlowMeta; default FlowMeta(type="feature", base_branch="dev") at :152
    resolve_flow,        # :263 -> FlowMeta; `final_base = base_branch_override or resolved_base or "dev"` at :315
    _read_frontmatter,   # :112 -> dict | None (None: no leading ---, unterminated, non-mapping)
)
import yaml                                                   # already imported by sdd_meta.py:20
```

### Existing Signatures
```python
# nodes/base.py
_LONG_LIVED_BRANCHES: frozenset[str] = frozenset({"main", "staging", "dev"})   # :44 — DELETE
candidates = [s for s in (siblings if siblings is not None else _LONG_LIVED_BRANCHES) if s != base]  # :179

# nodes/research.py
_WORK_KIND_BASE_BRANCH: Dict[str, str] = {"bug": "main", "enhancement": "dev", "new_feature": "dev"}  # :63 — DELETE
def _parse_flow_frontmatter(spec_path: Path) -> Optional[str]:   # :159 — DELETE (body moves to sdd_meta)
resolved = _parse_flow_frontmatter(spec_path)                     # :615
resolved = _WORK_KIND_BASE_BRANCH.get(kind, "dev")                # :618

# nodes/feature_handoff.py
def _parse_flow_frontmatter(spec_path: Path) -> Optional[str]:   # :69 — DELETE
return _parse_flow_frontmatter(spec_path) or "dev"                # :391

# scripts/sdd/sdd_meta.py — pure re-export shim (15 names), lines 10-26
```

### Does NOT Exist (create here)
- ~~`read_declared_base_branch`~~ — FEAT-583's name; never implemented. New in this task.
- ~~`DEFAULT_FEATURE_BASE` / `DEFAULT_HOTFIX_BASE`~~ — new in this task.
- ~~`packages/ai-parrot/tests/knowledge/wiki/ledger/`~~ — does not exist; `sdd_meta` tests live in
  `tests/sdd_scripts/` (`test_sdd_meta_resolve_flow.py`, `test_worktree_plan.py`,
  `test_command_contracts.py`). Put the new `sdd_meta` test there.
- ~~`packages/ai-parrot/tests/sdd/`~~ — created by TASK-4085; do not use it here.

Tests that reference the deleted names: none import them. Only
`packages/ai-parrot/tests/flows/dev_loop/test_base_branch_guard.py:184` mentions
`_LONG_LIVED_BRANCHES` in a docstring — update the docstring to `KNOWN_BRANCHES`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/nodes/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py", "action": "MODIFY"},
    {"path": "scripts/sdd/sdd_meta.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_base_branch_guard.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_sdd_meta_branch_policy.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_branch_policy_single_source.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#KNOWN_BRANCHES",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#WORK_KIND_FLOW",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#FlowMeta",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#parse",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#resolve_flow",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#_read_frontmatter",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/base.py#assert_base_is_clean",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py#_parse_flow_frontmatter",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py#_parse_flow_frontmatter"
  ]
}
```

---

## Implementation Notes

- **Behaviour is frozen.** Every existing test in `tests/sdd_scripts/` and
  `packages/ai-parrot/tests/flows/dev_loop/` must pass unmodified (except the one
  docstring). The values of the constants are today's literals.
- **`None` vs default.** `read_declared_base_branch` must return `None` exactly when
  today's `_parse_flow_frontmatter` does; the callers keep their own `or DEFAULT_FEATURE_BASE`
  / kind-mapping fallback. Do not fold the default into the new function.
- **Import direction.** `flows/dev_loop/nodes/*` → `knowledge/wiki/ledger/sdd_meta` is a
  new edge; `sdd_meta` imports only `yaml`, `pydantic`, stdlib. Verify no cycle:
  `python -c "import parrot.knowledge.wiki.ledger.sdd_meta"` and
  `python -c "import parrot.flows.dev_loop.nodes.research"` both succeed.
- **Stale comments.** Remove the "LOCAL copy … NOT an import" comment in `base.py:40-43`
  and the TASK-2504/2505 docstring paragraphs that justify the duplicates.
- **TASK-4299 hook.** Keep `parse()` / `resolve_flow()` signatures unchanged here; TASK-4299
  adds the `config` keyword and makes the constants the *fallback* when no config exists.

---

## Implementation Blueprint

```python
# knowledge/wiki/ledger/sdd_meta.py — additions (after KNOWN_BRANCHES, before WORK_KIND_FLOW)
#: Default base branch for feature work and the mandatory base for hotfixes
#: (Git Parrot Flow, FEAT-187). TASK-4299 makes them configurable per repo.
DEFAULT_FEATURE_BASE: str = "dev"
DEFAULT_HOTFIX_BASE: str = "main"

WORK_KIND_FLOW: dict[str, tuple[str, str]] = {
    "bug": ("hotfix", DEFAULT_HOTFIX_BASE),
    "enhancement": ("feature", DEFAULT_FEATURE_BASE),
    "new_feature": ("feature", DEFAULT_FEATURE_BASE),
}
# FlowMeta._hotfix_implies_main: compare against DEFAULT_HOTFIX_BASE (message text unchanged).
# parse(): `return FlowMeta(type="feature", base_branch=DEFAULT_FEATURE_BASE)`
# resolve_flow(): `final_base = base_branch_override or resolved_base or DEFAULT_FEATURE_BASE`


def read_declared_base_branch(doc_path: Path) -> str | None:
    """Return the ``base_branch`` a document's YAML frontmatter declares, or ``None``.

    ``None`` means "nothing declared": the file is missing or unreadable, has no leading
    frontmatter block, the YAML is malformed, the block is not a mapping, or
    ``base_branch`` is absent, not a string, or blank. Callers decide the default —
    this function never does and never raises.
    """
    try:
        block = _read_frontmatter(doc_path)
    except (OSError, yaml.YAMLError):
        return None
    if not block:
        return None
    value = block.get("base_branch")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()
```

```python
# nodes/research.py:615-618 (after)
            resolved = read_declared_base_branch(spec_path)
            if resolved is None:
                kind = getattr(brief, "kind", None)
                resolved = WORK_KIND_FLOW.get(kind, ("feature", DEFAULT_FEATURE_BASE))[1]
# nodes/feature_handoff.py:391 (after)
        return read_declared_base_branch(spec_path) or DEFAULT_FEATURE_BASE
# nodes/base.py:179 (after)
    candidates = [s for s in (siblings if siblings is not None else KNOWN_BRANCHES) if s != base]
```

---

## Acceptance Criteria

- [ ] `grep -rn "_LONG_LIVED_BRANCHES\|_WORK_KIND_BASE_BRANCH\|def _parse_flow_frontmatter" packages/ai-parrot/src` returns nothing.
- [ ] `grep -n '"dev"\|"main"' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` matches only the two constant definitions and `KNOWN_BRANCHES`.
- [ ] `read_declared_base_branch` returns `None` for: missing file, file without `---`, unterminated block, malformed YAML, non-mapping block, missing key, non-string value, blank value; returns the stripped string otherwise.
- [ ] `scripts.sdd.sdd_meta` re-exports the three new names; the 15 existing names are unchanged.
- [ ] All of `tests/sdd_scripts/` and `packages/ai-parrot/tests/flows/dev_loop/` pass; `ruff check` passes on every touched file (no unused `yaml`/`Dict` imports).
- [ ] No cyclic import between `parrot.knowledge.wiki.ledger.sdd_meta` and `parrot.flows.dev_loop.nodes.*`.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest tests/sdd_scripts/test_sdd_meta_branch_policy.py -q`
- `pytest tests/sdd_scripts/test_sdd_meta_resolve_flow.py -q`
- `pytest tests/sdd_scripts/test_worktree_plan.py -q`
- `pytest tests/sdd_scripts/test_command_contracts.py -q`
- `pytest tests/sdd_scripts/test_ensure_worktree.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_branch_policy_single_source.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_base_branch_guard.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_flow_type_override.py -q`

Also, outside the pytest contract: `ruff check` on every touched source file, and
`grep -rn "_LONG_LIVED_BRANCHES\|_WORK_KIND_BASE_BRANCH\|def _parse_flow_frontmatter" packages/ai-parrot/src`
must find nothing.

---

## Test Specification

### `tests/sdd_scripts/test_sdd_meta_branch_policy.py` (CREATE)
- `test_constants_match_known_branches`: both defaults are members of `KNOWN_BRANCHES`; `WORK_KIND_FLOW["bug"] == ("hotfix", DEFAULT_HOTFIX_BASE)`.
- `test_read_declared_returns_value` (`tmp_path` doc with `base_branch: staging`) → `"staging"`.
- Parametrized `test_read_declared_returns_none_for`: missing file; no frontmatter; `---` only (unterminated); malformed YAML (`base_branch: [`); list body; no key; `base_branch: 3`; `base_branch: "  "`.
- `test_resolve_flow_default_uses_constant`: `resolve_flow()` → `FlowMeta(type="feature", base_branch=DEFAULT_FEATURE_BASE)`.
- `test_shim_reexports_new_names`: `from scripts.sdd.sdd_meta import read_declared_base_branch, DEFAULT_FEATURE_BASE, DEFAULT_HOTFIX_BASE`.

### `packages/ai-parrot/tests/flows/dev_loop/test_branch_policy_single_source.py` (CREATE)
- `test_no_local_copies`: the three node modules expose none of the deleted names (`hasattr` checks).
- `test_base_siblings_default_is_known_branches`: `nodes.base` has no `_LONG_LIVED_BRANCHES`; `assert_base_is_clean` default siblings come from `KNOWN_BRANCHES` (monkeypatch `KNOWN_BRANCHES` in `sdd_meta`? — no: the import is by name, so instead call with `siblings=None` against a fixture repo as `test_base_branch_guard.py:184-188` does and assert the fetched refs are `KNOWN_BRANCHES - {base}`).
- `test_feature_handoff_fallback`: spec without frontmatter → `"dev"` (`DEFAULT_FEATURE_BASE`); spec with `base_branch: staging` → `"staging"` (reuse the `_spec` helper pattern of `test_flow_type_override.py:59`).
- `test_research_kind_mapping_fallback`: unreadable spec + `kind="bug"` → `"main"`; unknown kind → `"dev"`.

---

## Agent Instructions

1. Read `sdd_meta.py` fully and the three node files around the cited lines; re-run the
   `grep -n` anchors before editing (lines drift).
2. Edit `sdd_meta.py` first; run `tests/sdd_scripts` — must stay green before touching callers.
3. Replace the callers; delete the local copies and their justification comments; fix imports.
4. Add the two test files; run the Validation Commands; `ruff check --fix` touched files.
5. Commit only the listed files: `feat(parrot-installer): TASK-4298 — one source for the SDD branch policy in core`.
6. Close with `scripts/sdd/close_task.sh TASK-4298 parrot-installer verified`.

---

## Completion Note

_(filled in by close_task.sh / the implementing agent)_
