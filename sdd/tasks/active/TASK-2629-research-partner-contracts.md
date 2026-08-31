# TASK-2629: ResearchPartner contracts, factory, selector and family guard

**Feature**: FEAT-482 — Complementary (Collaborative) Research for the Dev Flow
**Spec**: `sdd/specs/devflow-complementary-research.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 1**. This is the contract layer every other task in
FEAT-482 builds on: the Pydantic models, the partner ABC, the registry, the config
selector, and the family guard that rejects Anthropic partner models.

Deliberately has no dependency on any other task, so it can land first and unblock
everything else.

---

## Scope

- Create `research_partner.py` with `ResearchFinding`, `ResearchFindings`,
  `ComplementaryFindings` (exact shapes in spec §2 Data Models).
- Implement `AbstractResearchPartner` ABC: `partner_name: str`,
  `advisory: bool = True`, and abstract
  `async def research(*, brief, question, cwd, run_id, node_id, session_host=None) -> ResearchFindings`.
- Implement `ResearchPartnerFactory` with `register(name)` / `create(name, **kwargs)`,
  mirroring `CodeReviewDispatcherFactory` (`code_review.py:164-170`).
- Add the selector triad to `dev_loop/catalog.py`, mirroring `catalog.py:54/60/63`:
  `RESEARCH_PARTNER_BACKEND: str = "gpt"`,
  `_RESEARCH_PARTNER_CHOICES: Tuple[str, ...] = ("gpt", "nova")`,
  `resolve_research_partner_backend(config_getter=None) -> str`.
- **Family guard**: the resolver MUST reject an Anthropic partner model
  (`us.anthropic.*`, `global.anthropic.*`, `claude-*`) with a `ValueError` naming
  BOTH reasons: (1) correlated priors defeat the seat's decorrelation purpose,
  (2) the Converse thinking path would return 400 (see TASK-2630).
- Add a `BackendInfo` entry with `roles=("research_partner",)` so the catalog
  surfaces the seat.
- Add the `DEV_FLOW_RESEARCH_PARTNER_*` conf keys from spec §7 Configuration.
  **Unset `DEV_FLOW_RESEARCH_PARTNER` ⇒ disabled ⇒ byte-identical behavior.**
- Unit tests.

**NOT in scope**: the partner implementation (TASK-2631), the coordinator
(TASK-2632), the `bedrock.py` thinking fix (TASK-2630), any node wiring,
`DEV_FLOW_IDEATION_MODEL` (TASK-2635).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/research_partner.py` | CREATE | Models, ABC, factory |
| `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py` | MODIFY | Selector triad + `BackendInfo` |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `DEV_FLOW_RESEARCH_PARTNER_*` keys |
| `packages/ai-parrot/tests/flows/dev_flow/test_research_partner.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from abc import ABC, abstractmethod                       # stdlib
from typing import Any, Callable, Literal, Optional, Tuple
from pydantic import BaseModel, Field
from parrot import conf
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py
class AbstractCodeReviewDispatcher(ABC):                             # line 85
    advisory: bool = False                                           # line 100
class CodeReviewDispatcherFactory:                                   # line 164
    @classmethod
    def register(cls, name: str)                                     # line 170

# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py — MIRROR THIS TRIAD
ADVERSARIAL_BACKEND: str = "codex"                                   # line 54
_ADVERSARIAL_BACKEND_CHOICES: Tuple[str, ...] = ("codex", "nova")    # line 60
def resolve_adversarial_backend(config_getter: Optional[ConfigGetter] = None) -> str:  # line 63
    # Resolves DEV_LOOP_ADVERSARIAL_BACKEND through config, defaults to the
    # module constant; raises ValueError naming the valid options otherwise.
ConfigGetter = Callable[..., Any]
    BackendInfo(id="nova", ...)                                      # line 230

# packages/ai-parrot/src/parrot/conf.py — sibling keys, follow this neighbourhood
DEV_LOOP_ADVERSARIAL_MODEL: str = config.get("DEV_LOOP_ADVERSARIAL_MODEL", fallback="gpt-5.5")     # line 947
DEV_FLOW_IDEATION_MAX_ROUNDS: int = config.getint("DEV_FLOW_IDEATION_MAX_ROUNDS", fallback=2)      # line 972
DEV_LOOP_NOVA_REVIEW_MODEL: str = config.get("DEV_LOOP_NOVA_REVIEW_MODEL", fallback=_NOVA_DEFAULT_CONVERSE_MODEL)  # line 1069
DEV_LOOP_ADVERSARIAL_BACKEND: str = config.get("DEV_LOOP_ADVERSARIAL_BACKEND", fallback="codex")   # line 1082

# packages/ai-parrot/src/parrot/models/openai.py — the default partner model string
    GPT5_6_SOL = "gpt-5.6-sol"                                       # line 22
```

