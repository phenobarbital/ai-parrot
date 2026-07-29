---
type: Wiki Entity
title: Community
id: class:parrot.knowledge.graphindex.communities.Community
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single community in the partition.
---

# Community

Defined in [`parrot.knowledge.graphindex.communities`](../summaries/mod:parrot.knowledge.graphindex.communities.md).

```python
class Community(BaseModel)
```

A single community in the partition.

Args:
    community_id: 16-char SHA-1 prefix of sorted member node_ids.
        Stable across runs with the same membership; changes when
        members are added or removed.
    size: Number of member nodes.
    member_node_ids: Members, centroid first, then by descending
        in-community degree.
    centroid_node_id: Member with the highest in-community degree
        (ties broken lexicographically by node_id for determinism).
    cohesion: internal_edges / (internal_edges + boundary_edges),
        in [0, 1]. 0.0 for isolated singletons.
    modularity_contribution: This community's contribution to the
        global modularity Q. The full Q is the sum of these.
    top_titles: Titles of the first ≤ 5 members in display order.
    label: Deterministic, LLM-free label summarising the community,
        derived from the most frequent salient keywords across member
        titles (see :func:`derive_community_label`). Empty string when
        no salient keyword could be extracted.
