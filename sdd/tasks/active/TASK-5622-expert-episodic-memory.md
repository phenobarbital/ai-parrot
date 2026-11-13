# TASK-5622: Expert episodic memory — EPISODES source kind, EpisodeSource, record_episode

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2.5 / Module 7, AC12. Episodes live in the expert's wiki namespace `expert-<slug>` (brainstorm decision); `parrot/memory/episodic` is NOT used.

---

## Scope

- Add `EPISODES = "episodes"` to `KnowledgeSourceKind`.
- Create `experts/knowledge/sources/episodes.py`: `Episode` model, `record_episode(wiki_toolkit, slug, episode, *, cap=200)` (calls the wiki toolkit's `remember(wiki_name=f'expert-{slug}', text=..., title=f'episode:{...}', category='note')`), and `EpisodeSource` implementing the `KnowledgeSource` protocol (retrieval; wraps episodes as untrusted data).
- Append `EpisodeSource(self.wiki_toolkit)` to the registry's per-bundle source list.
- Tests with a fake wiki toolkit.

**NOT in scope**: Calling record_episode from the stage node (TASK-5624).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/models.py` | MODIFY | EPISODES kind |
| `packages/ai-parrot/src/parrot/experts/knowledge/sources/episodes.py` | CREATE | source + recorder |
| `packages/ai-parrot/src/parrot/experts/registry.py` | MODIFY | register source |
| `packages/ai-parrot/tests/experts/test_episodes.py` | CREATE | tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
from parrot.experts.models import ExpertBundle, KnowledgeLayer, KnowledgeSourceKind, KnowledgeSourceSpec  # verified: sources/base.py:8
from parrot.memory.compaction.tokens import TokenCounter  # verified: sources/base.py:9
```

### Existing Signatures to Use
```python
class KnowledgeSource(Protocol): kind: KnowledgeSourceKind; async def layers(self, spec, bundle, *, workspace: Path | None, counter: TokenCounter) -> list[KnowledgeLayer]  # sources/base.py:13
class KnowledgeSourceKind(str, Enum): ... KB = "kb"  # models.py:62, :71
# parrot_tools/wiki/toolkit.py:869 async def remember(self, wiki_name: str, text: str, title=None, category="note", related_pages=None) -> dict
# registry.py:245-247 sources list: ..., WikiSource(self.wiki_toolkit, namespace=f"expert-{bundle.manifest.name}"), BookstoreSource(), GraphIndexSource(),
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop` imports inside `parrot/bots/flows/core/gates/` or `parrot/experts/`~~ — forbidden (spec Decisions `gate-core-independent-of-dev-loop`).
- ~~HelixDB client / `HelixGateStore`~~ — no client in the repo; spec §8 Q1 open — do NOT implement.
- ~~`ExpertManifest.stage`~~, ~~`RosterSeat.tier`~~, ~~`WikiSource.remember`~~, ~~`DecisionService.propose`/`.record`~~ — do not exist.
- ~~`WikiSource.remember`~~ — call the toolkit's `remember`.
- Read `experts/knowledge/sources/wiki.py` for how WikiSource searches the namespace; reuse its query path for retrieval instead of inventing a search API.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/experts/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/experts/knowledge/sources/episodes.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/experts/registry.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/experts/test_episodes.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/experts/registry.py#ExpertRegistry",
    "sym:packages/ai-parrot/src/parrot/experts/models.py#KnowledgeSourceKind"
  ]
}
```

---

## Implementation Notes

- Conventions: `.claude/rules/codebase-conventions.md` (Pydantic v2, Google docstrings, `self.logger`, async I/O, no print).
- Worktree tests need `PYTHONPATH=packages/ai-parrot/src` (plus `packages/ai-parrot-integrations/src` / `packages/ai-parrot-tools/src` when touched).

---

## Implementation Blueprint

### Steps (in order)
1. Edit models.py and registry.py (import EpisodeSource at the top of registry.py next to the other source imports).
2. Create episodes.py.
3. Tests.

### Blocks

```python
# packages/ai-parrot/src/parrot/experts/models.py (MODIFY) — AFTER `    KB = "kb"` (verified: models.py:71; occurrences: 1)
    EPISODES = "episodes"
# packages/ai-parrot/src/parrot/experts/registry.py (MODIFY) — AFTER `            GraphIndexSource(),` (verified: registry.py:247; occurrences: 1)
            EpisodeSource(self.wiki_toolkit),
```
```python
# packages/ai-parrot/src/parrot/experts/knowledge/sources/episodes.py  (CREATE)
"""Per-expert episodic memory in the wiki namespace (FEAT-890 M7)."""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any
from pydantic import BaseModel, ConfigDict
from parrot.experts.models import ExpertBundle, KnowledgeLayer, KnowledgeSourceKind, KnowledgeSourceSpec
from parrot.memory.compaction.tokens import TokenCounter

logger = logging.getLogger(__name__)

class Episode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str | None
    stage: str | None
    input_digest: str
    outcome: str
    gate_resolution: str | None = None
    lesson: str = ""

async def record_episode(wiki_toolkit: Any, slug: str, episode: Episode, *, cap: int = 200) -> None:
    """Write one episode; enforce the per-expert cap (oldest first). Never raises: logs and returns."""
    # FILL IN

class EpisodeSource:
    """Retrieval source over episode notes in expert-<slug>."""
    kind = KnowledgeSourceKind.EPISODES
    def __init__(self, wiki_toolkit: Any) -> None:
        self.wiki_toolkit = wiki_toolkit
    async def layers(self, spec: KnowledgeSourceSpec, bundle: ExpertBundle, *, workspace: Path | None,
                     counter: TokenCounter) -> list[KnowledgeLayer]:
        """Top-k relevant episodes as untrusted-data layers; [] when the wiki is unavailable."""
        # FILL IN
```
**Why**: never raising from record_episode keeps memory a side effect that cannot fail a stage.

### FILL IN checklist
- [ ] cap enforcement
- [ ] retrieval + untrusted wrapping (reuse the KnowledgeLayer shape other sources produce)
- [ ] tests

---

## Acceptance Criteria

- [ ] AC12.
- [ ] Existing `test_registry.py`, `test_resolver.py` pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/experts/test_episodes.py -q`
- `pytest packages/ai-parrot/tests/experts/test_registry.py -q`
- `pytest packages/ai-parrot/tests/experts/test_resolver.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5622 expert-stages-and-delegation verified`.

---

## Completion Note

*(Agent fills this in when done)*
