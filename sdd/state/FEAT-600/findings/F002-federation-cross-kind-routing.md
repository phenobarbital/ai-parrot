---
id: F002
query_id: Q002
type: wiki_page+read
intent: FederatedWikiStore routes bare ids by kind prefix to whichever overlay declares it and hydrates cross-kind neighbors
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F002 — FederatedWikiStore routes bare ids by kind prefix to whichever overlay declares it and hydrates cross-kind neighbors

## Summary

_route() splits a namespaced id; for an unqualified id it calls _route_bare_overlay_id(), which extracts the kind (`_BARE_ID_KIND_RE`) and returns the overlay namespace whose overlay_prefixes contain it. neighbors() (L976-1059) applies three layers: outgoing hydration of foreign-qualified ids, overlay outgoing-to-code (neighbor kind NOT in the overlay's prefixes → returned unqualified and hydrated from the local plane), and incoming edges folded from every overlay (_overlay_incoming_edges iterates all handles with prefixes). Nothing is ledger-specific: the loops at L682 and L1197 iterate every handle, so a second overlay is supported by construction.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py`
  lines: 885-916
  symbol: `FederatedWikiStore._route`
  excerpt: |
    overlay_ns = self._route_bare_overlay_id(page_id) … return handle, page_id, True
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py`
  lines: 917-930
  symbol: `FederatedWikiStore._route_bare_overlay_id`
  excerpt: |
    match = _BARE_ID_KIND_RE.match(page_id) … kind = match.group(1)
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py`
  lines: 976-1059
  symbol: `FederatedWikiStore.neighbors`
  excerpt: |
    2. Overlay outgoing-to-code: when the seed is in an overlay namespace and a neighbor's kind is NOT in that overlay's prefixes, return the neighbor unqualified and hydrated
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py`
  lines: 1133-1180
  symbol: `FederatedWikiStore._overlay_requalify_neighbors / _overlay_incoming_edges`
  excerpt: |
    if kind not in overlay_handle.config.overlay_prefixes
- path: `tests/knowledge/wiki/test_federation_overlay.py`
  lines: 1-
  symbol: `TestOverlayOutgoingEdges / TestLocalIncomingFromOverlay`
  excerpt: |
    Tests for FEAT-566 Module 13: Federation overlay namespace routing

## Notes

Two overlays declaring the same kind would be ambiguous (first match wins) — `table`/`schema`/`source` collide with nothing today (F019). Spike 2 of the brainstorm is largely answered by the code and its tests; a two-overlay test is still worth adding.
