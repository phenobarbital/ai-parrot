# TASK-2088: Nova backend registration, catalog entry & selectable adversarial seat

**Feature**: FEAT-405 — Nova (AWS Bedrock) Dispatcher & Per-Agent Usage Report
**Spec**: `sdd/specs/novaclient-dev-loop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2086, TASK-2087
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of the spec — the wiring that makes the Nova dispatchers
reachable. Until this lands, `NovaCodeDispatcher` and
`NovaAdversarialReviewDispatcher` exist but nothing can select them:
`DevAgentBackend` has exactly eight values and `build_dispatcher` raises
`ValueError` for anything else (`agent_builder.py:210`).

This task also converts `ADVERSARIAL_BACKEND` from a hardcoded constant
(`catalog.py:48`) into a config-resolved choice over `{codex, nova}`.

**The governing constraint is [R3]: fully opt-in.** An operator who configures
nothing must see byte-identical behaviour — `claude-code` still develops,
`codex` still reviews adversarially. Every default in this task is a
no-behaviour-change default.

---

## Scope

- Add `"nova"` to the `DevAgentBackend` Literal (`models/base.py:383`; the alias
  is also referenced at line 847 — check that site still resolves).
- Add a `nova` branch to `build_dispatcher` before the `raise ValueError`
  (`agent_builder.py:210`), returning `(NovaCodeDispatcher, NovaCodeDispatchProfile)`
  and honouring `spec.model` over the config default.
- Add a `BackendInfo` row for `nova` to `catalog.BACKENDS` (`catalog.py:88`) with
  the curated Bedrock model list, `transport="api"`, and its roles.
- Convert `ADVERSARIAL_BACKEND` into a config-resolved choice over
  `{codex, nova}` defaulting to `"codex"`, updating both use sites
  (`catalog.py:294`, `:296`).
- Add the `DEV_LOOP_NOVA_*` config keys not already added by TASK-2086/2087
  (code model, review model, mechanical model, adversarial backend selector).
- Write unit tests, including a regression test that unset config yields today's
  exact behaviour.

**NOT in scope**: the dispatchers themselves (TASK-2086/2087); usage reporting
(TASK-2089+); PR enrichment (TASK-2092); adding `nova` to `JUDGE_BACKENDS` or
`PRIMARY_REVIEW_BACKENDS` (those seats are not part of this feature).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` | MODIFY | `"nova"` into the `DevAgentBackend` Literal |
| `packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py` | MODIFY | `nova` branch before `raise ValueError` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py` | MODIFY | `BackendInfo` row; `ADVERSARIAL_BACKEND` → config-resolved |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `DEV_LOOP_NOVA_*` keys + `DEV_LOOP_ADVERSARIAL_BACKEND` |
| `packages/ai-parrot/tests/flows/dev_loop/test_nova_wiring.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.flows.dev_loop.dispatchers import NovaCodeDispatcher      # TASK-2086
from parrot.flows.dev_loop.models import NovaCodeDispatchProfile      # TASK-2084
from parrot.flows.dev_loop.agent_builder import build_dispatcher
from parrot.flows.dev_loop.catalog import (
    ADVERSARIAL_BACKEND, BACKENDS, BackendInfo, backends_for_role, catalog_payload,
)
from parrot import conf
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
DevAgentBackend = Literal[                                            # line 383
    "claude-code", "codex", "gemini", "nvidia", "grok", "zai", "moonshot", "google_coding"
]
class DevAgentSpec(BaseModel):                                        # line 388
    agent: DevAgentBackend = Field(...)                               # line 396
    model: str = Field(default="", description="'' ⇒ use the backend's default model.")
