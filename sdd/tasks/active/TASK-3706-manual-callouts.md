# TASK-3706: Exploded-view callout mapping to Part via structured vision (M6 Q8)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3705
**Assigned-to**: unassigned

> Parallelism: modifies manuals/figures.py created by TASK-3705 (same file — serialized); reuses its FigureCandidate and capability rule.

---

## Context

Spec §2 Overview "Callouts (Q8)", §3 **Module 6** (`CalloutMapper`, `resolve_callout_mapper`, `is_exploded_view`,
`map_callouts`), goal **G11**, **AC21**. For every exploded view (caption/step evidence mentions ≥ 2 callout
numbers) one `ask_to_image(prompt, image, structured_output=CalloutMap)` call returns the callouts; each label
resolves to a `Part` by exact part number, else `similarity(description, part.name) ≥ 0.85`; unresolved callouts
stay on the media node (`unresolved_callouts[]`) and enter the verification queue. The pass is **disabled until
spike 1 passes** (`callouts_enabled`, default `False`).

---

## Scope

- Append to `manuals/figures.py`: `CALLOUTS_ENABLED_ENV`, `callouts_enabled()`, `CALLOUT_PROMPT`, `CalloutMapper`
  protocol, `resolve_callout_mapper`, `is_exploded_view`, `map_callouts`, and a module-local `_similarity`
  (rapidfuzz token_sort_ratio / 100 — copied from `contracts/carding.py:868-892`, because `manuals` must not
  import `contracts`, spec M1).
- Tests: `test_map_callouts_structured_output`.

**NOT in scope**: writing `depicts` edges (TASK-3712 graph loader, from `MediaRef.callouts`); `proc_find_part`
(TASK-3724); calling the pass from ingest (TASK-3713); flipping the flag (spike, TASK-3726).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/manuals/figures.py` | MODIFY | callout mapping pass (Q8) |
| `packages/ai-parrot/tests/knowledge/manuals/test_callouts.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.manuals.models import Callout, CalloutMap, CalloutLink, PartRef   # created by TASK-3699 (manuals/models.py)
# already in figures.py (TASK-3705): FigureCandidate, CaptioningUnavailable, logger, TYPE_CHECKING StepDraft
import os   # stdlib, for the env flag
```

### Existing Signatures to Use
```python
# structured_output on every provider (verified 2026-09-25):
AnthropicClient.ask_to_image(..., structured_output: Union[type, StructuredOutputConfig] = None, ...)  # anthropic/client.py:1329-1343 (:1337)
GoogleGenAIClient.ask_to_image(..., structured_output=...)   # google/client.py:5160
OpenAIClient.ask_to_image(..., structured_output: Optional[type] = None)  # openai/client.py:1468 — parsed → AIMessage.structured_output
ClaudeAgentClient.ask_to_image  # claude_agent.py:1036-1040 — raises NotImplementedError ⇒ treated as absent

# rapidfuzz similarity pattern to copy (do not import):
def similarity(left: str, right: str) -> float   # packages/ai-parrot/src/parrot/knowledge/contracts/carding.py:868-892

# TASK-3699 model contract (spec §3 M2):
class Callout(BaseModel): label: str; description: str; part_number: str | None; bbox: tuple[float,float,float,float] | None
class CalloutMap(BaseModel): callouts: list[Callout]
class CalloutLink(BaseModel): media_id: str; part_id: str; callout: str; confidence: float; origin: Literal["vision"]
class PartRef(BaseModel): part_id: str; part_number: str | None; name: Extracted[str]; quantity: int | None; resolved: bool
```

### Does NOT Exist
- ~~`CalloutMap`, `depicts` edge, callout parser~~ anywhere before FEAT-601 (spec §6).
- ~~`similarity` in `parrot.knowledge.common`~~ — M1 does not move it; keep a private copy here.
- ~~A generic "vision structured" helper on `AbstractClient`~~ — `ask_to_image` is per provider.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/manuals/figures.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_callouts.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py#AnthropicClient.ask_to_image",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/carding.py#similarity"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest …`.
- `callouts_enabled()` reads `PARROT_MANUALS_CALLOUTS` (`"1"/"true"` ⇒ on); default **off** (AC21). `map_callouts`
  accepts an explicit `enabled: bool | None = None` override for tests/spikes.
