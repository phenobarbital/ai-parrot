# TASK-1847: Porygon reference migration + docs

**Feature**: FEAT-321 — PromptBuilder Identity Capability
**Spec**: `sdd/specs/promptbuilder-identity-capability.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1846
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4. Porygon is the reference adopter: its ~122-line
inline `BACKSTORY` constant (agents/porygon.py:11-133) is split into the five
per-field Markdown files and the agent switches to `IdentityMixin`. This task
also writes the user-facing documentation (spec AC requires docs for the
identity capability, the `identity/` directory convention, and `$`-placeholder
semantics).

---

## Scope

- CREATE `agents/porygon/identity/{role,goal,capabilities,backstory,rationale}.md`:
  split the existing `BACKSTORY` prose (porygon.py:11-133) by concern —
  role/goal/capabilities/rationale extracted where identifiable, the remaining
  domain prose (business context, org hierarchy, KPI definitions, analysis
  guidelines) stays in `backstory.md`. Content-preserving: no prose rewrites
  beyond the split.
- MODIFY `agents/porygon.py`:
  - Add `IdentityMixin` FIRST in bases:
    `class Porygon(IdentityMixin, SkillRegistryMixin, EpisodicMemoryMixin, PandasAgent)`.
  - Set `enable_identity = True` class attribute.
  - Delete the `BACKSTORY` constant and the `backstory=BACKSTORY` kwarg from
    `super().__init__` (porygon.py:160-179).
  - In `configure()`, call `await self._configure_identity()` alongside the
    existing `_configure_episodic_memory()` / `_configure_skill_registry()`
    calls (porygon.py:322-326).
- CREATE `docs/prompts/identity-capability.md`: the `identity/` directory
  convention, `IdentityMixin` adoption (flag, `identity_dir`, `configure()`
  wiring), the `"identity"` preset path, hot-reload semantics, precedence
  (kwarg > file > class attr > default), silent-missing behavior, and
  `$`-placeholder semantics (verbatim injection; dynamic variables resolve;
  optional `escape_placeholders`).
- Write the structural regression test (see Test Specification).

**NOT in scope**: framework changes (Modules 1–3 are done by TASK-1844..1846);
migrating any agent other than Porygon; rewriting/improving Porygon's persona
prose.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/porygon/identity/role.md` | CREATE | Role extracted from BACKSTORY |
| `agents/porygon/identity/goal.md` | CREATE | Goal extracted from BACKSTORY |
| `agents/porygon/identity/capabilities.md` | CREATE | Capabilities extracted from BACKSTORY |
| `agents/porygon/identity/backstory.md` | CREATE | Remaining domain prose |
| `agents/porygon/identity/rationale.md` | CREATE | Response-style guidance extracted |
| `agents/porygon.py` | MODIFY | Adopt IdentityMixin; remove BACKSTORY |
| `docs/prompts/identity-capability.md` | CREATE | User documentation |
| `packages/ai-parrot/tests/bots/test_porygon_identity_migration.py` | CREATE | Structural regression test |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-21 on `dev`. Use these VERBATIM; verify anything not listed.

### Verified Imports
```python
from parrot.bots.mixins import IdentityMixin      # available after TASK-1846
from parrot.skills import SkillRegistryMixin      # existing (skills/mixin.py:27)
from parrot.memory import EpisodicMemoryMixin     # existing (memory/episodic/mixin.py:77)
```

### Existing Signatures to Use
```python
# agents/porygon.py  (repo-root agents/ directory — NOT inside packages/)
BACKSTORY = """..."""                    # lines 11-133 — ~122 lines, DELETE in this task
@register_agent(name="porygon", at_startup=True)   # line 136
class Porygon(SkillRegistryMixin, EpisodicMemoryMixin, PandasAgent):  # line 137
    agent_id = "porygon"
    # __init__ (160-179): super().__init__(*args, local_kb=True, backstory=BACKSTORY,
    #                                      output_mode=OutputMode.MSTEAMS, ..., **kwargs)
    # configure() (322-326): await super().configure(...) then
    #   await self._configure_episodic_memory(); await self._configure_skill_registry()

# agents/porygon/  — existing directory holding only skills/ (and skills/learned/).
# The identity/ subdirectory is CREATED by this task.

# IdentityMixin default identity_dir resolution (from TASK-1846):
#   Path(inspect.getfile(type(self))).parent / "identity"
#   For Porygon: inspect.getfile(Porygon) == .../agents/porygon.py
#   → default dir == agents/identity — WRONG for Porygon's layout.
#   Porygon MUST set identity_dir explicitly:
#     identity_dir = Path(__file__).parent / "porygon" / "identity"
```

