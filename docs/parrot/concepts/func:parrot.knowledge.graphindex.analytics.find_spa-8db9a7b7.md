---
type: Concept
title: find_sparse_communities()
id: func:parrot.knowledge.graphindex.analytics.find_sparse_communities
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Find communities with low internal cohesion (sparse communities).
---

# find_sparse_communities

```python
def find_sparse_communities(communities_result: Optional['CommunitiesResult'], min_size: int=3, max_cohesion: float=0.15) -> list[dict]
```

Find communities with low internal cohesion (sparse communities).

A community is considered sparse when it has enough members to be
meaningful (>= min_size) but low internal cohesion (< max_cohesion).
These represent areas where knowledge is disconnected.

Args:
    communities_result: A ``CommunitiesResult`` from FEAT-191 Louvain
        community detection.
    min_size: Minimum number of members for a community to be
        considered. Communities smaller than this are skipped.
    max_cohesion: Maximum cohesion threshold. Communities with
        cohesion >= this value are considered tight (not sparse).

Returns:
    List of dicts, each containing ``community_id``, ``size``,
    ``cohesion``, and ``top_titles`` for sparse communities.
