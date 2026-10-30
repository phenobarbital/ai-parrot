# TASK-4926: `ExpertRegistry` — two roots, seeding, build, register, deny rule

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4917, TASK-4920, TASK-4921, TASK-4922, TASK-4924, TASK-4925, TASK-4927, TASK-4929
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (registry part), U3, G1, G7, G9, §8 Q2/Q3/Q7. The registry is where every piece meets:

1. discover the package-bundled root then `AGENTS_DIR/experts` (TASK-4925), overlay them with `ExpertView`;
2. per bundle: probe the `expert-<slug>` wiki namespace, **seed** it from Tier-1 knowledge when empty, reject the
   bundle when it is still empty or the store is not writable (TASK-4921);
3. build the toolkits, the allowlist and the `ModelConfig` (TASK-4917), the resolver with its sources
   (TASK-4919–TASK-4922), and the `ExpertAgent` (TASK-4924);
4. `AgentRegistry.register_instance(name, agent, tags=…)`, then push the non-delegation PBAC rule through the
   public `register_db_bot_policies` (verified: `register_instance` registers no policies).

Toolkit resolution by name (`expert.yaml` `toolkits`) is a small factory owned here:
`LLMWikiToolkit` → the shared wiki toolkit; `BookstoreToolkit` → built only when a `Bookstore` was passed (it
needs library locations; none exist by default — WARNING and continue); `CVEToolkit` → `parrot_tools.security.cve`
(TASK-4929), imported lazily, built with `store_resolver=wiki_source.store_for`; `ExpertKnowledgeToolkit` →
`parrot_tools.experts` (TASK-4927); any other name → WARNING and skip. Imports of `parrot_tools` are lazy so the
core package never hard-requires the tools distribution.

---

## Scope

- Create `experts/registry.py` with `ExpertRegistry` (`__init__`, `load`, `get`, `names`, `report`, `workspace`).
- Write `test_registry.py` against fake wiki toolkit + `InMemoryWikiStore`, a stub `AgentRegistry` evaluator and a
  stubbed LLM.

**NOT in scope**: host wiring (TASK-4933), shipped bundles (TASK-4930/TASK-4931), end-to-end tests (TASK-4934).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/registry.py` | CREATE | `ExpertRegistry` |
| `packages/ai-parrot/tests/experts/test_registry.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.conf import AGENTS_DIR                          # verified: parrot/conf.py:181
from parrot.registry.registry import AgentRegistry          # verified: parrot/registry/registry.py (class AgentRegistry, line 302)
from parrot.knowledge.wiki.file_store import InMemoryWikiStore   # verified: wiki/file_store.py:74 (tests only)
from parrot.experts.loader import BUNDLED_EXPERTS_DIR, EXPERTS_DIRNAME, discover_expert_bundles   # TASK-4925
from parrot.experts.view import ExpertView                   # TASK-4925
from parrot.experts.agent import ExpertAgent                 # TASK-4924
from parrot.experts.policy import effective_allowlist, effective_toolkits, expert_policy_rules, model_config_for   # TASK-4917
from parrot.experts.knowledge.resolver import KnowledgeResolver   # TASK-4919
from parrot.experts.knowledge.sources.bundled import BundledSource       # TASK-4920
from parrot.experts.knowledge.sources.workspace import WorkspaceSource   # TASK-4920
from parrot.experts.knowledge.sources.adr import ADRSource               # TASK-4920
from parrot.experts.knowledge.sources.wiki import WikiSource             # TASK-4921
from parrot.experts.knowledge.sources.bookstore import BookstoreSource   # TASK-4922
from parrot.experts.knowledge.sources.graphindex import GraphIndexSource # TASK-4922
from parrot.experts.models import DuplicateExpertError, ExpertBundle, ExpertKnowledgeError   # TASK-4914
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/registry/registry.py
def register_instance(self, name: str, instance: AbstractBot, *, tags: Optional[Iterable[str]] = None,
                      priority: int = 0, replace: bool = False) -> None    # line 633 — WARNS (does not raise) on duplicate