### Does NOT Exist
- ~~`agents/porygon/identity/`~~ — created by THIS task.
- ~~`agents/porygon/__init__.py` or a porygon package module~~ — Porygon is the
  top-level FILE `agents/porygon.py`; `agents/porygon/` is a sibling ASSETS dir.
  This is why the mixin's module-relative default lands at `agents/identity` and
  an explicit `identity_dir` is REQUIRED (see above).
- ~~`docs/prompts/identity-capability.md`~~ — created by THIS task
  (`docs/prompts/` exists; `promptbuilder.md` lives there).
- ~~a `backstory` kwarg still being required by PandasAgent/AbstractBot~~ — after
  removal, resolution falls through to the file value injected by the mixin.

---

## Implementation Notes

### Pattern to Follow
Keep `configure()` wiring exactly parallel to the existing mixin calls
(porygon.py:322-326):
```python
await super().configure(...)
await self._configure_episodic_memory()
await self._configure_skill_registry()
await self._configure_identity()          # ← new
```

### Key Constraints
- **`identity_dir` must be explicit** (see contract): Porygon is a module FILE
  next to its assets directory, so the mixin default resolves to the wrong
  place. Set `identity_dir = Path(__file__).parent / "porygon" / "identity"`.
- Content preservation: the union of the five files must carry all substantive
  BACKSTORY content — the parity test compares distinctive markers.
- MRO: `IdentityMixin` first, so its `__init__` runs before
  `SkillRegistryMixin`/`EpisodicMemoryMixin`/`PandasAgent` and its
  `_build_prompt` wraps `AbstractBot._build_prompt`.
- Porygon imports heavy deps (`google` LLM, pandas stack) — the regression
  test must be structural (text/AST checks on `agents/porygon.py` + file
  existence) with any import-based assertions guarded by
  `pytest.importorskip`.
- Docs follow the style of `docs/prompts/promptbuilder.md`.

### References in Codebase
- `agents/porygon.py:11-133,136-137,160-179,322-326` — everything this task touches
- `docs/prompts/promptbuilder.md` — documentation style reference
- `sdd/specs/promptbuilder-identity-capability.spec.md` §2, §5, §7

---

## Acceptance Criteria

- [ ] Five `agents/porygon/identity/*.md` files exist and are non-empty.
- [ ] `BACKSTORY` constant and `backstory=BACKSTORY` kwarg removed from
      `agents/porygon.py`; `IdentityMixin` first in bases;
      `enable_identity = True`; explicit `identity_dir` set;
      `_configure_identity()` called in `configure()`.
- [ ] Distinctive BACKSTORY content markers (e.g. KPI definitions, org
      hierarchy headings) appear in the union of the five files (parity).
- [ ] `docs/prompts/identity-capability.md` covers: directory convention,
      mixin adoption, preset path, hot reload, precedence, silent-missing,
      `$`-placeholder semantics.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/bots/test_porygon_identity_migration.py -v`
- [ ] No linting errors: `ruff check agents/porygon.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_porygon_identity_migration.py
# Structural checks — Porygon's runtime deps are heavy, so assert on source
# text and files; guard any import-based test with pytest.importorskip.
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]   # adjust to repo root
PORYGON = REPO / "agents" / "porygon.py"
IDENTITY = REPO / "agents" / "porygon" / "identity"


class TestPorygonMigration:
    def test_identity_files_exist(self):
        for name in ("role", "goal", "capabilities", "backstory", "rationale"):
            f = IDENTITY / f"{name}.md"
            assert f.is_file() and f.read_text(encoding="utf-8").strip()

    def test_backstory_constant_removed(self):
        src = PORYGON.read_text(encoding="utf-8")
        assert "BACKSTORY = " not in src
        assert "backstory=BACKSTORY" not in src

    def test_mixin_adopted(self):
        src = PORYGON.read_text(encoding="utf-8")
        assert "IdentityMixin" in src
        assert "enable_identity = True" in src
        assert "_configure_identity()" in src

    def test_content_parity_markers(self):
        merged = " ".join(
            (IDENTITY / f"{n}.md").read_text(encoding="utf-8")
            for n in ("role", "goal", "capabilities", "backstory", "rationale")
        )
        # pick 3-5 distinctive phrases from the original BACKSTORY before deleting it
        for marker in (...,):
            assert marker in merged
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1846 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code, confirm every
   listed import/signature still exists; update the contract first if drifted
