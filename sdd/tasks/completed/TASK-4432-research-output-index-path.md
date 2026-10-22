# TASK-4432: `ResearchOutput.index_path` + DevelopmentNode explicit index resolution

**Feature**: FEAT-698 — /sdd-brief One-Command Brief Flow for Hotfixes and Single-Issue Fixes
**Spec**: `sdd/specs/sdd-brief-hotfix-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, design-research S3. A dev-loop hotfix run carries
`feat_id == ""`, and `DevelopmentNode._find_feature_slug` returns `None`
for that before scanning (development.py:1323-1329) — so today every hotfix
is single-agent by construction. A `--split` brief has a real per-brief
index with several `HOTFIX-*` tasks; without an explicit path the pool would
never see it. `sdd-research` (TASK-4433) will emit `index_path`; this task
adds the field and makes `_build_scheduler` honor it **before** the legacy
`feat_id` scan.

`ResearchNode` needs no change: it reads `base_branch` from the raw YAML of
`spec_path` (research.py:159-195), which works on a brief's frontmatter
(`base_branch:` key present, no `type:`).

---

## Scope

- Add `index_path: str = ""` to `ResearchOutput` (with an
  `AliasChoices("index_path", "index")` alias, matching the model's
  drift-tolerant style).
- `DevelopmentNode._build_scheduler`: when `research.index_path` is set,
  resolve it against `research.worktree_path`, **refuse paths that escape
  the worktree** (absolute or `..`-escaping → log a warning and ignore), and
  build via `TaskScheduler.from_index_file`; otherwise fall through to the
  existing `_find_feature_slug` scan unchanged.
- Tests: extend `test_empty_feat_id.py`; add a brief-frontmatter case to
  `test_research_base_branch.py`; create `test_brief_index_dispatch.py`.

**NOT in scope**: `task_scheduler.py` (TASK-4431); the sdd-research prompt
(TASK-4433); `WorkBrief`/`DevRequestBrief` (keep their shape — spec M5);
`ResearchNode` code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` | MODIFY | `ResearchOutput.index_path` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` | MODIFY | `_build_scheduler` honors `index_path` |
| `packages/ai-parrot/tests/flows/dev_loop/test_empty_feat_id.py` | MODIFY | index_path-set case |
| `packages/ai-parrot/tests/flows/dev_loop/test_research_base_branch.py` | MODIFY | brief frontmatter resolves base |
| `packages/ai-parrot/tests/flows/dev_loop/test_brief_index_dispatch.py` | CREATE | single vs split brief dispatch |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models.base import ResearchOutput  # verified: models/base.py:347
from parrot.flows.dev_loop.task_scheduler import TaskScheduler  # verified: task_scheduler.py:129
```

### Existing Signatures to Use
```python
# models/base.py — class ResearchOutput(BaseModel)                        # line 347
#   model_config = ConfigDict(populate_by_name=True)                      # line 360
#   feat_id: str = Field(..., validation_alias=AliasChoices("feat_id", "feature_id", "feat", "feature"))  # 372-376
#   worktree_path: str                                                    # 382-386
#   base_branch: str = Field(default="", ..., validation_alias=AliasChoices("base_branch", "base"),)  # 401-410
#     anchor (occurrences 1): `        validation_alias=AliasChoices("base_branch", "base"),`  # line 409

# nodes/development.py
@staticmethod
def _find_feature_slug(worktree_path: str, feat_id: str) -> Optional[str]   # line 1309
async def _build_scheduler(self, research: ResearchOutput) -> Optional[TaskScheduler]  # line 1344
#   anchor (occurrences 1):
#   `        feature_slug = await asyncio.to_thread(self._find_feature_slug, research.worktree_path, research.feat_id)`  # line 1362
#   uses asyncio.to_thread for filesystem reads (async-first rule)         # line 1360-1361 comment

# task_scheduler.py
@classmethod
def from_index_file(cls, path: Path) -> Optional["TaskScheduler"]        # line 164 — None on missing/malformed; ValueError on cycle
```

### Does NOT Exist
- ~~`ResearchOutput.index_path`~~ — created here.
- ~~`TaskScheduler.from_index_path`~~ — not created; use `from_index_file`.
- ~~`ResearchNode` support code for briefs~~ — none needed (raw-YAML base_branch read).
- ~~`WorkBrief.kind == "brief"`~~ — brief runs still enter as `kind == "bug"`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_empty_feat_id.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_research_base_branch.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_brief_index_dispatch.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py#ResearchOutput",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py#DevelopmentNode._build_scheduler",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py#DevelopmentNode._find_feature_slug",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py#TaskScheduler.from_index_file"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `index_path` defaults to `""` (not `None`) — consistent with
  `repo_path`/`base_branch` on the same model; `""` means "no explicit index".
- Containment: resolve `Path(worktree_path) / index_path`, `.resolve()` both,
  require the result to be inside the resolved worktree; otherwise warn and
  fall back to the legacy scan. LLM-produced paths are untrusted input.
- Keep the single-task behavior identical: a 1-task brief still reaches
  `_execute_single` through the existing `_collapse_for_single_task` /
  `should_fan_out` logic — do not special-case it.
