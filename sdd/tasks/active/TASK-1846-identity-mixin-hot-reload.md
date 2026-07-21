# TASK-1846: IdentityMixin — field injection + mtime hot reload

**Feature**: FEAT-321 — PromptBuilder Identity Capability
**Spec**: `sdd/specs/promptbuilder-identity-capability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1844, TASK-1845
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3 — the heart of the feature. `IdentityMixin` ties
the loader (TASK-1845) and the layer (TASK-1844) together: it injects file
values as identity fields at construction (preserving kwarg precedence), adds
`CAPABILITIES_LAYER` to a per-instance builder clone, and hot-reloads all five
fields on the next prompt build after an `identity/*.md` file changes.

Read spec §2 (Overview items 3–4 + Component Diagram) and §7 (Known Risks)
before implementing — the hot-reload mechanics are precisely constrained by
verified `PromptBuilder`/`AbstractBot` behavior.

---

## Scope

- CREATE `packages/ai-parrot/src/parrot/bots/mixins/identity.py` with
  `class IdentityMixin`:
  - Class attributes: `enable_identity: bool = False`,
    `identity_dir: Union[str, Path, None] = None`.
  - `__init__(self, *args, **kwargs)`: when `enable_identity` — resolve
    `identity_dir` (default
    `Path(inspect.getfile(type(self))).parent / "identity"`), call
    `load_identity(...)`, set each **non-empty** field as an instance
    attribute BEFORE `super().__init__(*args, **kwargs)` (so
    `kwargs.get(f) or getattr(self, f, None) or DEFAULT` keeps explicit
    kwargs winning and files beating class attributes). After
    `super().__init__`, set `self.capabilities` explicitly again if a file
    value exists (the `PandasAgent` path swallows the `capabilities` kwarg
    into `self._capabilities`, data.py:550,586). Record the applied
    `IdentityFields` snapshot. When flag is False: plain
    `super().__init__(*args, **kwargs)` passthrough — fully inert.
  - `async def _configure_identity(self) -> None`: guard on
    `enable_identity`; clone the agent's **effective** builder
    (`self._prompt_builder` — instance attr set by `AbstractBot.__init__`
    via `prompt_builder`/`prompt_preset` (abstract.py:533-536), else the
    inherited class attr), `add(CAPABILITIES_LAYER)`, stash TWO artifacts:
    a **pristine never-configured clone** (`self._identity_pristine`) for
    future re-configures, and assign a working clone to
    `self._prompt_builder`. Log at debug. Called explicitly by adopting
    agents after `await super().configure()` — do NOT override `configure()`.
  - `def _build_prompt(self, *args, **kwargs)`: hot-reload seam, delegates to
    `super()._build_prompt(*args, **kwargs)`. When enabled: re-run
    `load_identity` (near-free, mtime-keyed lru cache); if fields differ from
    the last-applied snapshot → update instance attributes (incl.
    `self.capabilities`), `clone()` the pristine builder, re-run
    `self._configure_prompt_builder()`-equivalent context configure (call the
    async `_configure_prompt_builder` is NOT possible here — `_build_prompt`
    is sync; instead re-clone + configure using the same context assembly:
    see Implementation Notes), **carry over transient layers** present on the
    old builder but absent from the new one (e.g. `skill_active`), then
    atomically swap `self._prompt_builder`.
- MODIFY `packages/ai-parrot/src/parrot/bots/mixins/__init__.py`: export
  `IdentityMixin` alongside `IntentRouterMixin`.
- Write unit tests (see Test Specification).

**NOT in scope**: layer/preset definitions (TASK-1844), loader internals
(TASK-1845), Porygon (TASK-1847), any edit to `parrot/bots/abstract.py` or
`PromptBuilder`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/mixins/identity.py` | CREATE | `IdentityMixin` |
| `packages/ai-parrot/src/parrot/bots/mixins/__init__.py` | MODIFY | Export `IdentityMixin` |
| `packages/ai-parrot/tests/bots/test_identity_mixin.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-21 on `dev`. Use these VERBATIM; verify anything not listed.

### Verified Imports
```python
from parrot.bots.prompts.identity import IdentityFields, load_identity  # after TASK-1845
from parrot.bots.prompts.domain_layers import CAPABILITIES_LAYER        # after TASK-1844
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.mixins import IntentRouterMixin   # existing sole export of bots/mixins/__init__.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:
    _prompt_builder: Optional[PromptBuilder] = None   # line 223 — CLASS attribute;
    # instance attr assigned in __init__ from prompt_builder kwarg (533) or
    # get_preset(prompt_preset) (535-536)
    # identity resolution in __init__ (lines 432-452):
    #   self.role = kwargs.get('role') or getattr(self, 'role', None) or DEFAULT_ROLE
    #   ... same for goal/capabilities/backstory/rationale
    #   (backstory default constant is DEFAULT_BACKHISTORY — note spelling, 443-446)
    async def _configure_prompt_builder(self) -> None: ...  # line 1179 — called ONCE from
    #   configure() (1423-1425, guarded by `not self._prompt_builder.is_configured`);
    #   builds configure_context with _resolve() pre-resolving dynamic vars inside identity
    #   fields (1200-1214); "capabilities": _resolve(getattr(self, 'capabilities', '')) at 1213;
    #   ends with self._prompt_builder.configure(configure_context) at 1240
    def _build_prompt(self, user_context="", vector_context="", conversation_context="",
                      kb_context="", pageindex_context="", metadata=None, ...)   # line 1242 — SYNC;
    #   per-request; builder.build() at 1311 / build_segments at 1310
    async def create_system_prompt(...)   # line 2733 — adds transient "skill_active" REQUEST
    #   layer via self._prompt_builder.add() at 2772 BEFORE calling _build_prompt (2774);
    #   self._prompt_builder.remove("skill_active") at 2786 after

# packages/ai-parrot/src/parrot/bots/prompts/builder.py
class PromptBuilder:
    def add(self, layer) -> PromptBuilder     # line 152 — add-or-replace by name, mutates
    def remove(self, name) -> PromptBuilder   # line 164 — NO-OP on missing name (pop(name, None))
    def get(self, name) -> Optional[PromptLayer]  # line 197
    def clone(self) -> PromptBuilder          # line 208 — deep copy, preserves _configured
    def configure(self, context) -> None      # line 223 — REPLACES layers with partial_render
    #   copies (234-241): original templates LOST afterwards; sets _configured=True
    is_configured                             # property

# Mixin pattern to mirror (flag + explicit _configure_* coroutine; NO configure() override):
# packages/ai-parrot/src/parrot/skills/mixin.py:27,57,105-108 — SkillRegistryMixin
# packages/ai-parrot/src/parrot/memory/episodic/mixin.py:77,100,181,195 — EpisodicMemoryMixin
# agents/porygon.py:322-326 — adopting agent calls the _configure_* coroutines after
#   await super().configure(...)

# packages/ai-parrot/src/parrot/bots/data.py — precedence gotcha
class PandasAgent(IntentRouterMixin, BasicAgent):   # line 514
    _prompt_builder = _build_pandas_prompt_builder()  # line 535 — SHARED class attribute
    def __init__(..., capabilities: str = None, ...)  # line 550 — stored as
    #   self._capabilities (586); the kwarg does NOT reach AbstractBot's kwargs
```

### Does NOT Exist
- ~~`parrot/bots/mixins/identity.py`~~ / ~~`IdentityMixin`~~ — created by THIS task.
- ~~mixins overriding `configure()`~~ — neither `SkillRegistryMixin` nor
  `EpisodicMemoryMixin` does; the agent calls `_configure_*()` explicitly. Follow that.
- ~~re-configuring an already-configured builder with new values~~ — IMPOSSIBLE:
  `configure()` destroys the original templates (builder.py:234-241). Always re-clone
  the pristine builder.
- ~~an async `_build_prompt`~~ — it is synchronous (abstract.py:1242). The override
  must be sync too.
- ~~`AbstractBot._configure_prompt_builder(force=...)`~~ — no such parameter; it is
  called once, guarded by `is_configured`. The mixin re-configures its OWN clone.
- ~~`PromptBuilder.reconfigure()` / `reset()`~~ — no such methods.

---

## Implementation Notes

### Hot-reload configure on a sync path
`_configure_prompt_builder` is async and one-shot-guarded, but the swap happens
inside sync `_build_prompt`. Recommended approach: after re-cloning the
pristine builder, temporarily point `self._prompt_builder` at the fresh clone
and re-run the configure-context assembly. Two acceptable implementations
(pick one, document the choice in the completion note):

1. **Reuse via loop**: schedule `self._configure_prompt_builder()` — NOT
   possible synchronously; do NOT block the running loop. Prefer option 2.
2. **Extract/replicate context assembly (recommended)**: build the configure
   context exactly as `_configure_prompt_builder` does for identity fields —
   the five fields via `getattr(self, ...)` with `_resolve`-style dynamic
   pre-resolution — and call `new_builder.configure(context)` directly. Keep
   the replicated mapping MINIMAL and reference abstract.py:1208-1227; add a
   comment anchoring it to that range so drift is discoverable. (Do NOT edit
   `abstract.py` to extract a helper — out of scope for this task; if drift
   risk feels unacceptable, raise it in the completion note for a follow-up.)

### Carry-over + atomic swap (spec §7)
```python
old = self._prompt_builder
fresh = self._identity_pristine.clone()
fresh_names = {l.name for l in fresh.layers}       # verify accessor: builder exposes
                                                   # _layers dict; use .get(name) checks
fresh.configure(context)
for name in old_layer_names_not_in(fresh):          # e.g. "skill_active"
    fresh.add(old.get(name))
self._prompt_builder = fresh                        # single assignment = atomic swap
```
`create_system_prompt` later calls `remove("skill_active")` on the NEW builder —
safe: `remove()` is a no-op on missing names (builder.py:164-174).

### Key Constraints
- Opt-in flag default False → mixin fully inert; non-adopters byte-for-byte
  unchanged (spec AC — regression-tested).
- Only inject *non-empty* file values; snapshot comparison uses the loaded
  `IdentityFields` (not rendered output).
- Comprehensive `self.logger` calls: debug on load/no-change, info on reload.
- Google-style docstrings + strict type hints throughout.
- MRO: the mixin must appear BEFORE the agent base class in adopters'
  bases so its `__init__`/`_build_prompt` run first and delegate via `super()`.

### References in Codebase
- `packages/ai-parrot/src/parrot/skills/mixin.py` — flag + `_configure_*` shape
- `packages/ai-parrot/src/parrot/memory/episodic/mixin.py:100,181,195` — opt-out default flag
- `packages/ai-parrot/tests/bots/prompts/test_abstractbot_integration.py` — bot test harness patterns

---

## Acceptance Criteria

- [ ] Agent with `enable_identity=True` + fixture `identity/` dir gets all five
      `self.*` fields from files, including `self.capabilities`.
- [ ] Explicit constructor kwarg beats file value; file beats class attribute.
- [ ] Editing `backstory.md` (content + mtime bump) → next `_build_prompt`
      output reflects the new text without reconstructing the agent.
- [ ] A transient layer added to the builder before `_build_prompt` survives a
      hot-reload swap in that same call.
- [ ] `$current_date` inside a file resolves after (re-)configure.
- [ ] Mixin with `enable_identity=False` is inert: no file reads, no layer, no
      swap; a non-adopter agent's prompt is byte-for-byte unchanged.
- [ ] `from parrot.bots.mixins import IdentityMixin` works.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/bots/test_identity_mixin.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/mixins/`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_identity_mixin.py
# Use a minimal fake agent (stub of the AbstractBot seams: _prompt_builder,
# _build_prompt, identity resolution) OR a lightweight real bot if the existing
# test harness (tests/bots/prompts/test_abstractbot_integration.py) provides one.
import os
import pytest
from parrot.bots.mixins import IdentityMixin


@pytest.fixture
def identity_dir(tmp_path):
    for f, text in {
        "role": "a test analyst",
        "goal": "answer questions",
        "capabilities": "- do X\n- do Y",
        "backstory": "context here",
        "rationale": "be concise",
    }.items():
        (tmp_path / f"{f}.md").write_text(text, encoding="utf-8")
    return tmp_path


class TestFieldInjection:
    def test_mixin_injects_fields(self, identity_dir): ...
    def test_kwarg_wins_over_file(self, identity_dir): ...
    def test_file_beats_class_attribute(self, identity_dir): ...
    def test_disabled_flag_inert(self, identity_dir): ...


class TestHotReload:
    def test_reload_on_mtime_change(self, identity_dir): ...
    def test_no_reload_when_unchanged(self, identity_dir): ...
    def test_swap_carries_transient_layers(self, identity_dir): ...
    def test_dynamic_values_resolve(self, identity_dir): ...


class TestNonAdopter:
    def test_non_adopter_prompt_unchanged(self): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1844 and TASK-1845 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code, confirm every
   listed import/signature still exists; update the contract first if drifted
4. **Update status** in `sdd/tasks/index/promptbuilder-identity-capability.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1846-identity-mixin-hot-reload.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
