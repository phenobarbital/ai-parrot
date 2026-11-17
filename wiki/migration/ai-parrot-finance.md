# `parrot.finance` — the finance satellite

`parrot.finance` used to live inside this repository. It now ships from its own
repository, [`parrot-finance-agent`](https://github.com/phenobarbital/parrot-finance-agent),
as the distribution **`ai-parrot-finance`** — a PEP 420 satellite that merges
back into the `parrot.*` namespace exactly like `ai-parrot-embeddings` and
`ai-parrot-integrations` do.

```bash
pip install ai-parrot-finance            # core: flow, committee, schemas
pip install 'ai-parrot-finance[all]'     # + every broker/data family
pip install 'ai-parrot-finance[graph-ingest]'   # + the trading-corpus ingest path
```

Import paths are unchanged:

```python
from parrot.finance import build_committee_flow, run_trading_flow
```

## Not the same thing as `ai-parrot[finance]`

This repository still has a `finance` **extra** (`ta-lib`,
`pandas-datareader`). It is unrelated to the `ai-parrot-finance`
**distribution** — different namespaces, no conflict, and installing one has no
bearing on the other. The extra provides numeric libraries; the distribution
provides the agent system.

## What moved into the satellite

| Was | Now |
|---|---|
| `parrot_tools/technical_analysis.py` | `parrot.finance.tools.technical_analysis` |
| `parrot_tools/composite_score.py` | `parrot.finance.tools.composite_score` |

Both modules imported `.alpaca`, `.coingecko` and `.cryptoquant`, which do not
exist in `parrot_tools` — they are finance toolkits. The modules were therefore
unimportable, and took `composite_score` down with them. The originals are
replaced by shims that raise an `ImportError` naming the new path instead of a
bare `ModuleNotFoundError`.

## Changes made in this repository for the satellite

Each of these is a fix to something that was already broken, not a
finance-specific accommodation.

**Two undeclared runtime dependencies** (`proxylists`, `async-notify`). Without
them a clean install cannot import `parrot.bots` or `parrot.interfaces.http`.
Added to core.

**GraphIndex could not ingest a document corpus** (`fix(graphindex)`). Four
chained defects, each hiding the next:

1. `GraphIndexBuilder` passed `None` as the loader to
   `LoaderExtractor.extract`, so every `loader_sources` entry failed with
   `'NoneType' object has no attribute '_load'`. There is now
   `_loader_for(uri)`, plus a dependency-free `PlainTextLoader` for
   `.md/.markdown/.txt/.text/.rst/.mdx`, so a Markdown corpus indexes without
   ai-parrot-loaders installed.
2. Stage 1 gathered the three extractors under one `try`, so a missing optional
   parser (`tree_sitter_python`) discarded the other two extractors' results.
   Failures are now isolated per extractor and reported by name in
   `BuildResult.errors`.
3. `count_tokens` propagated tiktoken's BPE-download failure, which killed
   structure parsing on hosts without internet access. It now falls back to a
   character-based estimate.
4. `md_to_tree` required an LLM adapter even though the tree is derived from the
   Markdown alone. With `adapter=None` it builds the structure and skips the
   optional LLM passes — the exact path `LoaderExtractor` takes when no
   `PageIndexToolkit` is configured.

**Documentation.** `CLAUDE.md` and `.agent/CONTEXT.md` described a
repo-root `parrot/` directory that has not existed since the uv-workspace
migration, and placed the concrete toolkits in `parrot/tools/` rather than in
`parrot_tools`.
