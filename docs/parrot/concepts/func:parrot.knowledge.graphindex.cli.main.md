---
type: Concept
title: main()
id: func:parrot.knowledge.graphindex.cli.main
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: CLI entry point.
---

# main

```python
def main(argv: Optional[Sequence[str]]=None) -> int
```

CLI entry point.

Args:
    argv: Optional argument vector (defaults to ``sys.argv[1:]``).

Returns:
    Process exit code (0 on success, non-zero on error).
