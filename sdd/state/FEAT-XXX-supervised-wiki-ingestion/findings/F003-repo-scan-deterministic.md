# F003 — `repo_scan.py` is deterministic by design (suffix/size filters only)

- `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:1-21` (module
  docstring): "fully offline: no LLM, no embeddings, no external parsers."
- `repo_scan.py:41-75` — `CODE_SUFFIXES`, `DOC_SUFFIXES` (`.md .rst .txt`),
  `CONFIG_SUFFIXES`, `DEFAULT_EXCLUDE_DIRS`, `DEFAULT_EXCLUDE_NAMES`,
  `DEFAULT_MAX_FILE_BYTES` (512 KiB). Pre-ingestion filtering today =
  suffix + size + dir excludes. Nothing content-aware.
- Implication: the offline guarantee of `build` is documented behaviour —
  supervised triage must be **opt-in**, not a change to this path.

Method: direct read of first 80 lines + docstring.