def register_db_bot_policies(self, name: str, permissions: "dict | list | None") -> int   # line 507 — 0 when no evaluator
def has(self, name: str) -> bool                                           # line 668
def get_metadata(self, name: str) -> Optional[BotMetadata]                 # line 695
def get_bots_by_tag(self, tag: str) -> List[BotMetadata]                   # line 1565
@property def evaluator(self) -> Any                                       # line 390
# parrot_tools (lazy imports only):
#   parrot_tools.wiki.toolkit.LLMWikiToolkit(pageindex, graphindex, okf, config: WikiConfig, agent_id="agent",
#       store: Optional[BaseWikiStore] = None, confine_sources=False, **kwargs)   # toolkit.py:82
#   parrot.knowledge.bookstore.toolkit.BookstoreToolkit(bookstore: Bookstore, **kwargs)   # bookstore/toolkit.py:39
#   parrot_tools.security.cve.CVEToolkit(*, store_resolver=…, …)   # TASK-4929
#   parrot_tools.experts.ExpertKnowledgeToolkit(context, *, wiki, bookstore, decisions=None)   # TASK-4927
```

### Does NOT Exist
- ~~`AgentRegistry.register_instance(..., policies=…)`~~ — no policy parameter; use `register_db_bot_policies` after it.
- ~~`AgentRegistry._registered_agents` access~~ — private; use `has()` / `get_metadata()`.
- ~~a default `Bookstore`~~ — `Bookstore(locations, …)` raises without locations (`library.py:192-199`).
- ~~a toolkit registry by class name in core~~ — the name → toolkit factory is local to this module.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/experts/registry.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/experts/test_registry.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.register_instance",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.register_db_bot_policies",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.has",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.get_bots_by_tag"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Duplicates: within one root → `DuplicateExpertError` (raise, AC1); across roots → shadowing (report, AC22).
  Check `agent_registry.has(name)` before `register_instance` and raise `DuplicateExpertError` if a non-expert agent
  already uses the name (never silently replace it).
- Skip reasons in `report()["skipped"]`: `"empty-wiki-namespace"`, `"wiki-not-writable"`, plus the loader's.
  A skipped bundle never stops `load()`.
- Tags: `{"expert", f"expert:{name}", f"origin:{bundle.origin}"}`.
- `seed_knowledge: bool = True` constructor flag — tests that want a pure probe pass `False` (spec §7).
- Shared Tier-2 dir: `agents_dir / "knowledge"` when it is a directory, else `None`.

---

## Implementation Blueprint

### Steps (in order)
1. Constructor + `report`/`names`/`get` — *why*: trivial accessors the tests use first.
2. `_discover` (two roots + view) and `_admit` (probe/seed/reject) — *why*: AC19, AC22, AC23.
3. `_toolkits_for` factory and `_build` — then `load()` wiring + PBAC push (AC20).

### `packages/ai-parrot/src/parrot/experts/registry.py` (CREATE)
```python
"""ExpertRegistry: discover, seed, build and register domain experts (FEAT-778 M2)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from parrot.conf import AGENTS_DIR
from parrot.experts.agent import ExpertAgent
from parrot.experts.knowledge.resolver import KnowledgeResolver
from parrot.experts.knowledge.sources.wiki import WikiSource
from parrot.experts.loader import BUNDLED_EXPERTS_DIR, EXPERTS_DIRNAME, discover_expert_bundles
from parrot.experts.models import DuplicateExpertError, ExpertBundle, ExpertKnowledgeError
from parrot.experts.policy import effective_allowlist, effective_toolkits, expert_policy_rules, model_config_for
from parrot.experts.view import ExpertView


class ExpertRegistry:
    """Owns expert bundles and the ExpertAgents built from them; registers them into AgentRegistry."""

    def __init__(self, *, agent_registry: Any, agents_dir: Path | None = None, workspace: Path | None = None,
                 bundled_dir: Path | None = BUNDLED_EXPERTS_DIR, wiki_toolkit: Any = None, bookstore: Any = None,
                 decisions: Any = None, seed_knowledge: bool = True) -> None:
        self.agent_registry = agent_registry
        self.agents_dir = Path(agents_dir or AGENTS_DIR)
        self.workspace = workspace or self.agents_dir
        self.bundled_dir = bundled_dir
        self.wiki_toolkit = wiki_toolkit
        self.bookstore = bookstore
        self.decisions = decisions
        self.seed_knowledge = seed_knowledge
        self._experts: dict[str, ExpertAgent] = {}
        self._report: dict[str, Any] = {"loaded": [], "skipped": [], "shadowing": {}, "seeded": {}}
        self.logger = logging.getLogger(__name__)

    def report(self) -> dict[str, Any]:
        return {key: (dict(value) if isinstance(value, dict) else list(value)) for key, value in self._report.items()}

    def names(self) -> list[str]:
        return sorted(self._experts)

    def get(self, name: str, *, tenant: str | None = None) -> ExpertAgent:
        """KeyError when unknown. FILL IN: tenant views — phase-1 returns the global instance; record in notes."""
        return self._experts[name]

    async def load(self) -> int:
        """Discover → admit (probe/seed) → build → register → PBAC rule. Returns the number registered."""
        for bundle in self._discover():
            if not await self._admit(bundle):
                continue
            agent = await self._build(bundle)
            name = bundle.manifest.name
            if self.agent_registry.has(name):
                raise DuplicateExpertError(f"agent name {name!r} is already registered")
            self.agent_registry.register_instance(name, agent, tags={"expert", f"expert:{name}", f"origin:{bundle.origin}"})
            self.agent_registry.register_db_bot_policies(name, expert_policy_rules(bundle.manifest))
            self._experts[name] = agent
            self._report["loaded"].append({"name": name, "origin": bundle.origin})
        return len(self._experts)
```

### `packages/ai-parrot/src/parrot/experts/registry.py` (CREATE, continued — methods of `ExpertRegistry`)
```python
    def _discover(self) -> list[ExpertBundle]:
        """bundled root then workspace root; within-root duplicates raise; cross-root names shadow."""
        bundled, skipped_b = discover_expert_bundles(self.bundled_dir, origin="bundled") if self.bundled_dir else ([], [])
        workspace, skipped_w = discover_expert_bundles(self.agents_dir / EXPERTS_DIRNAME, origin="workspace")
        self._report["skipped"].extend([*skipped_b, *skipped_w])
        # FILL IN: raise DuplicateExpertError on a repeated name inside `bundled` or inside `workspace`;
        # view = ExpertView(bundled, workspace, label="workspace"); self._report["shadowing"].update(view.shadowing)
        return []

    async def _admit(self, bundle: ExpertBundle) -> bool:
        """Probe the namespace, seed from Tier-1 when empty, reject when still empty or not writable (Q2, G9)."""
        source = WikiSource(self.wiki_toolkit, namespace=f"expert-{bundle.manifest.name}")
        # FILL IN: n = await source.probe(); if n == 0 and self.seed_knowledge and bundle.knowledge_files:
        #   n = await source.seed(bundle.knowledge_files, asserted_by=f"expert:{name}"); report["seeded"][name] = n
        # map ExpertKnowledgeError to skip reason "wiki-not-writable" or "empty-wiki-namespace"; ERROR log;
        # append {"path": str(bundle.root), "reason": …}; return False — bounded by AC19, AC23
        return True

    def _toolkits_for(self, bundle: ExpertBundle, wiki_source: WikiSource) -> list[Any]:
        """Name → toolkit factory (see Context); unknown names WARNING + skip; parrot_tools imported lazily."""
        # FILL IN — bounded by AC10 (names) and the Bookstore-optional rule
        return []

    async def _build(self, bundle: ExpertBundle) -> ExpertAgent:
        """Resolver with sources per manifest, toolkits, allowlist, ModelConfig → ExpertAgent."""
        # FILL IN: sources = [BundledSource(None), WorkspaceSource(shared Tier-2 dir), WikiSource(...)] plus
        # ADRSource(self.decisions) when decisions is set, BookstoreSource(), GraphIndexSource();
        # toolkits = self._toolkits_for(...); discovered = [t.name for tk in toolkits for t in tk.get_tools()];
        # ExpertAgent(bundle, resolver=KnowledgeResolver(sources), model_config=model_config_for(tier),
        #             toolkits=toolkits, allowed_tools=effective_allowlist(manifest, discovered), workspace=…)
        raise NotImplementedError
```
**Why this shape**: admission runs before any agent is built, so a rejected bundle costs nothing; the PBAC push
uses the public DB-path registrar because `register_instance` does not register policies.

### FILL IN checklist
- [ ] `_discover` — duplicates and view; AC1, AC22.
- [ ] `_admit` — probe/seed/reject and report; AC19, AC23.
- [ ] `_toolkits_for` — factory; AC10.
- [ ] `_build` — sources, toolkits, agent; AC10, AC27.
- [ ] `get(tenant=…)` — record that tenant views are global in phase 1 if you keep it.

---

## Acceptance Criteria

- [ ] AC1 — duplicate name within one root raises `DuplicateExpertError`; malformed bundles are skipped.
- [ ] AC19 — empty or unresolvable namespace → bundle not registered, ERROR log, reason in `report()["skipped"]`.
- [ ] AC20 — `register_db_bot_policies` receives exactly the deny rule per loaded expert; with no evaluator it
      returns 0 and loading still succeeds.
- [ ] AC22 — workspace shadows bundled (reported); `global_only` bundled wins; tags include `origin:…`.
- [ ] AC23 — empty namespace is seeded once; a second `load()` on a fresh registry writes nothing new.
- [ ] `get_bots_by_tag("expert")` returns every loaded expert.
- [ ] `ruff check` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_registry.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/experts/test_registry.py — fake wiki toolkit over InMemoryWikiStore, real AgentRegistry
async def test_duplicate_expert_fails_load(tmp_path): ...                   # FILL IN
async def test_registry_registers_tagged_instance(expert_bundle): ...       # FILL IN
async def test_registry_rejects_empty_wiki_namespace(tmp_path): ...         # FILL IN
async def test_registry_seeds_empty_namespace_from_tier1(expert_bundle): ...  # FILL IN
async def test_seed_skipped_without_knowledge_files_then_rejected(tmp_path): ...  # FILL IN
async def test_workspace_bundle_shadows_bundled(tmp_path): ...              # FILL IN
async def test_registry_pushes_deny_rule_to_evaluator(expert_bundle): ...  # FILL IN: fake evaluator.load_policies
async def test_unknown_toolkit_name_is_skipped(expert_bundle, caplog): ...  # FILL IN
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug domain-experts --feature-id FEAT-778`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/domain-experts.json`
4. **Verify the Codebase Contract** — before writing ANY code, confirm every import and signature still exists;
   if anything changed, update the contract FIRST. Never reference a name not in the contract without verifying it.
5. **Update status** in `sdd/tasks/index/domain-experts.json` → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
   (add `packages/ai-parrot-server/src` when the task touches the server) and `ruff check` the files you changed
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4926 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker; Seat: gpt-5.6-terra (codex) · Attempts: 1
**Date**: 2026-10-30
**Notes**: Merged; task-tier and chunk merge-tier validation green.

**Deviations from spec**: none