# NOTE: DevAgentBackend is reused at line 847 by a second model — verify that site.

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py
def build_dispatcher(spec, *, redis_url, max_concurrent, stream_ttl_seconds,
                     config_getter=_default_config_getter
                     ) -> Tuple[DevLoopCodeDispatcher, BaseModel]: ...  # line 100
    common = {"redis_url": ..., "max_concurrent": ..., "stream_ttl_seconds": ...}
    if spec.agent == "claude-code": ...    # line 138
    if spec.agent == "codex": ...          # line 145
    if spec.agent == "gemini": ...         # line 152
    if spec.agent == "nvidia": ...         # line 159
    if spec.agent == "grok": ...           # line 175
    if spec.agent == "zai": ...            # line 182
    if spec.agent == "moonshot": ...       # line 193  ← CLOSEST PRECEDENT
    if spec.agent == "google_coding": ...  # line 203
    raise ValueError(f"Unknown DevAgentBackend: {spec.agent!r}")       # line 210  ← INSERT BEFORE

# the moonshot branch, verbatim shape (lines 193-201):
#     dispatcher = MoonshotCodeDispatcher(**common)
#     profile = MoonshotCodeDispatchProfile(
#         model=spec.model or config_getter("DEV_LOOP_MOONSHOT_MODEL", "kimi-k3"),
#         reasoning_effort=config_getter("DEV_LOOP_MOONSHOT_REASONING_EFFORT", "max"),
#     )
#     return dispatcher, profile

# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py
JUDGE_BACKENDS: Tuple[str, ...] = ("claude-code","codex","gemini","google_coding")  # line 42
ADVERSARIAL_BACKEND: str = "codex"                                    # line 48  ← MAKE SELECTABLE
PRIMARY_REVIEW_BACKENDS: Tuple[str, ...] = (...)                      # line 52
@dataclass(frozen=True)
class BackendInfo:                                                    # line 56
    id: str; label: str; transport: str; model_env: Optional[str]
    default_model: str; models: Tuple[str, ...]; requires: str
    roles: Tuple[str, ...]; notes: str = ""
BACKENDS: Tuple[BackendInfo, ...] = (...)                             # line 88  ← ADD A ROW
def backends_for_role(role: str) -> List[BackendInfo]: ...            # line 193
def catalog_payload(config_getter=None) -> Dict[str, Any]: ...        # line 277
    # line 294: "adversarial": [ADVERSARIAL_BACKEND],
    # line 296: "adversarial_backend": ADVERSARIAL_BACKEND,

# packages/ai-parrot/src/parrot/conf.py
DEV_LOOP_ADVERSARIAL_MODEL: str = config.get(..., fallback="gpt-5.5")  # line 1048
```

### Verified model ids for the catalog row

```text
default (dev seat)  minimax.minimax-m2.5
curated list        minimax.minimax-m2.5, moonshotai.kimi-k2.5, zai.glm-5,
                    us.anthropic.claude-opus-5, us.anthropic.claude-haiku-4-5-20251001-v1:0,
                    global.anthropic.claude-fable-5
requires            "AWS credentials with Bedrock model access (+ Bedrock API key for bedrock-mantle)"
transport           "api"
```

### Does NOT Exist

- ~~`"nova"` in `DevAgentBackend`~~ — the Literal has exactly 8 values; this task adds the 9th
- ~~A `nova` row in `catalog.BACKENDS`~~ — no Bedrock backend is listed
- ~~`conf.DEV_LOOP_ADVERSARIAL_BACKEND`~~ — this task adds it; only `_MODEL`, `_SCOPE`, `_BASE_REF` exist (`conf.py:1048,1053,1076`)
- ~~`ADVERSARIAL_BACKEND` as anything but the literal string `"codex"`~~ — it is a plain module constant today
- ~~`nova` in `JUDGE_BACKENDS` / `PRIMARY_REVIEW_BACKENDS`~~ — out of scope; do not add

---

## Implementation Notes

### Pattern to Follow

The `moonshot` branch (`agent_builder.py:193-201`) is the closest precedent —
copy its shape exactly:

```python
if spec.agent == "nova":
    dispatcher = NovaCodeDispatcher(**common)
    profile = NovaCodeDispatchProfile(
        model=spec.model or config_getter("DEV_LOOP_NOVA_CODE_MODEL",
                                          "minimax.minimax-m2.5"),
    )
    return dispatcher, profile