- Run tests with `PYTHONPATH=packages/ai-parrot/src` from the worktree root.

---

## Implementation Blueprint

### Steps (in order)
1. Add the field — *why*: the subagent contract needs a place to carry the path.
2. Add the explicit-path branch at the top of `_build_scheduler` — *why*: S3; legacy scan stays the fallback.
3. Extend/add tests — *why*: AC-1..AC-4.

### `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        validation_alias=AliasChoices("base_branch", "base"),' models/base.py)
# AFTER — insert below the `base_branch` Field's closing `    )` that follows
#         `        validation_alias=AliasChoices("base_branch", "base"),` (verified: models/base.py:409-410)
    index_path: str = Field(
        default="",
        description=(
            "Explicit task-index path inside the worktree, e.g. "
            "'sdd/briefs/<slug>.index.json' for a FEAT-698 brief run. '' means "
            "no explicit index: DevelopmentNode falls back to the per-spec index "
            "scan keyed by feat_id."
        ),
        validation_alias=AliasChoices("index_path", "index"),
    )
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        feature_slug = await asyncio.to_thread(self._find_feature_slug, research.worktree_path, research.feat_id)' development.py)
# BEFORE — insert above that line (verified: development.py:1362)
        if research.index_path:
            explicit = await asyncio.to_thread(self._contained_index_path, research.worktree_path, research.index_path)
            if explicit is not None:
                return await asyncio.to_thread(TaskScheduler.from_index_file, explicit)
            self.logger.warning(
                "Ignoring index_path %r: it does not resolve inside worktree %s; "
                "falling back to the per-spec index scan.",
                research.index_path,
                research.worktree_path,
            )
```
```python
# AFTER — add a new staticmethod right after `_find_feature_slug` (ends development.py:1342)
    @staticmethod
    def _contained_index_path(worktree_path: str, index_path: str) -> Optional[Path]:
        """Resolve ``index_path`` against the worktree; ``None`` when it escapes it.

        Args:
            worktree_path: The run's worktree root.
            index_path: Repo-relative index path reported by sdd-research.

        Returns:
            The absolute path, or ``None`` for an absolute or worktree-escaping path.
        """
        # FILL IN: reject Path(index_path).is_absolute(); root = Path(worktree_path).resolve();
        #          candidate = (root / index_path).resolve(); return candidate only if
        #          candidate == root or root in candidate.parents — bounded by AC-3
        raise NotImplementedError
```
**Why**: the explicit branch sits before the `feat_id` scan so a brief's
`feat_id == ""` never short-circuits it; returning `from_index_file`'s
`None` on a missing file preserves the documented "degrade to single-agent"
signal.

### Test blocks
```python
# packages/ai-parrot/tests/flows/dev_loop/test_brief_index_dispatch.py (CREATE)
"""Brief runs reach the scheduler through ResearchOutput.index_path — FEAT-698 / TASK-4432."""
# FILL IN: build ResearchOutput(feat_id="", index_path="sdd/briefs/demo-fix.index.json", ...) over a
#          tmp worktree; follow test_development_node.py's DevelopmentNode construction pattern;
#          assert await node._build_scheduler(research) has 2 tasks for a split brief (AC-1) and
#          that a 1-task brief still dispatches single-agent (AC-2); assert "../x.json" and an
#          absolute path are ignored with a warning (AC-3)

# test_empty_feat_id.py (MODIFY) — APPEND
# FILL IN: test_empty_feat_id_with_index_path_builds_scheduler — feat_id "" + index_path set ⇒ not None;
#          keep test_empty_feat_id_returns_none_without_matching untouched (AC-4)

# test_research_base_branch.py (MODIFY) — APPEND
# FILL IN: test_brief_frontmatter_resolves_base_branch — spec_path points at a brief file whose
#          frontmatter is `kind: brief` + `base_branch: main` (no `type:`); assert resolved "main" (AC-5)
```

### FILL IN checklist
- [ ] `_contained_index_path` body — AC-3
- [ ] dispatch tests — AC-1..AC-3
- [ ] empty-feat_id + index_path test — AC-4
- [ ] brief frontmatter base-branch test — AC-5

---

## Acceptance Criteria

- [ ] AC-1: `feat_id=""` + `index_path` → a 2-task brief index yields a scheduler with both `HOTFIX-*` tasks.
- [ ] AC-2: a 1-task brief still runs the single-agent path.
- [ ] AC-3: absolute or `..`-escaping `index_path` values are ignored with a warning; the legacy scan runs.
- [ ] AC-4: `feat_id=""` and no `index_path` → still `None` (existing guard intact).
- [ ] AC-5: `ResearchNode` resolves `base_branch` from a brief's frontmatter.
- [ ] `ResearchOutput(index="x")` validates via the alias; serialization uses `index_path`.
- [ ] Existing `test_development_node.py`, `test_flow_type_override.py` pass unchanged.
- [ ] `ruff check` clean on modified files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_brief_index_dispatch.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_empty_feat_id.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_research_base_branch.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_development_node.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_flow_type_override.py -q`

---

## Test Specification

See "Test blocks" above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-brief-hotfix-flow --feature-id FEAT-698`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/sdd-brief-hotfix-flow.json`
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4432 sdd-brief-hotfix-flow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