- One structured call per exploded view — never per callout (cost bound, spec §7).
- Unresolved callouts are returned, never guessed into a link.
- No new third-party dependency (rapidfuzz already in `graphindex`); Google docstrings, type hints, Pydantic v2, logger.

---

## Implementation Blueprint

### Steps (in order)
1. Add `import os` next to `import re`, extend the `models` import, add the env flag — *why*: the pass must be off until spike 1 passes (AC21).
2. Add `_similarity` (copy of contracts body) — *why*: manuals must not import contracts (M1 boundary).
3. Add `CalloutMapper`, `resolve_callout_mapper` — *why*: same capability rule as `resolve_captioner` (Q3).
4. Add `is_exploded_view`, `map_callouts` — *why*: deterministic label → Part resolution; LLM only proposes callouts.
5. Write the test.

### `packages/ai-parrot/src/parrot/knowledge/manuals/figures.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3705 lands: grep -c 'from parrot.knowledge.manuals.models import MediaLink, MediaRef' figures.py)
# REPLACE that import line with:
from parrot.knowledge.manuals.models import Callout, CalloutLink, CalloutMap, MediaLink, MediaRef, PartRef

# occurrences: 1 (verified after TASK-3705 lands: grep -c '^async def presign(' figures.py)
# AFTER — append at end of file, below `async def presign(` and its body
CALLOUTS_ENABLED_ENV = "PARROT_MANUALS_CALLOUTS"
CALLOUT_PROMPT = (
    "This is an exploded-view technical figure. List every numbered callout: its label exactly as printed, "
    "a short description of the part it points to, and the part number if printed. Context: {context}"
)
PART_SIMILARITY_THRESHOLD = 0.85


def callouts_enabled() -> bool:
    """Whether the callout pass is switched on (flipped once spike 1 passes — AC21)."""
    return os.environ.get(CALLOUTS_ENABLED_ENV, "").strip().lower() in {"1", "true", "yes"}


def _similarity(left: str, right: str) -> float:
    """rapidfuzz token_sort_ratio / 100 (copy of contracts/carding.py:868-892; manuals must not import contracts)."""
    # FILL IN: copy body verbatim incl. empty-input 0.0, identical 1.0 and RuntimeError install hint.
    return 0.0


class CalloutMapper(Protocol):
    """Anything that can map the callouts of one exploded view."""

    async def map_callouts(self, image: Path, *, context: str) -> CalloutMap: ...


class _AskToImageCalloutMapper:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def map_callouts(self, image: Path, *, context: str) -> CalloutMap:
        try:
            msg = await self._client.ask_to_image(
                CALLOUT_PROMPT.format(context=context), image, structured_output=CalloutMap
            )
        except NotImplementedError as exc:
            raise CaptioningUnavailable(str(exc)) from exc
        # FILL IN: coerce msg.structured_output (CalloutMap | dict | None) → CalloutMap; None ⇒ CalloutMap(callouts=[]).
        return CalloutMap(callouts=[])


def resolve_callout_mapper(client: Any) -> CalloutMapper:
    """Capability-resolved callout mapper; same rule as :func:`resolve_captioner`."""
    # FILL IN: reuse the resolve_captioner capability checks (no method / ClaudeAgentClient ⇒ CaptioningUnavailable).
    return _AskToImageCalloutMapper(client)


def is_exploded_view(figure: FigureCandidate, steps: Sequence["StepDraft"]) -> bool:
    """True when caption text or citing-step evidence mentions ≥ 2 callout numbers."""
    # FILL IN: count distinct callout tokens in figure.caption_text + the callout_mentions of steps whose
    #   figure_refs cite figure.label — bounded by: ≥ 2 distinct ⇒ True.
    return False


