---
id: F010
query_id: Q015,Q016,Q017
type: grep
intent: Confirm concept_id builders and every site that parses id prefixes (must learn ns::)
executed_at: 2026-08-23T02:20:00Z
depth: 0
---
# F010 — Ids are repo-relative (file:/dir:) and collide across repos; only 3 sites parse prefixes

## Summary
`file_concept_id` / `dir_concept_id` (repo_scan.py:249-256) produce `file:<relpath>` /
`dir:<relpath>` — identical strings in any two repos (`file:README.md`). Prefix-aware code
found by grep: `context.py:30 _ID_PREFIX_RE` (`^(?:file|dir|mod|pkg|doc|func|class|concept|page):`,
used at 124 to elide redundant titles in stubs) and `cli.py:417-420` (build-time prune, local
store only). `pack_results` derives the id from `concept_id|node_id|page_id` (context.py:107).
A `ns::` prefix (double colon) does not collide with the single-colon kind prefixes, and the
regex comment already notes ids may contain inner colons. Only `_ID_PREFIX_RE` needs to learn
to skip a leading `<ns>::`.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py`
  lines: 249-256
  symbol: `file_concept_id`, `dir_concept_id`
  excerpt: |
    return f"file:{PurePosixPath(rel_path)}"
    return f"dir:{PurePosixPath(rel_path) if rel_path else '.'}"
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/context.py`
  lines: 27-30, 105-126
  symbol: `_ID_PREFIX_RE`, `_stub_line`
  excerpt: |
    _ID_PREFIX_RE = re.compile(r"^(?:file|dir|mod|pkg|doc|func|class|concept|page):")
    rid = result.get("concept_id") or result.get("node_id") or result.get("page_id") or "?"
    if title and title.rstrip("/") not in (rid, _ID_PREFIX_RE.sub("", rid, count=1)):
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/context.py`
  lines: 131-190
  symbol: `pack_results`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 417-420
  symbol: `_prune_removed`
  excerpt: |
    if cid.startswith("file:") and cid not in expected_files:
    elif cid.startswith("dir:") and cid not in expected_dirs:
