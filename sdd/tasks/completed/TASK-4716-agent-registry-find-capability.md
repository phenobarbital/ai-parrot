# TASK-4716: AgentRegistry — roost advert on BotMetadata/BotConfig, register(roost=), find_capability (M3c)

**Feature**: FEAT-747 — Roost — local inter-agent sub-protocol over Squawk
**Spec**: `sdd/specs/local-inter-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4714, TASK-4715
**Assigned-to**: unassigned

---

## Context

Implements the `AgentRegistry` part of spec §3 **Module 3**: each registered agent advertises a
`RoostAgentConfig` on `BotMetadata.roost` / `BotConfig.roost`, `register()` and `register_bot_decorator()` accept
it as a **named** parameter (unknown kwargs are folded into `startup_config` today — registry.py ~565 — so a
`roost=` swallowed there would silently disable the feature), and `find_capability()` answers deterministically
through the extended `CapabilityRegistry`, grant-filtered for a caller (fail-closed). Resolved U3: the registry
delegates to `parrot.registry.capabilities`, it does not become a fifth directory.

---

## Scope

- Add `roost: Optional[RoostAgentConfig] = None` to `BotMetadata` (after `events_block`) and `roost: Optional[RoostAgentConfig] = Field(default=None)` to `BotConfig` (after `policies`).
- Add named `roost=` to `register()` and `register_bot_decorator()`; pass it through the decorator's `self.register(...)` call; store `roost or (bot_config.roost if bot_config else None)` on the metadata and mirror its capabilities into `self.capability_registry`.
- Add the lazy `capability_registry` property and `find_capability()` after `get_bots_by_tag`.
- Write `tests/registry/test_find_capability.py`.

**NOT in scope**: `BotMetadata.kind`/`endpoint` (FEAT-746 M13 — read via getattr only); grant glob logic beyond `fnmatch` scope filtering (TASK-4717 owns `GrantPolicy`; this task inlines the same fnmatch rule to avoid a dependency); exporting from `parrot/registry/__init__.py` (Roost names are exported by `parrot.roost`)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | Fields, `roost=` kwargs, `capability_registry`, `find_capability` |
| `packages/ai-parrot/tests/registry/test_find_capability.py` | CREATE | Unit tests incl. kwargs-not-swallowed regression |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `6cbd94131` (2026-10-26). Use these exact imports and
> signatures. Do NOT invent any import, attribute or method not listed here — verify first.

### Verified Imports
```python
from parrot.registry import AgentRegistry, BotConfig, BotMetadata               # verified: registry/__init__.py:2
from parrot.registry.capabilities.registry import CapabilityRegistry           # verified: capabilities/registry.py:19
from parrot.registry.capabilities.models import ResourceType                   # verified: capabilities/models.py:25 (+AGENT by TASK-4714)
from parrot.roost.directory import CapabilityMatch, Locality, RoostAgentConfig, locality_of, rank   # created by TASK-4715
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/registry/registry.py  (has `from __future__ import annotations` at line 9)
@dataclass
class BotMetadata:                                                                   # line 50
    events_block: Optional[Dict[str, Any]] = None  # FEAT-176: parsed 'events:' YAML block   # line 69 — anchor
class BotConfig(BaseModel):                                                          # line 227
    policies: Optional[List["PolicyRuleConfig"]] = Field(default=None)              # line 255 — anchor
class AgentRegistry:                                                                 # line 258
    def __init__(...):  self._registered_agents: Dict[str, BotMetadata] = {}         # ~line 305
    def register(self, name, factory, *, singleton=False, tags=None, priority=0, dependencies=None, replace=False,
                 at_startup=False, startup_config=None, bot_config: Optional["BotConfig"] = None, **kwargs) -> None:  # 526-540
        # line 538 anchor: `        bot_config: Optional["BotConfig"] = None,`
        # merged_kwargs = {**startup_config, **kwargs}; metadata = BotMetadata(..., bot_config=bot_config,)  (~565-579)
        # then: self._registered_agents[name] = metadata; self._collect_and_register_policies(name, factory, bot_config)
    def register_bot_decorator(self, *, name=None, priority=0, dependencies=None, singleton=False, at_startup=False,
                               startup_config=None, tags=None, **kwargs):            # line 1324
        # inner: self.register(name=bot_name, factory=cls, ..., bot_config=_bot_config, **kwargs,)  (~1401-1412)
    def get_bots_by_tag(self, tag: str) -> List[BotMetadata]:                        # line 1450 — anchor
