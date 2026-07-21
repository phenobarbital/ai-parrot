---
type: Wiki Summary
title: parrot.knowledge.wiki.file_store
id: mod:parrot.knowledge.wiki.file_store
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: In-memory wiki retrieval plane persisted as an OKF markdown bundle.
relates_to:
- concept: class:parrot.knowledge.wiki.file_store.InMemoryWikiStore
  rel: defines
- concept: mod:parrot.knowledge.okf.utils
  rel: references
- concept: mod:parrot.knowledge.wiki.export
  rel: references
- concept: mod:parrot.knowledge.wiki.store
  rel: references
---

# `parrot.knowledge.wiki.file_store`

In-memory wiki retrieval plane persisted as an OKF markdown bundle.

The SQLite-free backend (``WikiConfig.storage_backend = "memory"``):
all retrieval runs against RAM indexes — page dicts, a node-id map, a
hierarchical concept-id prefix tree, in/out edge adjacency, TF-IDF term
postings, and an embeddings map — while durability comes from a plain
**directory of OKF v0.1 markdown files**::

    {storage_dir}/pages/
    ├── index.md                  # auto-generated catalog
    ├── .embeddings.json          # vector sidecar (machine-only)
    ├── summaries/<id>.md         # YAML frontmatter + body
    ├── entities/<id>.md
    └── <category-plural>/<id>.md

The directory is therefore a valid, browsable OKF bundle at all times:
frontmatter carries the OKF fields (``type``, ``title``, ``id``,
``tags``, ``timestamp``, ``summary``, ``relates_to``) plus the wiki's
machine fields (``node_id``, ``source_id``, ``token_count``) — OKF
consumers tolerate unknown keys.

Loading walks the bundle once (lazily, on first use) and rebuilds every
index; queries never re-read files.  Mutations rewrite only the
affected page files plus ``index.md``.

## Classes

- **`InMemoryWikiStore(BaseWikiStore)`** — RAM-indexed wiki store persisted as an OKF markdown directory.
