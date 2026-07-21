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

- **9030** pages from **1764** Python modules and **2828** documents
- **19053** typed cross-reference edges

### Pages by category

- `concept`: 944
- `entity`: 3253
- `overview`: 3069
- `summary`: 1764

### Edges by relation

- `contains`: 1997
- `defines`: 4197
- `extends`: 826
- `mentions`: 7751
- `references`: 4282

### Knowledge map

- [`graph.html`](./graph.html) — 2007 nodes, 6279 edges, 28 communities (modularity 0.7743)

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

_Generated 2026-07-16T08:35:23+00:00 in 93359.2 ms._
