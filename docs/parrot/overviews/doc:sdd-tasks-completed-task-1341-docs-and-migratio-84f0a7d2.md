---
type: Wiki Overview
title: 'TASK-1341: Documentation, migration notes, CONTEXT.md update'
id: doc:sdd-tasks-completed-task-1341-docs-and-migration-notes-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 9** of the spec — finalize user-facing documentation
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.google
  rel: mentions
- concept: mod:parrot.embeddings.huggingface
  rel: mentions
- concept: mod:parrot.embeddings.openai
  rel: mentions
- concept: mod:parrot.rerankers
  rel: mentions
- concept: mod:parrot.rerankers.llm
  rel: mentions
- concept: mod:parrot.rerankers.local
  rel: mentions
- concept: mod:parrot.stores
  rel: mentions
- concept: mod:parrot.stores.arango
  rel: mentions
- concept: mod:parrot.stores.bigquery
  rel: mentions
- concept: mod:parrot.stores.faiss_store
  rel: mentions
- concept: mod:parrot.stores.milvus
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
- concept: mod:parrot.stores.pgvector
  rel: mentions
- concept: mod:parrot.stores.postgres
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
---

# TASK-1341: Documentation, migration notes, CONTEXT.md update

**Feature**: FEAT-201 — ai-parrot-embeddings
**Spec**: `sdd/specs/ai-parrot-embeddings.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1337, TASK-1338, TASK-1339, TASK-1340
**Assigned-to**: unassigned

---

## Context

Implements **Module 9** of the spec — finalize user-facing documentation
once the install surface is stable. This is the last task in the
feature because the README and migration notes must reflect the final
extras inventory (determined by TASK-1334/1335/1336 and the host
pyproject changes from TASK-1337).

Reference: spec §3 Module 9.

---

## Scope

- Replace the stub `packages/ai-parrot-embeddings/README.md` (created
  in TASK-1333) with a full README documenting:
  - Package purpose (one paragraph).
  - PEP 420 namespace contribution (one paragraph — why imports stay
    `from parrot.stores.X import Y`).
  - Complete extras inventory (table of extra name → backends → install
    deps).
  - Install patterns (single backend, multiple, full).
  - Dev workflow (`uv sync --all-packages`).
  - Pointer to the spec at `sdd/specs/ai-parrot-embeddings.spec.md`
    for design rationale.
- Create
  `docs/migration/feat-201-ai-parrot-embeddings.md` with:
  - One-paragraph summary of the change.
  - Old install command → new install command mapping
    (e.g. `pip install ai-parrot[embeddings]` →
    `pip install ai-parrot ai-parrot-embeddings[huggingface,faiss,pgvector]`).
  - `[all]` and `[all-fast]` invariants (unchanged user-visible
    behavior).
  - Note on import paths (they stay byte-identical — no code change
    needed in user projects).
  - Pointer to the proposal at
    `sdd/proposals/ai-parrot-embeddings.proposal.md` for design
    history.
- Update `.agent/CONTEXT.md` "What Lives Where" section:
  - Note that backend implementations for
    `parrot.{embeddings,stores,rerankers}` may live in either
    `ai-parrot` (base/Registry/Abstract) or `ai-parrot-embeddings`
    (concrete backends).
  - The import path is unchanged regardless of which distribution
    ships the file.

**NOT in scope**:
- Adding architectural diagrams beyond what's already in the spec
  (the spec has the component diagram; the docs reference it).
- Changing the existing root README.md significantly — a brief mention
  of the new package is fine.
- Updating `docs/sdd/WORKFLOW.md` — that's a separate concern.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/README.md` | MODIFY | Replace TASK-1333 stub with full README |
| `docs/migration/feat-201-ai-parrot-embeddings.md` | CREATE | One-page migration guide |
| `.agent/CONTEXT.md` | MODIFY | Update "What Lives Where" to reflect the split |

---

## Codebase Contract (Anti-Hallucination)

### Verified Final Extras Inventory

After TASK-1334 / 1335 / 1336, the satellite pyproject should declare
these extras (exact names and shapes are decided in those tasks):

