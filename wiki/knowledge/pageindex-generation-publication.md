---
title: PageIndex Generation Publication
summary: How PageIndex trees are written as immutable generations with copy-on-write, cross-process locking, body blobs, and age-based sweeping.
---

# PageIndex Generation Publication

## Purpose

PageIndex publication prevents lost updates and torn reads when multiple
processes or coroutines work on one tree. A writer builds and validates a
copy-on-write candidate, writes its immutable body blobs, and atomically
replaces the tree JSON. The JSON is the publication point; there is no
generation manifest or transaction log.

Readers therefore get the generation they loaded for the duration of their
read. The tree JSON and its referenced body blobs remain available for at
least the configured grace period, so a reader does not switch halfway
through a request to another generation. The eleven existing body readers
that resolve a node id through `NodeContentStore` retain live semantics: when
the legacy body is absent, they resolve through the live tree JSON to its
current `body_ref`. Generation-pinned readers use the node held by their
loaded tree.

## Public API

- [`GenerationInfo`](ref:parrot.knowledge.pageindex.generation.GenerationInfo) — generation id, publication timestamp, and parent generation
- [`StaleGenerationError`](ref:parrot.knowledge.pageindex.generation.StaleGenerationError) — candidate was built on an old live generation
- [`TreeLockTimeout`](ref:parrot.knowledge.pageindex.locks.TreeLockTimeout) — the per-tree writer lock was not acquired in time
- [`WriteTransaction`](ref:parrot.knowledge.pageindex.generation.WriteTransaction) — copy-on-write candidate and publication sequence
- `pageindex_get_generation` (`PageIndexToolkit.get_generation`) — returns the live generation information for a tree
- `pageindex_vacuum_tree` (`PageIndexToolkit.vacuum_tree`) — removes unreferenced bodies older than the grace period

## Configuration & Parameters

`PageIndexToolkit` accepts two publication settings:

| Parameter | Default | Description |
|---|---:|---|
| `generation_grace_s` | `3600` seconds | Minimum age before unreferenced body blobs and legacy bodies may be swept. Increase this when requests can outlive one hour. |
| `lock_timeout_s` | `30.0` seconds | Maximum time to wait for the exclusive cross-process writer lock. |

The on-disk layout is:

```text
<storage_dir>/<tree>.json
<storage_dir>/<tree>/bodies/<flat_concept_id>.<sha16>.md
<storage_dir>/.locks/<tree>.lock
```

The tree JSON stores `generation.id`, `generation.published_at`, and its
optional `generation.parent`. Each node references an immutable body with
`body_ref`. Body keys use the flattened concept id and the first 16 hex
characters of the markdown SHA-256 digest, so a body update creates a new
blob rather than overwriting one used by an older generation.

Publication takes the per-tree POSIX lock, rejects a stale candidate, validates
the candidate, writes body blobs, runs strict OKF projection, and atomically
replaces the tree JSON. A failed publication before that replacement leaves
the previous generation live. `vacuum_tree` and the opportunistic sweep remove
unreferenced blobs only after the grace period. Trees written before this
feature remain readable; their first write migrates legacy node bodies to the
identity-based layout.

## Usage Examples

```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

toolkit = PageIndexToolkit(adapter, storage_dir="./pageindex")

# The live generation is the atomic publication currently visible to readers.
generation = await toolkit.get_generation("handbook")
print(generation["id"], generation["published_at"])

# Remove only unreferenced bodies older than the configured grace period.
vacuum_report = await toolkit.vacuum_tree("handbook")
print(vacuum_report["bodies_swept"])
```

When a writer detects that another process published after its candidate was
loaded, it raises `StaleGenerationError`. The caller should reload the tree,
reapply its change, and retry; the toolkit retries its mutating operations at
most twice before surfacing the error. A `TreeLockTimeout` means the lock was
not acquired within `lock_timeout_s` and should be handled as a temporary
contention failure.

## Gotchas

- The tree JSON is the publication point. Do not introduce or expect a generation manifest.
- OKF projection is strict during publication; projection failure aborts the JSON switch.
- A reader held longer than `generation_grace_s` can outlive the retention guarantee and lose old body blobs.
- Legacy `<node_id>.md` and `<flat_concept_id>.md` sidecars remain readable until the age-based sweep removes them.

## Related

- [PageIndex — Tree-Based RAG for Document Retrieval](pageindex.md) — tree construction, retrieval, and toolkit configuration
