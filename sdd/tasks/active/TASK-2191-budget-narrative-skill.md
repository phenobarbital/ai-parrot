# TASK-2191: `budget-narrative` composite skill

**Feature**: FEAT-420 — FinanceReporter Tier-2 + Narrative Skill
**Spec**: `sdd/specs/finance-reporter-tier2-narrative.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2186
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of the spec, and is the reason this feature is a *skill*
rather than more Python: criterion **G-C** requires that changing how the report
reads means editing **data**, not code, and shipping no release.

This is a **composite** skill (`{dir}/SKILL.md` + adjacent assets) rather than a
single file, and that is forced rather than stylistic:
`SkillDefinition.MAX_TOKENS = 1000` (`skills/models.py:74`) with a
`field_validator` that **raises** above it (`skills/models.py:76-82`). The facts
contract plus the reference phrasing cannot fit in one body, so they live as
assets served on demand by `read_skill_asset` (`skills/tools.py:491`).

The prose this skill produces is the *only* non-deterministic output in the
feature, so the skill itself carries the discipline that keeps it safe: name
entities and directions, and quote figures only from the facts.

---

## Scope

Create the composite skill directory `.agent/skills/budget-narrative/`:

- **`SKILL.md`** — frontmatter (`name`, `description`, `triggers` — see the hard
  requirement below) plus a body, **strictly under 1000 cl100k_base tokens**,
  that instructs an LLM to:
  - render the `narrative_facts` contract as prose
  - read `facts-schema.md` for the contract and `reference.md` for style
  - quote **only** figures present in the facts (the mechanical guard in
    TASK-2190 enforces this; the skill must make compliance the obvious path)
  - state direction and name entities rather than inventing analysis
  - produce the sections the two layout profiles bind to (a headline/bottom-line
    paragraph, per-division reads, key drivers, a recommendation)
- **`facts-schema.md`** — the `narrative_facts` output contract as TASK-2186
  actually shipped it, with each field's meaning and allowed values.
- **`reference.md`** — the phrasing from `executive_summary.py:159-269` as style
  exemplars, with the mapping from each fact combination to the sentence shape
  the original produced.
- A unit test asserting the skill parses, stays under the cap, and is discovered
  as a composite with `assets_dir` populated.

**NOT in scope**:
- Any Python that calls the skill — that is TASK-2192 (`NarrativeMixin`).
- The figure guard implementation (TASK-2190).
- Executable assets. Assets are **documentation only**; a `.py` asset that gets
  imported would violate FEAT-324 G1 (see `transformers.py:72-79`).
- Modifying or deleting `.agent/skills/data-storytelling/` — related in theme but
  a separate, generic skill. Leave it alone.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.agent/skills/budget-narrative/SKILL.md` | CREATE | Entry point; frontmatter + < 1000-token body |
| `.agent/skills/budget-narrative/facts-schema.md` | CREATE | The `narrative_facts` contract |
| `.agent/skills/budget-narrative/reference.md` | CREATE | Phrasing exemplars ported from the reference artifact |
| `packages/ai-parrot/tests/unit/test_budget_narrative_skill.py` | CREATE | Parse/cap/discovery test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# For the test only:
from pathlib import Path
from parrot.skills.parsers import parse_skill_directory, parse_skill_file
from parrot.skills.models import SkillDefinition
from parrot.skills.loader import SkillsDirectoryLoader
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/skills/parsers.py — THE PARSING RULES
def _count_tokens(text: str) -> int:                       # line 32
    return len(_ENCODING.encode(text))                     # line 34
    # cl100k_base (real tiktoken), NOT a chars/4 heuristic.

def parse_skill_file(file_path: Path) -> SkillDefinition:  # line 37
    name: str = metadata.get("name", "")                   # line 55
    description: str = metadata.get("description", "")     # line 56
    # >>> HARD REQUIREMENT (lines 59-62):
    _triggers_sentinel = object()
    _raw_triggers = metadata.get("triggers", _triggers_sentinel)
    if _raw_triggers is _triggers_sentinel:
        raise ValueError(f"Skill file missing 'triggers' field: {file_path}")
    # => the `triggers` KEY MUST BE PRESENT. An empty list is allowed
    #    ("may be an empty list (for composite/directory skills)", line 57),
    #    but OMITTING the key raises.
    if not name:        raise ValueError(...)              # lines 70-71
    if not description: raise ValueError(...)              # lines 72-73
    template_body = post.content.strip()                   # line 76 — body AFTER frontmatter
    version  = str(metadata.get("version", "1.0"))         # line 88  (optional)
    category = metadata.get("category", None)              # line 89  (optional)
    priority = int(metadata.get("priority", 90))           # line 90  (optional)
    token_count = _count_tokens(template_body)             # line 93  <-- body only
    return SkillDefinition(...)                            # lines 95-106