```
google           huggingface   openai
pgvector         milvus        arango         bigquery   faiss   chroma
reranker-local   reranker-llm
all              # aggregator
```

The README's install table should use these names verbatim. If a task
implementation chose different names, MIRROR THEM — do not document
what the spec hoped for if reality diverged.

### Verified `.agent/CONTEXT.md` Section to Update

```markdown
# packages/ai-parrot/.agent/CONTEXT.md (or repo root .agent/CONTEXT.md)
## What Lives Where
```
parrot/
├── clients/          # LLM provider wrappers (AbstractClient subclasses)
├── bots/             # Bot and Agent implementations
│   └── orchestration/  # AgentCrew, DAG execution
├── tools/            # Tool definitions and toolkits
├── loaders/          # Document loaders for RAG
├── vectorstores/     # PgVector, ArangoDB     ← outdated; actual dir is `stores/`
├── handlers/         # HTTP handlers (aiohttp-based)
├── memory/           # Conversation memory (Redis-backed)
└── integrations/     # Telegram, MS Teams, Slack, MCP
```
```

The current CONTEXT.md is outdated (says `vectorstores/` when the
actual dir is `stores/`). Implementation MAY fix the `vectorstores` →
`stores` discrepancy AS PART of FEAT-201's CONTEXT.md update, since
that's a one-line corrective change in the same section. Do NOT
attempt a larger rewrite of CONTEXT.md.

### Does NOT Exist (Anti-Hallucination)

- ~~`docs/migration/` directory~~ — verify with `ls docs/migration/`
  before creating. If it doesn't exist, create it.
- ~~A top-level `MIGRATION.md`~~ — use the per-feature path under
  `docs/migration/` instead, to match the convention of per-feature
  state under `sdd/state/`.
- ~~An entry in `docs/sdd/WORKFLOW.md`~~ — that doc is about the SDD
  workflow itself, not feature migrations.
- ~~A new package classifier or PyPI metadata change to the host
  pyproject~~ — TASK-1337 handles all host pyproject changes; do NOT
  touch it from this task.

---

## Implementation Notes

### Suggested README structure

```markdown
# ai-parrot-embeddings

Concrete backend implementations for the AI-Parrot retrieval stack.

## What's in this package

This satellite contributes modules to three subsystems of the
`parrot.*` namespace:

- `parrot.embeddings.{google, huggingface, openai}` — embedding backends
- `parrot.stores.{postgres, pgvector, milvus, arango, bigquery, faiss_store}` — vector stores
- `parrot.rerankers.{local, llm}` — rerankers

The abstract base classes (`AbstractEmbeddingModel`, `AbstractStore`,
`AbstractReranker`), the registries (`EmbeddingRegistry`), the dispatch
maps (`supported_embeddings`, `supported_stores`), and all shared types
(`parrot.stores.models.Document`, `SearchResult`, …) remain in the
`ai-parrot` core package.

## Import contract

This package uses **PEP 420 implicit namespace packages**. Its modules
ship directly under the existing `parrot.*` namespace — no separate
top-level. Existing imports continue to work unchanged once installed:

```python
from parrot.embeddings.huggingface import SentenceTransformerModel  # ← from satellite
from parrot.stores.pgvector import PgVectorStore                    # ← from satellite
from parrot.embeddings import EmbeddingRegistry                     # ← from core
```

## Install

| Goal | Command |
|------|---------|
| One backend                 | `pip install ai-parrot-embeddings[pgvector]` |
| Multiple                    | `pip install ai-parrot-embeddings[pgvector,milvus,huggingface]` |
| Embeddings + vector stores  | `pip install ai-parrot-embeddings[huggingface,pgvector]` |
| Rerankers                   | `pip install ai-parrot-embeddings[reranker-local]` |
| Everything                  | `pip install ai-parrot-embeddings[all]` |

## Extras

| Extra | Pulls in | Enables |
|-------|----------|---------|
| `huggingface` | `sentence-transformers`, `tokenizers`, `safetensors`, … | `parrot.embeddings.huggingface.SentenceTransformerModel` |
| `google` | `google-genai`, `google-cloud-aiplatform` | `parrot.embeddings.google.GoogleEmbeddingModel` |
| `openai` | `openai`, `tiktoken` | `parrot.embeddings.openai.OpenAIEmbeddingModel` |
| `pgvector` | `pgvector` | `parrot.stores.postgres.PgVectorStore` |
| `milvus` | `pymilvus`, `milvus-lite` | `parrot.stores.milvus.MilvusStore` |
| `arango` | `python-arango-async` | `parrot.stores.arango.ArangoDBStore` |
| `bigquery` | `google-cloud-bigquery` | `parrot.stores.bigquery.BigQueryStore` |
| `faiss` | (no extra deps; `faiss-cpu` ships with `ai-parrot` core) | `parrot.stores.faiss_store.FAISSStore` |
| `chroma` | `chromadb` | (reserved) |
| `reranker-local` | `sentence-transformers` (cross-encoder) | `parrot.rerankers.local.LocalCrossEncoderReranker` |
| `reranker-llm` | (no extra deps; uses existing LLM clients) | `parrot.rerankers.llm.LLMReranker` |
| `all` | All of the above | Full stack |

## Development

```bash
git clone https://github.com/phenobarbital/ai-parrot
cd ai-parrot
uv sync --all-packages   # installs both ai-parrot and ai-parrot-embeddings editable
uv run pytest packages/ai-parrot-embeddings/tests/
```

## Design rationale

- Spec: [`sdd/specs/ai-parrot-embeddings.spec.md`](../../sdd/specs/ai-parrot-embeddings.spec.md)
- Proposal: [`sdd/proposals/ai-parrot-embeddings.proposal.md`](../../sdd/proposals/ai-parrot-embeddings.proposal.md)
```

