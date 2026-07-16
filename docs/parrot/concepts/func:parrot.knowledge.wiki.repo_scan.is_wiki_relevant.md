---
type: Concept
title: is_wiki_relevant()
id: func:parrot.knowledge.wiki.repo_scan.is_wiki_relevant
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Whether a repository-relative path is in wiki scope.
---

# is_wiki_relevant

```python
def is_wiki_relevant(rel_path: str, suffixes: Optional[Iterable[str]]=None, exclude_dirs: Optional[Iterable[str]]=None) -> bool
```

Whether a repository-relative path is in wiki scope.

Single source of truth for the selection filter, shared by full
discovery (:func:`discover_repo_files`) and incremental upserts so
the two paths can never disagree about what belongs in the wiki.

Args:
    rel_path: POSIX-style path relative to the repository root.
    suffixes: File suffixes to keep (defaults to
        :data:`DEFAULT_SUFFIXES`).
    exclude_dirs: Extra exclusions (merged with
        :data:`DEFAULT_EXCLUDE_DIRS`): a bare name (``"vendor"``)
        prunes any directory of that name; an entry containing
        ``/`` (``"docs/wiki"``) prunes that root-relative path
        prefix only.

Returns:
    ``True`` when the file should be scanned into the wiki.