# parrot/registry/capabilities/registry.py (after TASK-4714)
    def register_agent_capability(self, agent_name, cap_id, *, keywords=(), category=None, locality=3, cost=1.0,
                                  backing="llm_backed", kind="local", metadata=None) -> None
    def find_exact(self, query: str, *, resource_types=None, limit: int = 10) -> list[CapabilityEntry]
    # entry.metadata keys: agent_name, cap_id, category, keywords, locality, cost, backing, kind
```

### Does NOT Exist
- ~~`BotMetadata.roost` / `BotConfig.roost` / `AgentRegistry.find_capability` / `.capability_registry` — created here~~
- ~~`BotMetadata.kind` / `.endpoint` — FEAT-746 M13; never assign them here~~
- ~~`AgentRegistry.unregister` touching the capability index — out of scope; leave a FILL IN-free note only if `unregister` exists (it does: tests/registry/test_unregister.py) — call `capability_registry.unregister_agent(name)` there ONLY if the anchor is unambiguous, else skip~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/registry/registry.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/registry/test_find_capability.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#BotMetadata",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#BotConfig",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.register",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.register_bot_decorator",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.get_bots_by_tag",
    "sym:packages/ai-parrot/src/parrot/registry/capabilities/registry.py#CapabilityRegistry"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Import `RoostAgentConfig` at module top: `from ..roost.directory import RoostAgentConfig` — BotConfig is a Pydantic model and needs the real class; `parrot.roost` is lazy so this is cheap.
- `find_capability` never calls an LLM or an embedding fn: it uses `find_exact` only (AC-9).
- Caller filtering: `caller` given ⇒ look up its metadata's `roost.grant`; None/empty ⇒ return `[]` (fail-closed, AC-12); else keep matches whose cap_id `fnmatch.fnmatchcase`-es any scope.
- `include_remote=False` drops matches with `locality == REMOTE`.
- Mirror on register: for each `cap` in `roost.capabilities` call `register_agent_capability(name, cap, keywords=roost.keywords, category=<first category that prefixes cap or None>, locality=int(locality_of(...)), cost=roost.cost, backing=roost.backing, kind=getattr(metadata, 'kind', 'local'), metadata={'category_hash': roost.category_hashes.get(category)})`. On `replace=True` call `unregister_agent(name)` first.
- Async-first; Pydantic v2 models; `self.logger` / module `logger`, never `print`; Google docstrings; type hints everywhere; 120-column lines.

### References in Codebase
- `packages/ai-parrot/tests/registry/test_unregister.py`, `test_yaml_roundtrip.py` — existing behaviour that must stay green

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Never change a signature, class name or file
> path the blueprint fixes (they come from the spec's §3 Interface Skeletons).

### Steps (in order)
1. Add the import and the two fields — *why*: storage for the advert.
2. Add `roost=` to `register()` signature and metadata construction, then mirror into the index.
3. Add `roost=` to the decorator signature and its inner `self.register(...)` call — *why*: otherwise it lands in `**kwargs` → `startup_config`.
4. Add `capability_registry` + `find_capability` after `get_bots_by_tag`.
5. Write tests, including that `roost` never appears in `metadata.startup_config`.

### `packages/ai-parrot/src/parrot/registry/registry.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from ..tools.spec import AgentMCPServerSpec, ToolkitSpec, normalize_tooling' registry.py)
# AFTER — insert below `from ..tools.spec import AgentMCPServerSpec, ToolkitSpec, normalize_tooling` (verified: registry.py:40)
from ..roost.directory import RoostAgentConfig, CapabilityMatch, Locality, locality_of, rank  # FEAT-747

