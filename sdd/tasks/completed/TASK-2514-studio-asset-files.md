# TASK-2514: Asset file management — identity / kb / skills CRUD

**Feature**: FEAT-467 — Agent Studio — Management API
**Spec**: `sdd/specs/agentstudio-management.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2511
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. Users edit an agent's on-disk assets through the API:
`AGENTS_DIR/<agent>/identity/*.md` (five canonical files),
`AGENTS_DIR/<agent>/kb/*.md|txt`, and `AGENTS_DIR/<agent>/skills/*`
(single-file and composite layouts). Changes take effect after a reload —
responses flag `reload_required`.

---

## Scope

- Implement `StudioFilesHandler(StudioBaseView)` in
  `handlers/studio/files.py`:
  - `GET /api/v1/astudio/agents/{name}/files/{kind}` — list files of a kind.
  - `GET/PUT/DELETE .../files/{kind}/{filename}` — read/write/delete one
    file. `kind ∈ {identity, kb, skills}` (400 otherwise).
- Per-kind rules:
  - `identity`: filename must be one of the five canonical
    `IDENTITY_FILES` + `.md` (400 listing them otherwise).
  - `kb`: `.md`/`.txt` only (matches what `configure_local_kb` scans).
  - `skills`: single-file `<name>.md` or composite `<name>/SKILL.md` +
    assets; on PUT of a skill file, validate with `parse_skill_file`
    (tmp-file parse) → 422 with the parser message on failure.
- Traversal-safe resolution (helper from TASK-2511); ownership enforced;
  every mutating response includes `reload_required: true`.
- Deleting a file the live agent uses is allowed (flagged), never blocked.
- Routes + tests.

**NOT in scope**: triggering the reload itself (client calls the TASK-2512
endpoint); the shared skills CATALOG (TASK-2515 — this task is per-agent
files only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/files.py` | CREATE | files handler |
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | add routes |
| `packages/ai-parrot-server/tests/studio/test_files.py` | CREATE | kind rules + traversal tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.prompts.identity import IDENTITY_FILES, load_identity  # identity.py:27,51
from parrot.skills.parsers import parse_skill_file                      # skills/parsers.py:37
from parrot.skills.parsers import parse_skill_directory                 # skills/parsers.py:109
from parrot.conf import AGENTS_DIR                                      # conf.py:175
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/prompts/identity.py
IDENTITY_FILES: tuple[str, ...] = ("role", "goal", "capabilities",
                                   "backstory", "rationale")  # :27
def load_identity(directory, *, escape_placeholders: bool = False) -> IdentityFields: ...  # :51
    # reads directory / f"{name}.md"; missing/empty → field None

# KB scan contract — parrot/bots/stores/local.py
def _get_agent_kb_directory(self) -> Optional[Path]: ...  # :41
    # Path(AGENTS_DIR) / safe_name / 'kb'  (:56); slug = name.lower().replace(' ','_')
# _get_kb_local_files :20 — glob("*.md") + glob("*.txt")

# Skills file contract — parrot/skills/parsers.py
def parse_skill_file(file_path: Path) -> SkillDefinition: ...       # :37
    # frontmatter: name*, description*, triggers key required (may be []),
    # version="1.0", category, priority=90; raises ValueError on violations
def parse_skill_directory(skill_dir: Path) -> SkillDefinition: ...  # :109  ({name}/SKILL.md)
# body token cap: SkillDefinition.MAX_TOKENS = 1000 (skills/models.py:76)
# per-agent dirs: AGENTS_DIR/{agent_id}/skills[/learned]  (skills/mixin.py:141 mkdirs both)
```

### Does NOT Exist
- ~~A file-management HTTP surface for agent assets~~ — greenfield.
- ~~`identity.md` as an identity file~~ — only the five canonical names.
- ~~A loader for `AGENTS_DIR/<name>/config.yaml`~~ — do not add config.yaml
  to the editable kinds.
- ~~Automatic reload on file write~~ — resolved decision: reload is an
  explicit separate call; this handler only flags `reload_required`.
- ~~`SkillFileRegistry` HTTP integration~~ — not needed here; validation
  is via the parsers directly.

---

## Implementation Notes

### Pattern to Follow
Resolve base dir per kind:
```python
base = Path(AGENTS_DIR) / agent_slug / kind          # identity|kb|skills
target = (base / filename).resolve()
if not target.is_relative_to(base.resolve()): -> 400
```
Skill PUT validation: write to a scratch tmp file, `parse_skill_file`, on
`ValueError` → 422 with the message; only then move into place.

### Key Constraints
- Agent slug validated (`^[a-z0-9_-]+$`); agent existence checked against
  the registry/manager (404 for unknown agent).
- Composite skills: PUT of `skills/{name}/SKILL.md` and asset files under
  `skills/{name}/...` both allowed; `SKILL.md` validated, assets not.
- mkdir parents on first write of a kind dir.
- Responses: `{path, kind, size, reload_required}`.

### References in Codebase
- `agents/porygon/identity/` — real identity dir example (5 files).
- `.agent/skills/` composite layouts — frontmatter examples.

---

## Acceptance Criteria

- [ ] Identity writes restricted to the 5 canonical filenames.
- [ ] Skill writes frontmatter-validated (422 on bad frontmatter,
      token-cap violation surfaced).
- [ ] KB writes restricted to `.md`/`.txt`.
- [ ] Traversal attempts → 400; unknown agent → 404; unknown kind → 400.
- [ ] Mutations return `reload_required: true`; deletes allowed even for
      in-use files.
- [ ] `pytest packages/ai-parrot-server/tests/studio/test_files.py -v` passes.
- [ ] `ruff check packages/ai-parrot-server/src/parrot/handlers/studio/` clean.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_files.py
class TestStudioFiles:
    async def test_identity_canonical_names_only(self, studio_app, tmp_agents_dir): ...
    async def test_identity_roundtrip_readable_by_load_identity(self, ...): ...
    async def test_skill_frontmatter_validation_422(self, ...): ...
    async def test_composite_skill_layout(self, ...): ...
    async def test_kb_extension_rules(self, ...): ...
    async def test_traversal_rejected(self, ...): ...
    async def test_reload_required_flag(self, ...): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2511 completed
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/agentstudio-management.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-27
**Notes**:
- `StudioFilesHandler` in `files.py` registered at two paths (list vs
  single-file) so the same class dispatches on `match_info.get
  ("filename")`: `.../files/{kind}` (GET list) and
  `.../files/{kind}/{filename:.*}` (GET/PUT/DELETE one file — the
  `:.*` converter is what lets composite skill paths like
  `<name>/SKILL.md` reach the handler as a single match_info value).
- Per-kind rules: identity restricted to the five canonical
  `IDENTITY_FILES` + `.md`; kb restricted to flat (no subdir) `.md`/
  `.txt`; skills accept single-file `<name>.md` or composite
  `<name>/SKILL.md` + `<name>/<asset>` (assets unrestricted). Skill
  frontmatter is validated via `parse_skill_file` against a SCRATCH
  tmp file (never the real target) for both the single-file form and
  the composite `SKILL.md` entry point — `_is_skill_definition_file`
  distinguishes those from plain composite assets, which are written
  as-is.
- Traversal safety reuses TASK-2511's `resolve_safe_path` directly
  (no new logic) — it already accepts multi-segment relative paths, so
  composite skill filenames pass straight through.
- Agent existence/ownership resolves BOTH origins (registry
  `bot_config.config['created_by']` — TASK-2512 convention — and
  DB-origin `BotModel.created_by`), since on-disk assets live under
  `AGENTS_DIR/<agent>/` regardless of the agent's origin. GET requires
  no ownership (any authenticated user can read); PUT/DELETE enforce
  `_require_owner`.
- No "file in use" check exists anywhere — delete is unconditional once
  ownership passes, matching the resolved decision ("never blocked").
  Every mutation response includes `reload_required: true`; this
  handler never calls `reload_agent` itself.
- Tests use the same `Handler(request)` + `__wrapped__`-peeling pattern
  as TASK-2512/2513, with a REAL `AgentRegistry` (not mocked) so
  `load_identity()` round-trips genuinely against the written files
  (`test_identity_write_and_load_identity_roundtrip`).

**Deviations from spec**: none.

Verification: `pytest packages/ai-parrot-server/tests/studio/
test_files.py -v` → 19/19 passed (green on first real run — no
implementation bugs found via testing this time). `ruff check
packages/ai-parrot-server/src/parrot/handlers/studio/` → clean except
intentional `BLE001` best-effort/fail-open patterns matching established
convention. Full regression sweep (`tests/studio/`, `tests/manager/`,
ephemeral-owner, DB-bot fallback tests) → 103/103 passed. Verified the
main repo tree stayed clean (`git status --porcelain` empty) throughout —
no `AGENTS_DIR`-related stray-file incidents this time.
