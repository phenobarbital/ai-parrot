---
type: Wiki Entity
title: WikiProjectConfig
id: class:parrot.knowledge.wiki.project.WikiProjectConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Repository-level wiki configuration (``.parrot/wiki.json``).
---

# WikiProjectConfig

Defined in [`parrot.knowledge.wiki.project`](../summaries/mod:parrot.knowledge.wiki.project.md).

```python
class WikiProjectConfig(BaseModel)
```

Repository-level wiki configuration (``.parrot/wiki.json``).

Attributes:
    wiki_name: Wiki identifier; defaults to the repo directory name.
    storage_dir: Wiki storage directory, relative to the repo root.
    backend: Retrieval-plane backend (``sqlite`` or ``memory``).
    include_suffixes: File suffixes scanned into the wiki; empty
        means the scanner defaults.
    exclude_dirs: Extra directory names pruned during scans.
    body_max_chars: Cap on stored page body length.
    max_file_kb: Files larger than this many KiB are skipped.
    claude: Claude Code integration settings.

## Methods

- `def storage_path(self, root: Path) -> Path` — Resolve the wiki storage directory against the repo root.
- `def db_path(self, root: Path) -> Path` — Path of the SQLite retrieval plane (sqlite backend).
- `def is_built(self, root: Path) -> bool` — Whether the retrieval plane exists on disk for this repo.
