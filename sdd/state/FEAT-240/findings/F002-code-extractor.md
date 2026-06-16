---
id: F002
query_id: Q002
type: read
intent: Check CodeExtractor extract() signature, mtime, sha1, lineno stamping
executed_at: 2026-06-16T00:00:00Z
duration_ms: 2400
parent_id: null
depth: 0
---

# F002 — CodeExtractor lacks mtime, sha1, and lineno stamping

## Summary

`CodeExtractor` at `extractors/code.py` has `extract(self, file_path, source)` with
no `mtime` parameter. `_extract_class` stamps `domain_tags={"symbol_type": "class"}`
only — no `lineno`/`end_lineno`. Same for `_extract_function` (symbol_type + qualified_name
only). No sha1 computation of source content. `_make_node_id(source_uri, symbol)` and
`_get_node_text(node, source_bytes)` are module-level functions importable by subclasses.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py`
  lines: 95-100
  symbol: `CodeExtractor.extract`
  excerpt: |
    async def extract(
        self, file_path: str, source: str
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py`
  lines: 237-273
  symbol: `CodeExtractor._extract_class`
  excerpt: |
    domain_tags={"symbol_type": "class"}

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py`
  lines: 295-338
  symbol: `CodeExtractor._extract_function`
  excerpt: |
    domain_tags={"symbol_type": "function", "qualified_name": qualified_name}

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py`
  lines: 34-45
  symbol: `_make_node_id`
  excerpt: |
    def _make_node_id(source_uri: str, symbol: str) -> str:
        raw = f"{source_uri}::{symbol}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py`
  lines: 48-58
  symbol: `_get_node_text`
  excerpt: |
    def _get_node_text(node, source_bytes: bytes) -> str:
        return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

## Notes

All three additions (mtime param, sha1 stamping, lineno/end_lineno) are backward-
compatible: mtime via Optional kwarg, sha1/lineno via extra domain_tags keys.
The brainstorm's proposed changes align with the actual signatures.
