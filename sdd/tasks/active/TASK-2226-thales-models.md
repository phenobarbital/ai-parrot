# TASK-2226: Thales Pydantic contracts — deck, slides, config, result models

**Feature**: FEAT-425 — "Thales" Research Flow with Structured Citations, Decks & Final Report
**Spec**: `sdd/specs/agentcrew-tales-research.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of FEAT-425. Every other Thales module (factories, nodes, renderer,
runner, handler) consumes these models, and the separate
`research-tools-for-agents` spec implements new research sources against the
`SourceClaim`/`Finding` contract defined here. Spec §2 "Data Models" is the
normative shape list. Keep this package dependency-light: pydantic + stdlib
only (no parrot imports beyond typing needs) so satellite specs can build
against it without pulling flow machinery.

---

## Scope

- Create package `packages/ai-parrot/src/parrot/flows/thales/` with
  `__init__.py` and `models/` subpackage (`__init__.py`, `deck.py`,
  `slides.py`, `config.py`, `result.py`).
- Implement (names are normative, per spec §2):
  - `deck.py`: `ResearchAngle`, `SourceClaim`, `Finding`, `ResearchDeck`.
  - `slides.py`: `SlideSpec`, `Bibliography`.
  - `config.py`: `ThalesConfig` — `num_decks: int = Field(default=10, ge=10)`
    (**minimum 10, NO upper cap** — resolved in brainstorm), `sources`
    default `["web", "deep_research", "arxiv"]`, `output_dir`,
    `per_node_timeout`, `max_paragraphs_per_finding: int = 6`.
  - `result.py`: `ArtifactRef`, `ThalesResult` (the run manifest).
- `SourceClaim.verification` is
  `Literal["groundedness", "provider_grounding", "unverified"]`;
  `published_date` is Optional (never invented — "n.d." rendering happens in
  the bibliography formatter, NOT here).
- Re-export all public models from `parrot.flows.thales.models` and from
  `parrot.flows.thales` (`__init__.py`).
- Google-style docstrings + strict type hints on every model/field.
- Write unit tests.

**NOT in scope**: any flow node, agent factory, rendering, persistence, or
HTTP code (TASK-2227…2232); the APA-ish bibliography *formatter* (TASK-2230 —
only the `Bibliography` container model lives here).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/thales/__init__.py` | CREATE | Package init, re-export models |
| `packages/ai-parrot/src/parrot/flows/thales/models/__init__.py` | CREATE | Model re-exports |
| `packages/ai-parrot/src/parrot/flows/thales/models/deck.py` | CREATE | ResearchAngle, SourceClaim, Finding, ResearchDeck |
| `packages/ai-parrot/src/parrot/flows/thales/models/slides.py` | CREATE | SlideSpec, Bibliography |
| `packages/ai-parrot/src/parrot/flows/thales/models/config.py` | CREATE | ThalesConfig |
| `packages/ai-parrot/src/parrot/flows/thales/models/result.py` | CREATE | ArtifactRef, ThalesResult |
| `packages/ai-parrot/tests/flows/thales/__init__.py` | CREATE | Test package |
| `packages/ai-parrot/tests/flows/thales/test_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-17 against `dev`.

### Verified Imports
```python
from pydantic import BaseModel, Field   # pydantic v2, core dep
from typing import Any, Literal, Optional
from pathlib import Path
```

### Existing Signatures to Use
```python
# Precedent for a domain-flow models package:
#   packages/ai-parrot/src/parrot/flows/dev_loop/models/  (package exists — mirror its layout)
# Spec §2 "Data Models" carries the normative field lists for every model in
# this task — copy shapes from the spec, not from memory.
```

### Does NOT Exist
- ~~`parrot/flows/thales/`~~ — this task creates it (no "tales"/"thales"
  reference exists in `parrot/` today; verified by grep).
- ~~`ResearchAngle`/`SourceClaim`/`Finding`/`ResearchDeck`/`SlideSpec`/
  `Bibliography`/`ThalesConfig`/`ArtifactRef`/`ThalesResult`~~ — none exist
  anywhere; this task creates all of them.
- ~~An upper bound on `num_decks`~~ — deliberately none (resolved in
  brainstorm: minimum 10, no hard cap). Do NOT add `le=`.
- ~~`InfographicRenderResult` import in these models~~ — `ThalesResult.infographic`
  stays `Optional[Any]` to avoid importing toolkit machinery here.

---

## Implementation Notes

### Pattern to Follow
```python
# Pydantic v2 model style used across the repo (e.g. parrot/models/):
class SourceClaim(BaseModel):
    """One cited source backing a finding. ..."""
    url: str
    verification: Literal["groundedness", "provider_grounding", "unverified"]
```

### Key Constraints
- pydantic + stdlib only in `models/` — no parrot.* imports.
- `num_decks` validation: `ge=10`, default 10, **no upper cap**.
- All models JSON-serializable via `model_dump()`/`model_dump_json()`
  (Path fields must serialize cleanly).

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/models/` — layout precedent.
- Spec §2 Data Models — normative field lists.

---

## Acceptance Criteria

- [ ] All models importable: `from parrot.flows.thales.models import ResearchDeck, SourceClaim, ThalesConfig, ThalesResult`
- [ ] `ThalesConfig(num_decks=9)` raises ValidationError; `num_decks=10` and `num_decks=500` both pass
- [ ] `SourceClaim.verification` rejects values outside the three literals
- [ ] Round-trip: `ResearchDeck`/`SlideSpec`/`ThalesResult` survive `model_dump_json()` → `model_validate_json()`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/thales/test_models.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/thales/`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/thales/test_models.py
import pytest
from pydantic import ValidationError
from parrot.flows.thales.models import (
    Bibliography, Finding, ResearchAngle, ResearchDeck,
    SlideSpec, SourceClaim, ThalesConfig, ThalesResult,
)

class TestThalesConfig:
    def test_num_decks_floor(self):
        with pytest.raises(ValidationError):
            ThalesConfig(thesis="t", num_decks=9)

    def test_num_decks_no_cap(self):
        assert ThalesConfig(thesis="t", num_decks=500).num_decks == 500

class TestSourceClaim:
    def test_verification_labels(self):
        for label in ("groundedness", "provider_grounding", "unverified"):
            assert SourceClaim(url="https://x", accessed_date="2026-08-17",
                               source_tool="web_search", verification=label)
        with pytest.raises(ValidationError):
            SourceClaim(url="https://x", accessed_date="2026-08-17",
                        source_tool="web_search", verification="vibes")

class TestRoundTrip:
    def test_deck_roundtrip(self):
        deck = ResearchDeck(
            angle=ResearchAngle(angle_id="a1", title="t", question="q", rationale="r"),
            findings=[], tools_used=["web_search"],
        )
        assert ResearchDeck.model_validate_json(deck.model_dump_json()) == deck
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — before writing ANY code
4. **Update status** in `sdd/tasks/index/agentcrew-tales-research.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2226-thales-models.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
