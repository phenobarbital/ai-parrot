---
type: Wiki Summary
title: parrot.knowledge.pageindex.store
id: mod:parrot.knowledge.pageindex.store
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: On-disk JSON persistence for PageIndex trees.
relates_to:
- concept: class:parrot.knowledge.pageindex.store.JSONTreeStore
  rel: defines
---

# `parrot.knowledge.pageindex.store`

On-disk JSON persistence for PageIndex trees.

Each tree is stored as ``<storage_dir>/<tree_name>.json`` and is written
atomically (temp file in the same directory followed by ``os.replace``)
so a crash mid-write cannot leave a half-written tree on disk.

## Classes

- **`JSONTreeStore`** — File-system backed registry of PageIndex trees.