(Adjust the extras table to match the **actual** extras shipped by
TASK-1334/1335/1336.)

### Suggested migration doc structure

```markdown
# Migration — FEAT-201: ai-parrot-embeddings

**Released**: <version with FEAT-201 included>
**Affects**: anyone installing or vendoring AI-Parrot.

## What changed

The concrete backends for embeddings, vector stores, and rerankers
moved from the `ai-parrot` core distribution to a new sibling package
`ai-parrot-embeddings`. **Import paths are unchanged** — code such as
`from parrot.stores.pgvector import PgVectorStore` continues to work
without modification, but you must now install the satellite alongside
`ai-parrot`.

## Install command mapping

| Old | New |
|-----|-----|
| `pip install ai-parrot[embeddings]` | `pip install ai-parrot ai-parrot-embeddings[huggingface,faiss,pgvector]` |
| `pip install ai-parrot[milvus]`     | `pip install ai-parrot ai-parrot-embeddings[milvus]`                  |
| `pip install ai-parrot[arango]`     | `pip install ai-parrot ai-parrot-embeddings[arango]`                  |
| `pip install ai-parrot[chroma]`     | `pip install ai-parrot ai-parrot-embeddings[chroma]`                  |
| `pip install ai-parrot[all]`        | `pip install ai-parrot[all]` (unchanged — the meta-extra now reaches the satellite automatically) |
| `pip install ai-parrot[all-fast]`   | `pip install ai-parrot[all-fast]` (unchanged for the same reason) |

## Code changes required

**None.** All import paths (`from parrot.embeddings.X`, `from parrot.stores.X`,
`from parrot.rerankers.X`) continue to work exactly as before.

## What did NOT change

- `parrot.embeddings.EmbeddingRegistry` and the
  `supported_embeddings` dispatch.
- `parrot.stores.AbstractStore`, `supported_stores`, and all
  shared types in `parrot.stores.models`.
- `parrot.stores.{kb,parents,utils,empty,cache}` — higher-level
  abstractions stay in core.
- `parrot.rerankers.{AbstractReranker, create_reranker}` and the lazy
  `__getattr__` resolution.
- `parrot.tools.{vectorstoresearch, multistoresearch}` — core RAG
  primitives stay in core.

## Design history

- Spec: [`sdd/specs/ai-parrot-embeddings.spec.md`](../../sdd/specs/ai-parrot-embeddings.spec.md)
- Proposal: [`sdd/proposals/ai-parrot-embeddings.proposal.md`](../../sdd/proposals/ai-parrot-embeddings.proposal.md)
- Research audit: [`sdd/state/FEAT-201/`](../../sdd/state/FEAT-201/)
```

