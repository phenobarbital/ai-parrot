---
type: Concept
title: scan_repository()
id: func:parrot.knowledge.wiki.repo_scan.scan_repository
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Scan a repository into wiki page records and edges.
---

# scan_repository

```python
def scan_repository(root: Path, suffixes: Optional[Iterable[str]]=None, exclude_dirs: Optional[Iterable[str]]=None, body_max_chars: int=DEFAULT_BODY_MAX_CHARS, max_file_bytes: int=DEFAULT_MAX_FILE_BYTES, use_git: bool=True, rel_paths: Optional[Iterable[str]]=None) -> RepoScan
```

Scan a repository into wiki page records and edges.

Args:
    root: Repository root directory.
    suffixes: File suffixes to include (defaults to
        :data:`DEFAULT_SUFFIXES`).
    exclude_dirs: Extra directory names to prune.
    body_max_chars: Cap on stored page body length.
    max_file_bytes: Skip files larger than this.
    use_git: Prefer ``git ls-files`` for discovery.
    rel_paths: Explicit relative paths to scan instead of running
        discovery (used for incremental upserts).

Returns:
    A fully populated :class:`RepoScan`.
