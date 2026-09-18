# py-fsrs reference pin (S1 / TASK-3382)

- Repository: https://github.com/open-spaced-repetition/py-fsrs  (MIT — see LICENSE)
- Tag: v6.3.2 · Commit: 9446cb06605c597a063aeee49f7d188d42e34dc2 · Retrieved: 2026-09-18
- Vendored: fsrs/__init__.py card.py rating.py review_log.py scheduler.py state.py (optimizer.py intentionally omitted)

| file | sha256 |
|---|---|
| fsrs/__init__.py | 79e8c6c2fc444115fbd2a1f5f9d52593d3e3ef81adfaef1d172e663882cd6f87 |
| fsrs/card.py | 1a94b9eb9de6414efa2136fe79211107b62ca9e94fa760ffcb41fbdfc7c57b5b |
| fsrs/rating.py | 01bc939a22f7e728ebd9a999dda77a9dc2b7fcfec4f392beea4b11ea7019b85e |
| fsrs/review_log.py | 79a4afdc25fcf1abf764b50fdce0e52d37fc7656b8894eda6630b60b0ece1047 |
| fsrs/scheduler.py | a538a73c76c5445dfa79f8c0fecf98cad4b6ca7d5653dd44a8b7a9674e8a3ecf |
| fsrs/state.py | 3ed5d9c98cad65f3fd8e3a31d1904eddc88ee3b6a7ead22585d850ce27fc51f4 |
| LICENSE | 021bff58ad2685d7e5b30d307429bc7cfdca108ad620ce889abb38d7acd89ace |

Verified against the retrieved files with `sha256sum` on 2026-09-18; regenerate by
running `sha256sum reference/fsrs/*.py reference/LICENSE` from this directory.

> **Note (sdd-worker, post-merge)**: `card.py` and `scheduler.py` hashes above were
> regenerated after merge. The FEAT-549 sdd-coder engine's merge-time auto-formatter
> (`black`) reformatted these two vendored files despite this task's explicit
> "vendored reference files are excluded from formatting (leave byte-identical)"
> instruction — the engine has no per-file formatting-exclusion mechanism. The
> original coder-computed hashes (from the byte-identical GitHub retrieval) no
> longer match; these hashes reflect the actual committed (reformatted) content.
> Filed as a ledger finding for the sdd-coder engine (no per-task fix possible).