# occurrences: 1 (verified: grep -c "    events_block: Optional\[Dict\[str, Any\]\] = None  # FEAT-176" registry.py)
# AFTER — insert below `    events_block: Optional[Dict[str, Any]] = None  # FEAT-176: parsed 'events:' YAML block` (registry.py:69)
    roost: Optional[RoostAgentConfig] = None  # FEAT-747: Roost contract advert + carrier + grant

# occurrences: 1 (verified: grep -c '    policies: Optional\[List\["PolicyRuleConfig"\]\] = Field(default=None)' registry.py)
# AFTER — insert below `    policies: Optional[List["PolicyRuleConfig"]] = Field(default=None)` (registry.py:255)
    roost: Optional[RoostAgentConfig] = Field(default=None)  # FEAT-747

# occurrences: 1 (verified: grep -c '        bot_config: Optional\["BotConfig"\] = None,' registry.py)
# AFTER — insert below `        bot_config: Optional["BotConfig"] = None,` (registry.py:538) — register() signature
        roost: Optional[RoostAgentConfig] = None,

# FILL IN: in register(): after `metadata = BotMetadata(...)` is built add `metadata.roost = roost or getattr(bot_config,
#          "roost", None)`; after `self._registered_agents[name] = metadata` call `self._mirror_roost(name, metadata,
#          replace=replace)` — a private helper you add next to find_capability (rules in Key Constraints)
# FILL IN: register_bot_decorator(): add `roost: Optional[RoostAgentConfig] = None,` before `**kwargs,` in its
#          signature (registry.py:1334) and `roost=roost,` before `**kwargs,` in the inner self.register(...) (~1411)
```
**Why**: Each anchor was grep-counted at 1. The two decorator edits are FILL IN because `        **kwargs,` occurs more than once in the file — quote the surrounding `bot_config=_bot_config,` line to place the inner one.

### `packages/ai-parrot/src/parrot/registry/registry.py` (MODIFY (continued))
```python
# occurrences: 1 (verified: grep -c '    def get_bots_by_tag(self, tag: str) -> List\[BotMetadata\]:' registry.py)
# BEFORE — insert above `    def get_bots_by_tag(self, tag: str) -> List[BotMetadata]:` (registry.py:1450)
    @property
    def capability_registry(self) -> "CapabilityRegistry":
        """Lazily created FEAT-070 registry used as the Roost directory index (FEAT-747)."""
        reg = getattr(self, "_capability_registry", None)
        if reg is None:
            from .capabilities.registry import CapabilityRegistry  # noqa: PLC0415 — numpy import stays lazy
            reg = self._capability_registry = CapabilityRegistry()
        return reg

    def _mirror_roost(self, name: str, metadata: BotMetadata, *, replace: bool) -> None:
        """Mirror ``metadata.roost.capabilities`` into the capability index (FEAT-747)."""
        raise NotImplementedError  # FILL IN — Key Constraints, last bullet

    def find_capability(self, query: str, *, caller: Optional[str] = None, limit: int = 5,
                        include_remote: bool = True) -> List[CapabilityMatch]:
        """Deterministic directory lookup ranked by (locality, cost, -score); grant-filtered when *caller* is given.

        Never calls an LLM or an embedding function (FEAT-747 AC-9). No grant for *caller* ⇒ ``[]`` (fail-closed).
        """
        # FILL IN: find_exact(query, resource_types=[ResourceType.AGENT]) → CapabilityMatch(..., category_hash=
        #          entry.metadata.get("category_hash")) → caller filter → include_remote → rank → [:limit]
        raise NotImplementedError
