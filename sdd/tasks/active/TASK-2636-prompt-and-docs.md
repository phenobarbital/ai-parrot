# TASK-2636: sdd-ideation Complementary Research prompt and operator docs

**Feature**: FEAT-482 — Complementary (Collaborative) Research for the Dev Flow
**Spec**: `sdd/specs/devflow-complementary-research.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2632, TASK-2635
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 7**. This task is where the *collaboration* actually
happens — everything before it moves findings around; this decides what the primary
seat does with them.

Attribution is **prompt-enforced**, not machine-validated (§8 Q7). The
`ResearchFinding.id` field makes citation checkable and the `.research.md` sidecar is
the structural backstop, but the merged document's quality depends on this prompt.
Write it carefully.

---

## Scope

- Add a **Complementary Research** section to
  `dev_flow/_subagent_data/sdd-ideation.md` instructing the seat to:
  - read the partner's findings as a **peer's contribution to expand on**, not a
    claim to rebut — this is collaboration, not adversarial review
  - **attribute** insights by finding `id` (e.g. "*[F2, gpt-5.6-sol] …*")
  - state disagreements explicitly and say why — **disagreement is data, not conflict**
  - never let the partner's *absence* change the process (findings are optional)
- Add guidance for the new read-only wiki MCP tools from TASK-2635 (`wiki_query`,
  `wiki_page`, `wiki_related`): prefer graph search over `Grep` for "where does X
  live / how do these relate" questions; `Grep` remains right for exact literals.
- Mirror the prompt to `.claude/agents/sdd-ideation.md` (the repo-level twin for
  interactive use — see `_subagent_defs.py`'s docstring).
- Document the operator surface in `docs/`: all `DEV_FLOW_RESEARCH_PARTNER_*` keys,
  `DEV_FLOW_IDEATION_MODEL`, the two backends, the degradation contract, and the
  `.research.md` artifact.
- **Document the web-search egress posture explicitly**:
  `DEV_FLOW_RESEARCH_PARTNER_WEB_SEARCH` defaults to **`true`**, so enabling the
  partner sends brief content — which may describe unreleased work — to a
  third-party search provider. Say so plainly; do not bury it.

**NOT in scope**: any Python behavior change; machine-validating attribution
(§8 Q7 resolved as prompt-enforced); FEAT-484's own docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md` | MODIFY | Complementary Research + graph-search sections |
| `.claude/agents/sdd-ideation.md` | MODIFY | Mirror of the above |
| `docs/` (new or existing dev-flow page) | MODIFY | Operator configuration reference |

---

## Codebase Contract (Anti-Hallucination)

### Verified Signatures / Facts

```python
# packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_defs.py
_VALID_NAMES: frozenset[str] = frozenset({"sdd-ideation"})           # line 33
def load_subagent_definition(name: str) -> str
# Reads ONLY dev_flow/_subagent_data/<name>.md — never .claude/agents/ at
# runtime. The repo-level twin at .claude/agents/sdd-ideation.md exists for
# interactive Claude Code use with setting_sources=["project"].
# => BOTH files must be updated; they do not sync automatically.

# Frontmatter is stripped before use:
def _strip_frontmatter(text: str) -> str
# Malformed frontmatter returns the text unchanged rather than dropping the file.

# From TASK-2629 — the field attribution refers to:
class ResearchFinding(BaseModel):
    id: str            # stable, e.g. "F1" — cite these
    title: str
    detail: str
    evidence: list[str] = []
    confidence: Literal["high","medium","low"] = "medium"

# Wiki MCP tools exposed by TASK-2635 (read-only subset):
#   mcp__wikitoolkit__wiki_query   (parrot/knowledge/wiki/tools.py:155)
#   mcp__wikitoolkit__wiki_page    (:190)
#   mcp__wikitoolkit__wiki_related (:225)
```

### Config keys to document

