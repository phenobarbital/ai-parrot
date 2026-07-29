---
type: Wiki Entity
title: WikiBookkeeper
id: class:parrot.knowledge.wiki.bookkeeper.WikiBookkeeper
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Manages index.md and log.md bookkeeping files for a wiki.
---

# WikiBookkeeper

Defined in [`parrot.knowledge.wiki.bookkeeper`](../summaries/mod:parrot.knowledge.wiki.bookkeeper.md).

```python
class WikiBookkeeper
```

Manages index.md and log.md bookkeeping files for a wiki.

This class is intentionally stateless — wiki directory paths are
passed to each method so the same instance can service multiple wikis.

Example::

    bk = WikiBookkeeper()
    bk.log_operation(wiki_dir, "INGEST", "source: article.md, pages: 3")
    print(bk.read_log(wiki_dir, last_n=10))

## Methods

- `def generate_index(self, tree: dict, tree_name: str, sources: Optional[list]=None, categories: Optional[list]=None) -> str` — Generate index.md content, extending OKF's output with wiki metadata.
- `def write_index(self, wiki_dir: Path, tree: Optional[dict]=None, tree_name: str='wiki', sources: Optional[list]=None, categories: Optional[list]=None) -> None` — Write (or overwrite) index.md in the wiki directory.
- `def rebuild_index(self, wiki_dir: Path, tree: Optional[dict]=None, tree_name: str='wiki', sources: Optional[list]=None) -> str` — Regenerate index.md from current state and return the content.
- `def log_operation(self, wiki_dir: Path, operation: str, details: str, timestamp: Optional[str]=None) -> None` — Append a single operation entry to log.md.
- `def read_log(self, wiki_dir: Path, last_n: int=50) -> str` — Return the last ``last_n`` lines from log.md.