def parse_skill_directory(skill_dir: Path) -> SkillDefinition:  # line 109
    """Composite: {dir}/SKILL.md via parse_skill_file, plus assets_dir set."""
```

```python
# packages/ai-parrot/src/parrot/skills/models.py
class SkillDefinition(BaseModel):                     # line 53
    name: str; description: str; triggers: List[str]  # lines 59-61
    template_body: str                                # line 66
    token_count: int                                  # line 67
    file_path: Path                                   # line 68
    assets_dir: Optional[Path] = Field(default=None)  # line 69 — set for composite only
    MAX_TOKENS: ClassVar[int] = 1000                  # line 74  <-- HARD CAP
    @field_validator("token_count")                   # line 76
    def validate_token_count(cls, v): ...             # RAISES above the cap (lines 80-82)
```

```python
# packages/ai-parrot/src/parrot/skills/tools.py — how the LLM reaches this skill
class SkillFileToolkit(AbstractToolkit):                            # line 371
    async def list_skill_commands(self) -> ToolResult: ...          # line 413
    async def load_skill(self, name: str) -> ToolResult: ...        # line 454
        # returns the body + an asset manifest
    async def read_skill_asset(self, skill_name: str, asset: str) -> ToolResult: ...  # line 491
        # sandboxed reader; path traversal rejected; "SKILL.md" is RESERVED for load_skill
```

```yaml
# The frontmatter shape to use (verified against the parser above):
---
name: budget-narrative
description: >
  Render deterministic budget-variance facts as executive-summary prose.
  Quote only figures present in the facts.
triggers: []          # REQUIRED KEY — empty list is valid for composite skills
category: domain
version: "1.0"
---
```

```
# The facts contract to document (from TASK-2186 / spec §2 Data Models):
headline: rev_state (behind|ahead), rev_direction (narrowing|widening|flat),
          ebitda_direction (improved|worsened|held_steady),
          both_improving | both_worsening | diverging (bools),
          first_label, last_label
top_driver: division, project, ebitda_variance, trend (may be null),
            urgency (immediate|confirm_trend|check_timing|none)   -- or null
division_reads[]: division, kind (on_track|spread|concentrated|offset_by),
                  named[], offsetter (only for offset_by, else null)
watch[] / bright[]: division, project, ebitda_variance, trend
n_snapshots: int
```

### Does NOT Exist

- ~~`.agent/skills/budget-narrative/`~~ — this task creates it.
- ~~a packaged skill inside `ai-parrot`~~ — zero `.md` skills ship in
  `packages/`; skills live as repo data in `.agent/skills/` (20+ present). Do
  NOT put this skill under `packages/`.
- ~~`parrot/skills/budget-narrative.md`~~ — `parrot/skills/` is the **code**
  package (loader, registry, tools, models), not a skill-data directory.
- ~~`.agent/skills/data-storytelling` as a usable base~~ — it exists but is
  generic auto-generated boilerplate about matplotlib/pandas, consumes no facts
  contract, and (per the parser rules above) **omits the required `triggers`
  key**, so it likely fails to parse and is skipped. Not a template to copy.
- ~~`triggers` being optional~~ — the key is REQUIRED (parsers.py:61-62), even
  though its value may be `[]`.
- ~~`SKILL.md` being readable via `read_skill_asset`~~ — it is RESERVED for
  `load_skill` (`tools.py:491` docstring). Assets must be *other* filenames.
- ~~a 4-chars-per-token approximation~~ — the cap is measured with real
  `cl100k_base` tiktoken on the stripped body.
- ~~frontmatter counting toward `token_count`~~ — only `post.content.strip()`
  is counted (parsers.py:76,93).

---

## Implementation Notes

### Pattern to Follow

```markdown
<!-- .agent/skills/budget-narrative/SKILL.md — keep the BODY under 1000 tokens -->
---
name: budget-narrative
description: Render deterministic budget-variance facts as executive-summary prose.
triggers: []
category: domain
version: "1.0"
---

# Budget Variance Narrative

Turn a `narrative_facts` object into a short executive summary.

## Hard rules

1. **Never write a number that is not in the facts.** Every figure is checked
   mechanically; one invented figure discards your entire output.
2. State direction and name entities. Do not infer causes the facts do not carry.
3. If a field is null, say what the facts support ("new this period"), never guess.

## What to read

- `facts-schema.md` — every field and its allowed values.
- `reference.md` — the house style, with fact-combination → sentence mappings.

## What to produce

