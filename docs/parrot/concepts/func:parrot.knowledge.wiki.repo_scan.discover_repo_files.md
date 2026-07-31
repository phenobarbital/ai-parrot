---
type: Concept
title: discover_repo_files()
id: func:parrot.knowledge.wiki.repo_scan.discover_repo_files
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Enumerate candidate source files under ``root``.
---

# discover_repo_files

```python
def discover_repo_files(root: Path, suffixes: Optional[Iterable[str]]=None, exclude_dirs: Optional[Iterable[str]]=None, use_git: bool=True) -> list[str]
```

Enumerate candidate source files under ``root``.

Prefers ``git ls-files`` (tracked + untracked-but-not-ignored, so
``.gitignore`` is respected) and falls back to a filesystem walk
with :data:`DEFAULT_EXCLUDE_DIRS` pruning when ``root`` is not a
git repository.

Args:
    root: Repository root directory.
    suffixes: File suffixes to keep (defaults to
        :data:`DEFAULT_SUFFIXES`).
    exclude_dirs: Directory names to prune (merged with defaults).
    use_git: Set ``False`` to force the filesystem walk.

Returns:
    Sorted list of POSIX-style relative paths.