### Config keys to add (spec §7)

| Key | Default |
|---|---|
| `DEV_FLOW_RESEARCH_PARTNER` | `""` (disabled) |
| `DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL` | `gpt-5.6-sol` |
| `DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL` | `us.amazon.nova-2-lite-v1:0` |
| `DEV_FLOW_RESEARCH_PARTNER_THINKING_BUDGET` | `4096` |
| `DEV_FLOW_RESEARCH_PARTNER_EFFORT` | `high` |
| `DEV_FLOW_RESEARCH_PARTNER_TIMEOUT` | `600` |
| `DEV_FLOW_RESEARCH_PARTNER_MAX_TOKENS` | `16384` |
| `DEV_FLOW_RESEARCH_PARTNER_WEB_SEARCH` | `true` |

### Does NOT Exist

- ~~`AbstractResearchPartner`~~ / ~~`ResearchPartnerFactory`~~ / ~~`ResearchFindings`~~ — all new in this task.
- ~~`RESEARCH_PARTNER_BACKEND`~~ / ~~`resolve_research_partner_backend`~~ — new; mirror the adversarial triad.
- ~~`gpt-5.5-sol`~~ — **the real string is `gpt-5.6-sol`** (`models/openai.py:22`). No `-sol` variant exists at 5.5.
- ~~a `gpt` backend in `catalog.py`~~ — only `codex` (`:149`) and `nova` (`:230`) exist.
- ~~`AbstractCodeReviewDispatcher` as a base class for the partner~~ — mirror its *shape*, do not subclass it. Research is not review.

---

## Implementation Notes

### Pattern to Follow

```python
# Mirror catalog.py:54-80 exactly — module constant, choices tuple, resolver
# that raises ValueError naming valid options.
RESEARCH_PARTNER_BACKEND: str = "gpt"
_RESEARCH_PARTNER_CHOICES: Tuple[str, ...] = ("gpt", "nova")

def resolve_research_partner_backend(config_getter: Optional[ConfigGetter] = None) -> str:
    """Return the deployment's configured research-partner backend."""
```

### Key Constraints

- Async throughout on the ABC; Pydantic for every model; `self.logger`, never `print`.
- **The family guard is a hard reject, not a warning.** Its error message must name
  both the decorrelation reason and the 400 reason — a reader hitting it should
  understand it is not an arbitrary restriction.
- `advisory = True` on the ABC: partner findings are never authoritative.
- Google-style docstrings and strict type hints (`CLAUDE.md`).

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:42-80` — the triad to mirror, including the explanatory comment style.
- `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py:85-190` — ABC + factory shape.

---

## Acceptance Criteria

- [ ] `ResearchFinding` / `ResearchFindings` / `ComplementaryFindings` match spec §2 field-for-field
- [ ] `AbstractResearchPartner` is abstract with `advisory = True`
- [ ] `ResearchPartnerFactory.register` / `.create` work; unknown name raises naming valid options
- [ ] `resolve_research_partner_backend()` returns `""`/disabled when unset
- [ ] Anthropic partner model rejected with an error naming BOTH reasons
- [ ] All 8 conf keys present with the documented defaults
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_research_partner.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_flow/research_partner.py`
- [ ] Imports work: `from parrot.flows.dev_flow.research_partner import AbstractResearchPartner`

---

## Test Specification

```python
import pytest
from parrot.flows.dev_flow.research_partner import (
    AbstractResearchPartner, ResearchPartnerFactory,
    ResearchFinding, ResearchFindings, ComplementaryFindings,
)
from parrot.flows.dev_loop.catalog import resolve_research_partner_backend


def test_resolve_research_partner_backend_default_disabled():
    """Unset config => partner disabled, no work performed."""

def test_resolve_research_partner_backend_rejects_unknown():
    """Invalid value raises ValueError naming gpt/nova."""

def test_partner_rejects_anthropic_model():
    """us.anthropic.claude-opus-5 refused; message names decorrelation AND the 400."""
    with pytest.raises(ValueError, match="(?s)decorrel.*400|400.*decorrel"):
        ...

def test_abstract_partner_is_advisory():
    assert AbstractResearchPartner.advisory is True

def test_factory_registers_and_creates():
    """register() then create() returns the registered class."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (especially §2 Data Models, §3 Module 1, §7 Configuration).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** before writing ANY code — re-grep each cited line number; the spec was written 2026-08-31 and `catalog.py`/`conf.py` are actively edited by FEAT-479.
4. **Update status** in `sdd/tasks/index/devflow-complementary-research.json` → `"in-progress"`.
5. **Implement** following the scope and contract above.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-2629-research-partner-contracts.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