### `.agent/CONTEXT.md` patch

```markdown
parrot/
├── clients/          # LLM provider wrappers (AbstractClient subclasses)
├── bots/             # Bot and Agent implementations
│   └── orchestration/  # AgentCrew, DAG execution
├── tools/            # Tool definitions and toolkits
├── loaders/          # Document loaders for RAG
├── embeddings/       # base/registry/catalog/matryoshka — concrete backends
│                     #   (google/huggingface/openai) may ship from
│                     #   `ai-parrot-embeddings` via PEP 420 namespace merging
├── stores/           # AbstractStore + dispatch + shared models — concrete vector
│                     #   stores (pgvector/milvus/arango/bigquery/faiss_store) may
│                     #   ship from `ai-parrot-embeddings`. Sub-packages kb/, parents/,
│                     #   utils/ stay in core.
├── rerankers/        # AbstractReranker + factory — concrete rerankers (local/llm)
│                     #   may ship from `ai-parrot-embeddings`
├── handlers/         # HTTP handlers (aiohttp-based)
├── memory/           # Conversation memory (Redis-backed)
└── integrations/     # Telegram, MS Teams, Slack, MCP
```

### References in Codebase

- `packages/ai-parrot-loaders/README.md` — sibling-package README
  pattern to follow (if it exists; check first).
- Existing migration docs (if any) — match their style.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-embeddings/README.md` is more than the
      stub from TASK-1333 and includes the full extras table.
- [ ] `docs/migration/feat-201-ai-parrot-embeddings.md` exists.
- [ ] The migration doc's "Old → New" mapping uses **only extras
      names that actually exist** in the satellite pyproject (no
      hallucinated names).
- [ ] `.agent/CONTEXT.md` no longer lists `vectorstores/` as the
      directory name. (Correct it to `stores/` or document both.)
- [ ] `.agent/CONTEXT.md` mentions that backend implementations may
      live in either distribution.
- [ ] No host or satellite `pyproject.toml` change in this task.
- [ ] No code file (`.py`) change in this task.

---

## Test Specification

This task ships documentation only — no automated tests. The
acceptance criteria above are the contract.

A light sanity check is acceptable:

```python
# Optional sanity check — packages/ai-parrot-embeddings/tests/test_readme_present.py
from pathlib import Path


def test_satellite_readme_has_extras_table():
    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    # Spot-check that the README covers the main extras
    for extra in ("huggingface", "pgvector", "milvus", "all"):
        assert extra in readme, f"README missing mention of {extra!r}"


def test_migration_doc_present():
    doc = Path("docs/migration/feat-201-ai-parrot-embeddings.md")
    assert doc.exists(), f"missing migration doc at {doc}"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 9.
2. **Check dependencies** — TASK-1337, TASK-1338, TASK-1339,
   TASK-1340 must all be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — list the actual extras in the
   satellite pyproject before writing the table. Use them verbatim.
4. **Update status** in
   `sdd/tasks/index/ai-parrot-embeddings.json` → `"in-progress"`.
5. **Implement** — write the README, migration doc, CONTEXT.md patch.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker agent)
**Date**: 2026-05-28
**Notes**: Full README written with extras table, import contract, install
patterns, architecture section. Migration doc created at
docs/migration/feat-201-ai-parrot-embeddings.md with old→new install command
mapping. CONTEXT.md updated: removed outdated vectorstores/ entry, added
embeddings/, stores/, rerankers/ sections, added ai-parrot-embeddings satellite
section explaining PEP 420 approach.

**Deviations from spec**: none
