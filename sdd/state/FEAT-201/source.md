---
kind: inline
jira_key: null
fetched_at: 2026-05-28T00:00:00Z
summary_oneline: Move stores + embeddings + rerankers out of ai-parrot into a new ai-parrot-embeddings package; keep base Registry/Abstract in ai-parrot
---

# Source — FEAT-201: ai-parrot-embeddings

## Verbatim user intent

**Original (Spanish):**

> ai-parrot-embeddings -- convertir los extras de embeddings (con extras
> [arangodb|milvus|bigquery|faiss|pgvector|...]) en paquete aparte, la infra
> "base" (Registry de Embeddings, Abstract) se mantiene en ai-parrot pero los
> embeddings de cada tipo se instalan con extras del paquete nuevo
> `ai-parrot-embeddings` (ejemplo: `ai-parrot-embeddings[pgvector]`).

**Clarification (gate response):**

> move stores, embeddings, rerankers to new package ai-parrot-embedding,
> that is the requirement.

The clarification supersedes the narrower "embeddings extras" framing: the
new package owns **three subsystems** (stores, embeddings, rerankers), not
just one.

> **Naming note.** The original arg used `ai-parrot-embeddings` (plural);
> the clarification used `ai-parrot-embedding` (singular). Sibling packages
> follow the plural convention (`ai-parrot-loaders`, `-tools`, `-pipelines`).
> This proposal works in `ai-parrot-embeddings` (plural) and surfaces the
> naming choice as an open question for the user to confirm.

## Restated (English)

Create a new sibling package `ai-parrot-embeddings` under `packages/`, modeled
on the existing `ai-parrot-loaders`, `ai-parrot-pipelines`, `ai-parrot-tools`
split. The new package owns the entire **retrieval substrate**:

| Subsystem  | Source today (in ai-parrot)              | After split (in ai-parrot-embeddings) |
|------------|------------------------------------------|---------------------------------------|
| Embeddings | `parrot/embeddings/`                     | concrete backends move; base/Registry stay in core |
| Stores     | `parrot/stores/` (pgvector/milvus/...)   | concrete backends move; base/Registry stay in core |
| Rerankers  | `parrot/rerankers/`                      | concrete backends move; base/Registry stay in core |

Boundary intent:
- **Stay in `ai-parrot`:** the abstract / base infrastructure for all three
  subsystems — Registry, abstract classes / protocols, dispatcher that
  resolves a concrete implementation from a name + kwargs.