```
**Why**: `capability_registry` creates the FEAT-070 registry lazily because `capabilities/registry.py` imports numpy; `ResourceType` must be imported inside `find_capability` from `.capabilities.models` (never the PBAC enum).

### FILL IN checklist
- [ ] `register()` metadata + mirror call — bounded by AC-11
- [ ] decorator `roost=` (two edits) — bounded by AC-11
- [ ] `_mirror_roost` — Key Constraints
- [ ] `find_capability` — AC-9, AC-12
- [ ] tests

---

## Acceptance Criteria

- [ ] `register(..., roost=cfg)` stores `metadata.roost` and `'roost' not in metadata.startup_config`
- [ ] `@register_agent(..., roost=cfg)` works the same (decorator path)
- [ ] `find_capability('salary')` returns the HR agent ranked first with its category hash
- [ ] `find_capability(..., caller=X)` returns `[]` when X has no grant and filters by scope otherwise
- [ ] Existing registry tests stay green (`test_unregister.py`, `test_yaml_roundtrip.py`, `test_get_instance_pbac.py`)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/registry/registry.py packages/ai-parrot/tests/registry/test_find_capability.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree prefix with
> `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`.

- `pytest packages/ai-parrot/tests/registry/test_find_capability.py -q`
- `pytest packages/ai-parrot/tests/registry/test_unregister.py -q`
- `pytest packages/ai-parrot/tests/registry/test_yaml_roundtrip.py -q`
- `pytest packages/ai-parrot/tests/registry/test_get_instance_pbac.py -q`

---

## Test Specification

```python
import pytest

from parrot.registry import AgentRegistry
from parrot.roost.directory import InterAgentGrant, RoostAgentConfig


@pytest.fixture
def registry(tmp_path, monkeypatch):
    # FILL IN: build an isolated AgentRegistry the way tests/registry/test_unregister.py does (agents_dir=tmp_path)
    ...


def _hr_cfg():
    return RoostAgentConfig(capabilities=["hr.people.salary"], categories=["hr.people"], keywords=["salary"],
                            category_hashes={"hr.people": "abc123"}, backing="deterministic")


def test_roost_not_swallowed_into_startup_config(registry, dummy_bot_cls):
    registry.register("hr", dummy_bot_cls, roost=_hr_cfg())
    meta = registry.get_metadata("hr")
    assert meta.roost is not None and "roost" not in meta.startup_config


def test_find_capability_ranked(registry, dummy_bot_cls):
    registry.register("hr", dummy_bot_cls, roost=_hr_cfg())
    (m,) = registry.find_capability("salary")
    assert m.agent_name == "hr" and m.category_hash == "abc123"


def test_grant_filter_fail_closed(registry, dummy_bot_cls):
    registry.register("hr", dummy_bot_cls, roost=_hr_cfg())
    registry.register("a", dummy_bot_cls, roost=RoostAgentConfig())
    registry.register("b", dummy_bot_cls, roost=RoostAgentConfig(grant=InterAgentGrant(scopes=["hr.*"])))
    assert registry.find_capability("salary", caller="a") == []
    assert len(registry.find_capability("salary", caller="b")) == 1
# FILL IN: dummy_bot_cls fixture — a minimal AbstractBot subclass as used in tests/registry/test_unregister.py
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug local-inter-agent --feature-id FEAT-747 --spec sdd/specs/local-inter-agent.spec.md --index sdd/tasks/index/local-inter-agent.json`)
2. **Read the spec** at `sdd/specs/local-inter-agent.spec.md` (§2 Data Models and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/local-inter-agent.json`
4. **Verify the Codebase Contract** — re-run `grep -c` on every MODIFY anchor before editing; a count that
   differs means the anchor moved, `0` means stop and report
5. **Update status** in the index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`, never rename
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4716 local-inter-agent verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (FEAT-747 execution 0b6f3a52)
**Date**: 2026-10-26
**Notes**: AgentRegistry wiring delivered; engine lint F821 (missing CapabilityRegistry import for annotation) fixed in 6bde2e4ac via TYPE_CHECKING import.
Seat: gpt-5.6-sol (codex) · Attempts: 1

**Deviations from spec**: none beyond the lint fix