... (four short sections matching the layout binds) ...
```

### Key Constraints

- **Measure the body before committing.** Run the token count and keep clear
  headroom (aim ≤ 800) so a later edit does not silently push it over — an
  over-cap skill is logged as a warning and **skipped**, so the narrative simply
  stops appearing with no error anywhere obvious.
- The `triggers` key must be present. Use `[]` — this skill is invoked
  programmatically by the narrator, not by a user typing `/trigger`.
- Assets must be `.md`. No `.py`, no scripts — assets are documentation only (G1).
- Do not name an asset `SKILL.md`; that name is reserved for `load_skill`.
- Document the facts contract from **what TASK-2186 actually shipped**, not from
  the spec's draft shape, if the two diverged. The transformer is the authority.
- Write `reference.md` as *exemplars*, explicitly labelled as style guidance, so
  an LLM does not treat a sample figure as real data. Use obviously-fake
  placeholders (e.g. `$X.XM`) rather than plausible dollar amounts.

### References in Codebase

- `.agent/skills/` — 20+ existing skills; inspect a few for house formatting
- `packages/ai-parrot/src/parrot/skills/parsers.py:37-106` — the parsing rules
- `sdd/artifacts/executive_summary.py:159-269` — the phrasing to port as exemplars
- `packages/ai-parrot/tests/unit/test_skill_definition.py` — test style for skill parsing

---

## Acceptance Criteria

- [ ] `.agent/skills/budget-narrative/SKILL.md` exists with `name`, `description`, and a `triggers` key
- [ ] `parse_skill_file(SKILL.md)` succeeds (no `ValueError`)
- [ ] `token_count` < 1000 with headroom (assert ≤ 900 in the test)
- [ ] `parse_skill_directory(...)` returns a `SkillDefinition` with `assets_dir` set
- [ ] `SkillsDirectoryLoader(paths=[Path(".agent/skills")])` discovers `budget-narrative`
- [ ] `facts-schema.md` documents every field TASK-2186 actually emits
- [ ] `reference.md` uses obviously-fake placeholder figures, never plausible amounts
- [ ] No asset is named `SKILL.md`; no asset is executable (`.py`/`.sh`)
- [ ] The body states the "never write a number not in the facts" rule explicitly
- [ ] `.agent/skills/data-storytelling/` is **unmodified**
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_budget_narrative_skill.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_budget_narrative_skill.py  (create)
from pathlib import Path

import pytest

from parrot.skills.loader import SkillsDirectoryLoader
from parrot.skills.models import SkillDefinition
from parrot.skills.parsers import parse_skill_directory, parse_skill_file

SKILL_DIR = Path(".agent/skills/budget-narrative")


class TestBudgetNarrativeSkill:
    def test_skill_md_parses(self):
        definition = parse_skill_file(SKILL_DIR / "SKILL.md")
        assert definition.name == "budget-narrative"
        assert definition.description

    def test_body_under_token_cap_with_headroom(self):
        definition = parse_skill_file(SKILL_DIR / "SKILL.md")
        assert definition.token_count < SkillDefinition.MAX_TOKENS
        assert definition.token_count <= 900, "keep headroom for future edits"

    def test_composite_sets_assets_dir(self):
        definition = parse_skill_directory(SKILL_DIR)
        assert definition.assets_dir == SKILL_DIR

    def test_expected_assets_present(self):
        names = {p.name for p in SKILL_DIR.iterdir()}
        assert {"SKILL.md", "facts-schema.md", "reference.md"} <= names

    def test_no_executable_assets(self):
        assert not [p for p in SKILL_DIR.iterdir() if p.suffix in {".py", ".sh"}]

    def test_body_states_the_no_invented_figures_rule(self):
        body = (SKILL_DIR / "SKILL.md").read_text()
        assert "not in the facts" in body.lower() or "only figures" in body.lower()

    async def test_discovered_by_loader(self):
        loader = SkillsDirectoryLoader(paths=[Path(".agent/skills")])
        found = await loader.discover()
        assert any(d.name == "budget-narrative" for d in found)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§7 Known Risks explains the
   silent-skip failure mode that makes the token headroom matter)
2. **Check dependencies** — TASK-2186 must be in `sdd/tasks/completed/`; read the
   `narrative_facts` implementation it shipped and document **that** contract
3. **Verify the Codebase Contract** — re-read `parsers.py:37-106`; confirm the
   `triggers`-key requirement and the tiktoken counting still hold
4. **Update status** in `sdd/tasks/index/finance-reporter-tier2-narrative.json`
   → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above.
   **Measure the token count before committing**, not after.
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2191-budget-narrative-skill.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
Record the final `token_count` of `SKILL.md`.

**Deviations from spec**: none | describe if any