async def map_callouts(
    figures: Sequence[FigureCandidate],
    mapper: CalloutMapper,
    *,
    parts: Sequence[PartRef],
    steps: Sequence["StepDraft"],
    media_ids: Mapping[str, str] | None = None,
    enabled: bool | None = None,
) -> tuple[list[CalloutLink], list[Callout]]:
    """One structured call per exploded view; resolve label → Part; return (links, unresolved)."""
    if not (callouts_enabled() if enabled is None else enabled):
        logger.debug("map_callouts: disabled (set %s once spike 1 passes)", CALLOUTS_ENABLED_ENV)
        return [], []
    links: list[CalloutLink] = []
    unresolved: list[Callout] = []
    # FILL IN: for each fig with is_exploded_view ⇒ one mapper.map_callouts(fig.image.path, context=caption);
    #   per callout: exact part_number match (case/space-normalized) ⇒ confidence 1.0; else best
    #   _similarity(description, part.name.value) ≥ PART_SIMILARITY_THRESHOLD ⇒ that score; else unresolved.
    #   media_id = media_ids[fig.image.sha256] if given else fig.image.sha256[:16] (same scheme as pair_figures);
    #   CalloutLink(origin="vision") — bounded by AC21 (never a guessed link).
    return links, unresolved
```
**Why**: the flag and the one-call-per-view shape are fixed by Q8/AC21; resolution is deterministic so the
graph never carries an LLM-chosen part.

### `packages/ai-parrot/tests/knowledge/manuals/test_callouts.py` (CREATE)
```python
"""FEAT-601 M6 Q8 — callouts (AC21)."""
from __future__ import annotations

from types import SimpleNamespace

from parrot.knowledge.manuals import figures as fg
from parrot.knowledge.manuals.models import Callout, CalloutMap


class FakeMapper:
    def __init__(self, result: CalloutMap) -> None:
        self.calls = 0
        self.result = result

    async def map_callouts(self, image, *, context):
        self.calls += 1
        return self.result


async def test_map_callouts_structured_output(tmp_path) -> None:
    # FILL IN: one exploded FigureCandidate (caption "Fig. 2 — items 1, 2, 7"), parts with part_number "P-7" and name
    #   "hex bolt"; mapper returns callouts 7(part_number P-7), 2("hex bolt m8"), 9(unknown) ⇒ 2 links (1.0 and ≥0.85),
    #   1 unresolved, mapper.calls == 1; enabled=False ⇒ ([], []) and calls unchanged; env unset ⇒ disabled by default.
    ...
```

### FILL IN checklist
- [ ] `_similarity` body copy.
- [ ] `_AskToImageCalloutMapper` structured-output coercion.
- [ ] `resolve_callout_mapper` capability rule.
- [ ] `is_exploded_view` counting rule.
- [ ] `map_callouts` resolution loop — AC21.
- [ ] Test body.

---

## Acceptance Criteria

- [ ] Exploded views get exactly one structured vision call; resolved callouts become `CalloutLink`s; unresolved are returned (AC21).
- [ ] Disabled by default (`PARROT_MANUALS_CALLOUTS` unset) and when `enabled=False` (AC21).
- [ ] No import of `parrot.knowledge.contracts` from `manuals/figures.py`.
- [ ] `ruff check` + `black --check -l 120` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_callouts.py -q`
- `pytest packages/ai-parrot/tests/knowledge/manuals/test_figures.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_map_callouts_structured_output` | fake mapper returns `CalloutMap`; part_number exact and similarity resolution; unresolved listed; disabled when `callouts_enabled` is False |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/training-agent.spec.md` (module section named in Context).
2. **Check dependencies** — every `Depends-on` task must be in `sdd/tasks/completed/` (or merged in your feature branch).
3. **Verify the Codebase Contract** — before writing ANY code confirm every import, signature and line anchor
   above still holds (`grep -n` / `read`). Symbols marked "created by TASK-<X>" must exist now that the
   dependency landed; if a name differs, follow the landed code and record the deviation.
4. **Update status** in `sdd/tasks/index/training-agent.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes.
6. **Verify** — run every command in *Validation Commands* (with the worktree `PYTHONPATH`), plus `ruff check`
   and `black --check -l 120` on the touched files.
7. **Move this file** to `sdd/tasks/completed/`, set the index entry to `"done"`, fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
