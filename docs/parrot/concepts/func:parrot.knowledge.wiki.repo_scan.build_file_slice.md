---
type: Concept
title: build_file_slice()
id: func:parrot.knowledge.wiki.repo_scan.build_file_slice
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build the wiki page record for a single repository file.
---

# build_file_slice

```python
def build_file_slice(root: Path, rel_path: str, body_max_chars: int=DEFAULT_BODY_MAX_CHARS, max_file_bytes: int=DEFAULT_MAX_FILE_BYTES) -> Optional[FileSlice]
```

Build the wiki page record for a single repository file.

Args:
    root: Repository root.
    rel_path: POSIX relative path of the file.
    body_max_chars: Cap on the stored page body length.
    max_file_bytes: Files larger than this are skipped.

Returns:
    A :class:`FileSlice`, or ``None`` when the file is missing,
    binary, or oversized.