| Key | Default |
|---|---|
| `DEV_FLOW_RESEARCH_PARTNER` | `""` (disabled) |
| `DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL` | `gpt-5.6-sol` |
| `DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL` | `us.amazon.nova-2-lite-v1:0` |
| `DEV_FLOW_RESEARCH_PARTNER_THINKING_BUDGET` | `4096` (Converse only) |
| `DEV_FLOW_RESEARCH_PARTNER_EFFORT` | `high` (mantle only) |
| `DEV_FLOW_RESEARCH_PARTNER_TIMEOUT` | `600` |
| `DEV_FLOW_RESEARCH_PARTNER_MAX_TOKENS` | `16384` |
| `DEV_FLOW_RESEARCH_PARTNER_WEB_SEARCH` | **`true`** — external egress |
| `DEV_FLOW_IDEATION_MODEL` | `claude-opus-5` |

### Does NOT Exist

- ~~automatic sync between `_subagent_data/sdd-ideation.md` and
  `.claude/agents/sdd-ideation.md`~~ — there is none. Update **both**.
- ~~`sdd-research` or `sdd-secondopinion` in `dev_flow._subagent_defs`~~ —
  `_VALID_NAMES` is `frozenset({"sdd-ideation"})` only (`:33`). dev_flow owns its
  own prompt set deliberately.
- ~~`gpt-5.5-sol`~~ — the model string is **`gpt-5.6-sol`**.
- ~~machine-validated attribution~~ — §8 Q7 resolved as prompt-enforced. Do not add
  a validator; the prompt and the `.research.md` sidecar are the mechanism.

---

## Implementation Notes

### Prompt guidance to convey

The tone matters and is the whole point of the feature. The partner is a
**collaborator**, not an adversary — contrast with `sdd-secondopinion`, which
exists to challenge. Concretely, the section should tell the seat to:

- treat findings as additive coverage: expand, connect, and build on them
- cite by finding id and name the source model
- disagree openly with reasons — a documented disagreement is a useful signal about
  a genuinely uncertain area, not a conflict to resolve
- carry forward what the partner could not determine (`could_not_determine`) as
  Open Questions where appropriate
- proceed identically when there are no findings at all

### Key Constraints

- Do not add frontmatter that `_strip_frontmatter` would mishandle.
- Keep the two prompt copies textually identical.
- Do not weaken the existing Code Context / anti-hallucination instructions already
  in the prompt — this section is additive.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_defs.py:1-40` — the loader
  contract and why two copies exist.
- `CLAUDE.md` § "Adversarial Second Opinion" — the *contrasting* discipline, useful
  to read so this prompt does not accidentally reproduce an adversarial framing.

---

## Acceptance Criteria

- [ ] Complementary Research section added to `_subagent_data/sdd-ideation.md`
- [ ] `.claude/agents/sdd-ideation.md` is textually identical
- [ ] Prompt instructs: expand-not-rebut, attribute by finding id, disagree openly, tolerate absence
- [ ] Graph-search guidance added for the three read-only wiki tools
- [ ] `load_subagent_definition("sdd-ideation")` still returns a clean body (frontmatter stripped)
- [ ] All nine config keys documented, with the web-search egress consequence stated plainly
- [ ] Existing prompt instructions unchanged
- [ ] `pytest packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py -v` passes

---

## Test Specification

```python
def test_subagent_definition_loads_with_new_section():
    """load_subagent_definition('sdd-ideation') returns a body containing the
    Complementary Research section, with frontmatter stripped."""
    body = load_subagent_definition("sdd-ideation")
    assert "Complementary Research" in body
    assert not body.startswith("---")

def test_prompt_copies_are_identical():
    """_subagent_data/sdd-ideation.md and .claude/agents/sdd-ideation.md match."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 7, §2 "Why the partner is prompted neutrally", §8 Q5/Q7).
2. **Check dependencies** — TASK-2632 and TASK-2635 in `sdd/tasks/completed/`.
3. **Read the existing prompt in full** before adding to it — the new section must
   not contradict the Code Context discipline already there.
4. **Update status** in `sdd/tasks/index/devflow-complementary-research.json` → `"in-progress"`.
5. **Implement** — update BOTH prompt copies.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-2636-prompt-and-docs.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