```

For the adversarial selector, keep the module-level name so existing importers
keep working, but resolve it through config with a `codex` fallback:

```python
def resolve_adversarial_backend(config_getter=None) -> str:
    """Return the configured adversarial backend; 'codex' when unset."""
```

### Key Constraints

- **[R3] Unset config must change nothing.** `ADVERSARIAL_BACKEND` resolves to
  `"codex"`; the dev pool default stays `claude-code`. There must be a
  regression test proving this.
- Do not reorder or alter the existing `build_dispatcher` branches — insert only.
- `spec.model` always wins over the config default (the documented contract in
  `build_dispatcher`'s docstring, lines 100-130).
- Check the second `DevAgentBackend` use site at `models/base.py:847` still
  type-checks after adding the value.
- Keep `catalog.py` **data, not logic** — its module docstring is explicit about
  this; the config resolution should be a small function, not a rewrite.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py:193-201` — the branch to copy
- `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:88-130` — existing `BackendInfo` rows
- `packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py:1-30` — the "data, not logic" docstring

---

## Acceptance Criteria

- [ ] `DevAgentBackend` contains `"nova"`; `models/base.py:847`'s use site still resolves
- [ ] `build_dispatcher(DevAgentSpec(agent="nova"))` returns
      `(NovaCodeDispatcher, NovaCodeDispatchProfile)`