- **Move to `ai-parrot-embeddings`:** the concrete backend integrations
  (each backend's Python deps live behind an extra).
  Confirmed targets from the user's list plus codebase inspection:
  `[arangodb | milvus | bigquery | faiss | pgvector | ...]` — these are
  primarily **vector stores**, not embedding models. Embedding model
  backends (openai, google, huggingface) also live in `parrot/embeddings/`
  today and presumably move too, with their own extras.

Final install pattern (after the split):
```bash
pip install ai-parrot                          # base + Registries only
pip install ai-parrot-embeddings[pgvector]     # core + pgvector store
pip install ai-parrot-embeddings[milvus,faiss] # core + multiple stores
pip install ai-parrot-embeddings[openai]       # core + OpenAI embedding backend
pip install ai-parrot-embeddings[rerank-bge]   # core + BGE reranker (hypothetical extra name)
```

## Open ambiguities flagged at source time (to resolve via research)

1. **Package name (singular vs plural).** Original message said
   `ai-parrot-embeddings`; clarification said `ai-parrot-embedding`. Sibling
   packages all use plural. Confirm with user during Q&A. Working name:
   `ai-parrot-embeddings`.

2. **Subsystem boundaries already confirmed.** The clarification explicitly
   names all three subsystems (stores, embeddings, rerankers). Quick
   filesystem check confirms each has its own top-level module:
   `parrot/embeddings/`, `parrot/stores/`, `parrot/rerankers/`. Research
   must still distinguish these from siblings that are NOT vector stores:
   `parrot/bots/stores/`, `parrot/handlers/stores/`, `parrot/memory/.../
   store.py`, `parrot/pageindex/store.py`, etc.

3. **Current shape of extras.** Enumerate every extra in
   `packages/ai-parrot/pyproject.toml` tied to stores/embeddings/rerankers
   (e.g. `embeddings`, `milvus`, `pgvector`, `arango`, `bigquery`, plus the
   meta-extra `agents` / `agents-lite`) and classify each as "moves" vs
   "stays".

4. **Three Registry contracts.** Each subsystem likely has its own Registry
   + Abstract pair. Research must:
   - Locate `Registry` / `Abstract` for embeddings, stores, rerankers.
   - Confirm resolution strategy: direct import, lazy import string, or
     entry points (the latter is the cleanest mechanism for a satellite
     package to register classes back into a Registry that lives in core).
   - Enumerate consumers outside each subsystem (handlers, RAG pipelines,
     agents, tools).

5. **Comparable precedent.** `ai-parrot-loaders`, `-pipelines`, `-tools`
   already executed similar splits. Research must read each sibling's
   `pyproject.toml`, top-level `__init__.py`, and any bridging code in
   `ai-parrot` that consumes them, to reuse the same packaging convention
   (entry points? namespace package? lazy import? meta-extra alias?).

6. **Coupling sites that stay in core.** Pre-research scan shows these
   import or wrap vector-store / embedding logic and likely stay in core:
   - `parrot/handlers/stores/` — HTTP handlers for vector stores (probably
     stay in the web layer but import from the new package).
   - `parrot/tools/{vectorstoresearch,multistoresearch}.py` — tools that
     consume stores; stay in core (or move to ai-parrot-tools), but import
     from the new package.
   - `parrot/bots/stores/` — likely bot-side state, not vector stores;
     stays in core. Research must confirm.

7. **Downstream impact.** The existing meta-extras
   `ai-parrot[agents,images,llms,...,embeddings,...]` and the
   `agents-lite` profile will need to re-point to the new package.
   Migration aliases / deprecation policy must be considered.

8. **One package vs two.** Should stores live in `ai-parrot-embeddings`
   or in a separate `ai-parrot-vectorstores`? The clarification says one
   package (`ai-parrot-embedding`), so the working assumption is single
   package — but this is worth confirming in Q&A if the research surfaces
   strong coupling differences between subsystems.

9. **Import-stability strategy — DECIDED.** User decision (2026-05-28):
   **Option B — PEP 420 implicit namespace package.**

   > my decision is PEP 420 (namespace package), the other packages were
   > moved without take care of PEP 420, but let's stay ai-parrot-embeddings
   > using "B" choice.

   Consequences this decision locks in:
   - The new distribution `ai-parrot-embeddings` contributes submodules
     under the existing `parrot.*` namespace. All existing
     `from parrot.{embeddings,stores,rerankers} import …` sites stay
     byte-identical.
   - The host package `parrot/` (in `ai-parrot`) must be a PEP 420
     namespace package. The new package's layout must NOT include a
     top-level `__init__.py` at `src/parrot/`.
   - Existing sibling packages (`ai-parrot-loaders`, `-tools`,
     `-pipelines`) deliberately chose a different top-level
     (`parrot_loaders.*` etc.) and are out of scope for retrofitting in
     this work item.
   - Research still has to verify (a) the current shape of
     `packages/ai-parrot/src/parrot/__init__.py` so we know whether it
     blocks PEP 420 (it must be absent or namespace-compatible), and
     (b) the host pyproject's package-discovery config (must use
     `find_namespace_packages` or PEP 621 equivalent, not bare
     `find_packages`).

## Out of scope (explicit)

- Changing the embeddings API surface (signatures, return types). The split
  is purely a packaging / dependency boundary refactor.
- Removing any backend. Every backend in the current tree must remain
  installable somehow after the split.
- Re-implementing the Registry. Only its location (and possibly its
  import-resolution strategy) may change.

## Origin

- **Kind:** inline (no Jira ticket attached at proposal time).
- **Author:** Jesus Lara (`jesuslarag@gmail.com`).
- **Base branch:** `dev`.
- **Type:** feature.