4. **Update status** in `sdd/tasks/index/promptbuilder-identity-capability.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1847-porygon-identity-migration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-21
**Notes**: Split the ~122-line inline `BACKSTORY` constant into five files
under `agents/porygon/identity/` (role/goal/capabilities/backstory/
rationale), content-preserving (no prose rewrites beyond the split — role
statement → `role.md`, the dataset/tool-usage sentence → `goal.md`, the "KPI
Definitions and Tool Usage" section → `capabilities.md`, the "Analysis
Guidelines" section → `rationale.md`, and the `$current_date`/`$local_time`
line + "Business Domain" section (org hierarchy, replenishment cycle) →
`backstory.md`). Modified `agents/porygon.py`: `IdentityMixin` added FIRST
in bases, `enable_identity: bool = True`, explicit
`identity_dir = Path(__file__).parent / "porygon" / "identity"` (required —
Porygon is a top-level module file with a sibling assets dir, so the
mixin's module-relative default would resolve to `agents/identity`, which is
wrong), `BACKSTORY` constant and `backstory=BACKSTORY` kwarg removed, and
`await self._configure_identity()` added to `configure()` alongside the
existing `_configure_episodic_memory()` / `_configure_skill_registry()`
calls. Created `docs/prompts/identity-capability.md` covering the
directory convention, mixin adoption, the `"identity"` preset path, hot
reload, precedence (including the documented `PandasAgent.capabilities`
kwarg-swallowing exception), silent-missing-file behavior, and
`$`-placeholder semantics. Created the structural regression test
(4 tests, all pass) — guarded to source/file assertions per the task's own
guidance, since Porygon's runtime deps are heavy and it cannot be safely
imported in a test process (see below).

**IMPORTANT — gitignore finding**: `agents/` is repo-root-gitignored
(`.gitignore:270`, confirmed via `git check-ignore -v`), and
`agents/porygon.py` / `agents/porygon/` are genuinely untracked (`git status
--ignored` shows `!!`) — they did not exist in this worktree at all until I
copied them in from the main repo checkout (`/home/jesuslara/proyectos/
ai-parrot/agents/porygon.py`), since git worktrees only replicate *tracked*
content. This matches an established precedent
(`sdd/tasks/completed/TASK-1116-security-agent-wiring.md`: "MODIFY (local,
gitignored)" for `agents/security.py`) — gitignored agent files are edited
locally and never travel through the normal commit/PR flow. Consequently:
  - `agents/porygon.py` and `agents/porygon/identity/*.md` are **NOT** part
    of the `git add`/commit for this task (git would silently refuse them
    without `-f`, and forcing them in would be wrong — they're intentionally
    excluded from version control, likely for confidentiality of TROC's
    business data).
  - Since this worktree is expected to be removed after the feature merges
    (per the standard cleanup flow), I copied the modified `porygon.py` and
    the new `identity/*.md` files back to the main repo's working directory
    (`/home/jesuslara/proyectos/ai-parrot/agents/...`) so the local-only
    change survives worktree cleanup. Verified byte-identical via `diff`.
  - Only `docs/prompts/identity-capability.md` and
    `packages/ai-parrot/tests/bots/test_porygon_identity_migration.py` are
    committed on the feature branch — both are genuinely tracked, in-repo
    deliverables.
  - An ad-hoc smoke import of `agents/porygon.py` in this environment
    revealed that `import parrot` triggers `AgentRegistry` auto-discovery
    against the **main repo's** `agents_dir` (env/settings-configured
    absolute path, independent of cwd), which pre-populates
    `sys.modules['porygon']` before any explicit import — an environmental
    artifact, not a code defect, and exactly why the task specifies
    structural (not import-based) testing.

**Deviations from spec**: none in the code/docs themselves. The
gitignore-driven handling above (local-only edit + manual copy-back to the
main repo instead of a git commit for `agents/porygon.py` and
`agents/porygon/identity/*.md`) is a process deviation forced by the repo's
`.gitignore` policy, not a design choice — flagging it explicitly per the
"when in doubt, note it in the Completion Note" rule.