- [ ] `spec.model` overrides `DEV_LOOP_NOVA_CODE_MODEL`
- [ ] `catalog_payload()` lists `nova` with its curated models and roles
- [ ] **`ADVERSARIAL_BACKEND` resolves to `"codex"` when unconfigured** — no behaviour change
- [ ] Setting the config to `nova` selects the `nova-adversarial` dispatcher
- [ ] An invalid adversarial backend value raises a clear error naming the valid options
- [ ] `nova` is NOT added to `JUDGE_BACKENDS` or `PRIMARY_REVIEW_BACKENDS`
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_nova_wiring.py -v` passes
- [ ] Existing dev_loop tests still pass (`pytest packages/ai-parrot/tests/flows/dev_loop/ -v`)
- [ ] `ruff check` + `mypy` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_nova_wiring.py
import pytest
from parrot.flows.dev_loop.agent_builder import build_dispatcher
from parrot.flows.dev_loop.catalog import catalog_payload
from parrot.flows.dev_loop.dispatchers import NovaCodeDispatcher
from parrot.flows.dev_loop.models import DevAgentSpec, NovaCodeDispatchProfile


COMMON = dict(redis_url="redis://localhost:6379/0", max_concurrent=1,
              stream_ttl_seconds=60)


class TestBuildDispatcher:
    def test_nova_branch_returns_pair(self):
        d, p = build_dispatcher(DevAgentSpec(agent="nova"), **COMMON)
        assert isinstance(d, NovaCodeDispatcher)
        assert isinstance(p, NovaCodeDispatchProfile)

    def test_spec_model_overrides_config(self):
        _, p = build_dispatcher(DevAgentSpec(agent="nova", model="zai.glm-5"), **COMMON)
        assert p.model == "zai.glm-5"

    def test_default_model_is_minimax(self):
        _, p = build_dispatcher(DevAgentSpec(agent="nova"), **COMMON)
        assert p.model == "minimax.minimax-m2.5"


class TestCatalog:
    def test_nova_listed(self):
        payload = catalog_payload()
        assert any(b["id"] == "nova" for b in payload["backends"])

    def test_nova_not_in_judge_backends(self):
        from parrot.flows.dev_loop.catalog import JUDGE_BACKENDS, PRIMARY_REVIEW_BACKENDS
        assert "nova" not in JUDGE_BACKENDS
        assert "nova" not in PRIMARY_REVIEW_BACKENDS


class TestAdversarialSelector:
    def test_defaults_to_codex(self):
        """[R3] regression guard — unset config must not change behaviour."""
        from parrot.flows.dev_loop.catalog import resolve_adversarial_backend
        assert resolve_adversarial_backend(lambda k, d=None: d) == "codex"

    def test_selects_nova_when_configured(self):
        from parrot.flows.dev_loop.catalog import resolve_adversarial_backend
        getter = lambda k, d=None: "nova" if "ADVERSARIAL_BACKEND" in k else d
        assert resolve_adversarial_backend(getter) == "nova"

    def test_invalid_value_raises_naming_options(self):
        from parrot.flows.dev_loop.catalog import resolve_adversarial_backend
        getter = lambda k, d=None: "gemini" if "ADVERSARIAL_BACKEND" in k else d
        with pytest.raises(ValueError, match="codex"):
            resolve_adversarial_backend(getter)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (Module 5, §1 Non-Goals, §5 Acceptance Criteria)
2. **Check dependencies** — verify TASK-2086 and TASK-2087 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm the `build_dispatcher` branch line numbers and the `raise ValueError` position
   - Confirm `DevAgentBackend`'s second use site at `models/base.py:847`
   - Confirm `catalog.py`'s `ADVERSARIAL_BACKEND` consumers at lines 294 and 296
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/novaclient-dev-loop.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2088-nova-backend-wiring.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-08-03
**Notes**: Added `"nova"` to `DevAgentBackend` (`models/base.py`). Added a
`nova` branch to `build_dispatcher` (`agent_builder.py`, before the
`raise ValueError`), mirroring the moonshot branch:
`NovaCodeDispatcher(**common)` + `NovaCodeDispatchProfile(model=spec.model
or config_getter("DEV_LOOP_NOVA_CODE_MODEL", "minimax.minimax-m2.5"))`.
Added a `nova` `BackendInfo` row to `catalog.BACKENDS`
(`roles=("development", "adversarial")`, `transport="api"`, the 6 curated
Bedrock model ids). Converted the adversarial selector: `ADVERSARIAL_BACKEND`
constant kept as the literal `"codex"` (existing importers unaffected);
added `resolve_adversarial_backend(config_getter=None)`, validated against
`{"codex", "nova"}`, raising `ValueError` naming both options on an invalid
value; `catalog_payload()`'s two use sites (`:294`/`:296` in the original
contract) now call `resolve_adversarial_backend(config_getter)` instead of
referencing the bare constant. Added
`conf.DEV_LOOP_ADVERSARIAL_BACKEND` (fallback `"codex"`),
`conf.DEV_LOOP_NOVA_MECHANICAL_MODEL` (for TASK-2092, not yet consumed).
14 new unit tests in `test_nova_wiring.py`, all pass; ran
`test_catalog.py`/`test_agent_builder.py`/full `tests/flows/dev_loop/`
(926 passed, same 2 pre-existing unrelated failures as TASK-2086/2087,
verified identical via `git stash -u`). No new mypy error category (the
`nova` branch shows the exact same pre-existing `**dict[str, object]`
Liskov-style finding every other `build_dispatcher` branch already has).
`ruff check`: 2 new pre-existing-style (UP006 `Tuple`) findings on my own
new lines in `catalog.py`, matching the file's established (unfixed)
convention throughout — not touched, per the "insert only" instruction and
consistency with TASK-2086/2087's identical finding.

**Deviations from spec**: The task's Codebase Contract and "Files to
Create/Modify" table did not list `packages/ai-parrot/src/parrot/flows/
dev_loop/__init__.py`, but `agent_builder.py` imports `NovaCodeDispatcher`/
`NovaCodeDispatchProfile` via the *package* re-export
(`from parrot.flows.dev_loop import (...)`), not the `dispatchers`/`models`
submodules directly (per an explicit comment in `agent_builder.py`
explaining this is required so dispatcher class identities stay aligned
across every consumer, e.g. for `isinstance` checks under
`test_lazy_import.py`'s module-reload tests). Without adding both names to
`dev_loop/__init__.py`'s imports/`__all__`, `agent_builder.py` would raise
`ImportError`. Added them, mirroring the existing Moonshot/Zai entries
exactly. Verified with `python -c "import parrot.flows.dev_loop.code_review"`
/ `"import parrot.flows.dev_loop.dispatchers"` / `"import
parrot.flows.dev_loop"` (all exit 0) that this does not introduce a
circular-import regression.
