# ai-parrot — LLM Wiki

> Machine-first knowledge base compiled from this repository's code and documentation by [`scripts/build_llm_wiki.py`](../../scripts/build_llm_wiki.py), using the AI-Parrot `parrot.knowledge.wiki` retrieval plane (FEAT-260).

## What's here

| Artefact | Purpose |
| --- | --- |
| `wiki.db` | SQLite retrieval plane (FTS5/BM25 + typed edges) — the machine plane an agent queries and contributes to. |
| `index.md` + category folders | OKF v0.1 markdown bundle — the human-browsable projection of every page. |
| `graph.html` | Interactive, offline knowledge-graph map (open in a browser). |
| `graph.json` | Serialized graph (nodes, edges, communities). |
| `wiki_stats.json` | Full build report. |

## Contents

- **6362** pages from **1756** Python modules and **205** documents
- **11586** typed cross-reference edges

### Pages by category

- `concept`: 912
- `entity`: 3248
- `overview`: 446
- `summary`: 1756

### Edges by relation

- `contains`: 1988
- `defines`: 4160
- `extends`: 826
- `mentions`: 340
- `references`: 4272

### Knowledge map

- [`graph.html`](./graph.html) — 1998 nodes, 6260 edges, 25 communities (modularity 0.7768)

## Querying the wiki

```python
import asyncio
from parrot.knowledge.wiki.store import create_wiki_store

async def main():
    store = create_wiki_store('parrot', backend='sqlite')
    for hit in await store.search_fts('agent crew orchestration', limit=5):
        print(hit['title'], '->', hit['concept_id'])

asyncio.run(main())
```

## Regenerating

```bash
source .venv/bin/activate
python scripts/build_llm_wiki.py --preset ai-parrot
```

_Generated 2026-07-14T22:20:29+00:00 in 24774.6 ms._
