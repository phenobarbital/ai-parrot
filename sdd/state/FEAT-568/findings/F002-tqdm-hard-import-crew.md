# F002 — `tqdm` unconditional import in core `crew.py` breaks every core-only job

**Query**: Q005 (tqdm grep + read)
**Confidence**: high

## Evidence

- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:44`:
  `from tqdm.asyncio import tqdm as async_tqdm` — **module-level, unconditional**.
- Only two other references in the same file:
  - `crew.py:227`: `self.use_tqdm: bool = kwargs.get("use_tqdm", True)` — already
    an opt-**out** runtime flag.
  - `crew.py:4159-4164`: `if self.use_tqdm: chunk_iterator = async_tqdm(...)`
    — the only call site, gated by `use_tqdm`, used purely as a **cosmetic
    progress bar** for one chunk-summarization loop.
- `tqdm` is **not declared anywhere** in `packages/ai-parrot/pyproject.toml`
  (`grep -n tqdm` → no matches) — it is present in `uv.lock` only as a
  transitive dependency of unrelated extras (huggingface/openai SDKs etc.),
  so its presence in any given job is accidental.
- CI evidence (`test-wiki-extras`, `test-core` 3.12 logs): `parrot.bots.flows`
  (imported by `parrot.flows.dev_loop.runner` → `.commands` → `.__init__`,
  and directly by dozens of test modules) fails to import with
  `ModuleNotFoundError: No module named 'tqdm'` whenever a job doesn't
  happen to pull tqdm in transitively. In the `test-core` (3.12) run this
  single import is the direct cause of ~112 of the 319 collection
  errors/cascaded failures (every test file that imports anything importing
  `parrot.bots.flows`).

## Conclusion

This is a genuine bug independent of any extras/packaging policy: the
**use** of tqdm is already fully optional at runtime (`use_tqdm` flag,
single call site), but the **import** is not. The fix is to make the import
match the existing optionality — guard it (try/except at import time, or
move the import inside the `if self.use_tqdm:` branch) rather than adding
`tqdm` as a new hard core dependency for a purely cosmetic progress bar.
Zero test changes required; this is a pure source fix.
