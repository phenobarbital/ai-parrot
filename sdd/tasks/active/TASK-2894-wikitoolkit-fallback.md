# TASK-2894: Wire the detection fallback into wikitoolkit's three LLM resolution points

**Feature**: FEAT-531 — Auto-detect Claude Code / Codex CLI and default wikitoolkit + bookstore's LLM to it
**Spec**: `sdd/specs/wikitoolkit-cli-llm-fallback.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2892
**Assigned-to**: unassigned

---

## Context

This is Module 3 of FEAT-531 (spec §3). `wiki/cli.py` has three places that require an
explicit env var for an LLM and otherwise error/skip: `_extract_into_graph` (`WIKI_EXTRACT_LLM`),
and the `ingest` command's light/heavy pair (`_resolve_model_id` + `_build_triage_adapters`,
driven by `WIKI_LIGHTWEIGHT_MODEL` / `WIKI_MODEL`). This task adds the same detection fallback
used in TASK-2893, respecting `wiki/cli.py`'s own navconfig-aware `_env_setting()` convention
(different from bookstore's plain `os.environ.get`), and respecting the same-provider
constraint documented in `_build_triage_adapters`'s own docstring.

---

## Scope

### Part A — `_extract_into_graph` (`WIKI_EXTRACT_LLM`)

- Where the function currently does:
  ```python
  spec = _env_setting("WIKI_EXTRACT_LLM")
  if not spec:
      click.echo("[extract skipped: set WIKI_EXTRACT_LLM (e.g. 'anthropic:claude-haiku-4-5') to enable]")
      return None
  ```
  add a fallback: if `spec` is falsy and `_env_setting("PARROT_NO_AUTO_LLM")` is falsy, call
  `detect_coding_agent_llm()`; if it returns a spec, use it and `click.echo` a message naming
  the auto-selected spec and `WIKI_EXTRACT_LLM` as the override, instead of the "[extract
  skipped...]" message. If detection also misses, keep the existing skip message unchanged.

### Part B — the `ingest` command's light/heavy pair (`WIKI_MODEL` / `WIKI_LIGHTWEIGHT_MODEL`)

- Immediately before the existing lines
  ```python
  lightweight_model = _resolve_model_id(lightweight_model_opt, "WIKI_LIGHTWEIGHT_MODEL")
  model = _resolve_model_id(model_opt, "WIKI_MODEL")
  ```
  (currently at `wiki/cli.py:3714-3715`), pre-resolve both values from their CLI flag or env
  var (`lightweight_model_opt or _env_setting("WIKI_LIGHTWEIGHT_MODEL")`, and the equivalent
  for `model_opt`/`WIKI_MODEL`). **Only if both are still falsy** (neither CLI flag nor env
  var supplied either one) and `_env_setting("PARROT_NO_AUTO_LLM")` is falsy, call
  `detect_coding_agent_llm()` once; if it returns a spec, use that **same** spec string for
  both `lightweight_model` and `model`, and `click.echo` a visible message. Then pass the
  (possibly now-populated) values into the existing `_resolve_model_id(...)` calls unchanged —
  `_resolve_model_id` will simply see a truthy `cli_value` and short-circuit, so its own
  signature and behavior are untouched.
  - If only one of the two is already set (CLI flag or env var) and the other is not, do
    **not** auto-detect — fall through to the existing `_resolve_model_id` calls exactly as
    today (this preserves the `ClickException` for the genuinely-missing one, per spec §3
    Module 3 / Known Risks "light/heavy provider mismatch").
- Write unit tests for all branches described above.

**NOT in scope**:
- Any change to `bookstore/_llm.py` — that is TASK-2893.
- Any change to `parrot/clients/detection.py`, `_resolve_model_id()`'s signature, or
  `_build_triage_adapters()`'s signature — call it exactly as today once both values are
  pre-resolved.
- Any other `WIKI_*` env var or command in `wiki/cli.py` not named above. If you discover a
  fourth LLM-resolution call site while reading the file (spec §8 flags this as an open
  question), do NOT silently fix it — note it in this task's Completion Note instead and leave
  it for a follow-up.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Add detection fallback to `_extract_into_graph` and to the `ingest` command's light/heavy resolution (~lines 3714-3716) |
| `packages/ai-parrot/tests/knowledge/wiki/test_cli.py` | MODIFY | Add unit tests for the new fallback behavior (append; do not restructure existing tests) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.detection import detect_coding_agent_llm  # verified: TASK-2892 creates packages/ai-parrot/src/parrot/clients/detection.py
```
Import lazily, inside each function body (`_extract_into_graph` already does lazy imports for
its other heavy dependencies at lines 2717-2721 — follow that same pattern).

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def _env_setting(name: str) -> str | None:  # line 464-479
    """navconfig-aware; falls back to os.environ when navconfig is unavailable."""

def _extract_into_graph(
    root: Path,
    config: WikiProjectConfig,
    text: str,
    source_uri: str,
    asserted_by: str,
    run_id: str | None,
) -> dict[str, Any] | None:                  # line 2694-2743
    spec = _env_setting("WIKI_EXTRACT_LLM")  # line 2712 — THIS is where the fallback is added
    if not spec:
        click.echo("[extract skipped: set WIKI_EXTRACT_LLM (e.g. 'anthropic:claude-haiku-4-5') to enable]")  # line 2714
        return None

def _resolve_model_id(cli_value: str | None, env_name: str) -> str:  # line 3409-3428
    value = cli_value or _env_setting(env_name)
    if not value:
        raise click.ClickException(f"No model configured — pass the flag or set ${env_name} ...")
    return value

def _build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]:  # line 3431-3462
    ...

# Call site inside the `ingest` command (only caller of _resolve_model_id in the whole file):
lightweight_model = _resolve_model_id(lightweight_model_opt, "WIKI_LIGHTWEIGHT_MODEL")  # line 3714 — pre-resolve BEFORE this line
model = _resolve_model_id(model_opt, "WIKI_MODEL")                                      # line 3715 — pre-resolve BEFORE this line
light_adapter, heavy_adapter, light_model_id, same_provider = _build_triage_adapters(lightweight_model, model)  # line 3716 — unchanged
```

### Does NOT Exist
- ~~A `PARROT_NO_AUTO_LLM` check anywhere in `wiki/cli.py` today~~ — does not exist yet; this
  task introduces the first read of it, via `_env_setting()` (matching this file's existing
  navconfig-aware convention — do NOT use plain `os.environ.get` here, unlike `_llm.py`).
- ~~Any other caller of `_resolve_model_id`~~ — confirmed: the two call sites at lines 3714-3715
  are the only ones in the file. Do not add generic auto-detection logic inside
  `_resolve_model_id` itself (it only ever sees one variable at a time and cannot enforce the
  "both unset together" rule) — the pre-resolution must happen at the call site.
- ~~A fourth `WIKI_*`-model-driven LLM resolution point~~ — not found by this spec's research;
  verify with `grep -n "LLMFactory.create\|_env_setting(\"WIKI" packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  before closing this task, and note the result in the Completion Note either way.

---

## Implementation Notes

### Pattern to Follow (Part A)
```python
def _extract_into_graph(root, config, text, source_uri, asserted_by, run_id):
    spec = _env_setting("WIKI_EXTRACT_LLM")
    if not spec and not _env_setting("PARROT_NO_AUTO_LLM"):
        from parrot.clients.detection import detect_coding_agent_llm

        detected = detect_coding_agent_llm()
        if detected:
            click.echo(
                f"[auto-selected {detected} for WIKI_EXTRACT_LLM — a coding-agent CLI "
                "session was detected. Set WIKI_EXTRACT_LLM to override, or "
                "PARROT_NO_AUTO_LLM=1 to disable auto-detection.]"
            )
            spec = detected
    if not spec:
        click.echo("[extract skipped: set WIKI_EXTRACT_LLM (e.g. 'anthropic:claude-haiku-4-5') to enable]")
        return None
    try:
        ...  # unchanged
```

### Pattern to Follow (Part B)
```python
lightweight_model_value = lightweight_model_opt or _env_setting("WIKI_LIGHTWEIGHT_MODEL")
model_value = model_opt or _env_setting("WIKI_MODEL")
if not lightweight_model_value and not model_value and not _env_setting("PARROT_NO_AUTO_LLM"):
    from parrot.clients.detection import detect_coding_agent_llm

    detected = detect_coding_agent_llm()
    if detected:
        click.echo(
            f"[auto-selected {detected} for WIKI_MODEL/WIKI_LIGHTWEIGHT_MODEL — a "
            "coding-agent CLI session was detected. Set WIKI_MODEL / WIKI_LIGHTWEIGHT_MODEL "
            "to override, or PARROT_NO_AUTO_LLM=1 to disable auto-detection.]"
        )
        lightweight_model_value = detected
        model_value = detected
lightweight_model = _resolve_model_id(lightweight_model_value, "WIKI_LIGHTWEIGHT_MODEL")
model = _resolve_model_id(model_value, "WIKI_MODEL")
light_adapter, heavy_adapter, light_model_id, same_provider = _build_triage_adapters(lightweight_model, model)
```

### Key Constraints
- Do not change `_resolve_model_id()` or `_build_triage_adapters()` signatures.
- The "both unset together" check in Part B is load-bearing — do not auto-detect when only
  one of the two is missing (this would either mix providers or silently override a value the
  user only partially configured).
- Keep every new import lazy, matching the file's existing conventions.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/detection.py` (TASK-2892) — the function this task
  calls, in two places.
- `packages/ai-parrot/tests/knowledge/wiki/test_cli.py` — existing test file/fixtures to
  extend rather than duplicate (check for an existing Click `CliRunner` fixture before adding
  a new one).

---

## Acceptance Criteria

- [ ] `_extract_into_graph` uses the detected spec (with a visible `click.echo` message)
      instead of skipping, when `WIKI_EXTRACT_LLM` is unset, `PARROT_NO_AUTO_LLM` is unset,
      and detection succeeds.
- [ ] `_extract_into_graph` keeps today's exact "[extract skipped...]" message when detection
      also misses.
- [ ] The `ingest` command auto-detects and uses the **same** spec for both
      `WIKI_LIGHTWEIGHT_MODEL` and `WIKI_MODEL` only when **both** are unset (no CLI flag, no
      env var) and `PARROT_NO_AUTO_LLM` is unset.
- [ ] If only one of `WIKI_MODEL` / `WIKI_LIGHTWEIGHT_MODEL` is set and the other is not, the
      existing `ClickException` for the missing one is raised unchanged — detection is never
      invoked in this case.
- [ ] Setting `PARROT_NO_AUTO_LLM` (any truthy value, read via `_env_setting`) disables
      detection in both Part A and Part B — behavior identical to today.
- [ ] `detect_coding_agent_llm` is never called when the relevant env var(s)/flag(s) are
      already set (regression guard).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- [ ] Completion Note records whether a fourth `WIKI_*` LLM-resolution call site was found
      during the verification grep (spec §8 open item).

---

## Test Specification

```python
# append to packages/ai-parrot/tests/knowledge/wiki/test_cli.py
from unittest.mock import patch

import pytest

from parrot.knowledge.wiki import cli as wiki_cli


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("WIKI_EXTRACT_LLM", "WIKI_MODEL", "WIKI_LIGHTWEIGHT_MODEL", "PARROT_NO_AUTO_LLM"):
        monkeypatch.delenv(var, raising=False)


def test_extract_uses_detection_when_unset(monkeypatch, tmp_path, capsys):
    with patch(
        "parrot.clients.detection.detect_coding_agent_llm",
        return_value="claude-code:claude-haiku-4-5-20251001",
    ):
        # invoke _extract_into_graph with a stub config/store per existing fixtures in this
        # file; assert click.echo was called with an "[auto-selected ...]" message and that
        # extraction proceeded (mock LLMGraphExtractor per existing test patterns here).
        ...


def test_extract_respects_opt_out(monkeypatch, capsys):
    monkeypatch.setenv("PARROT_NO_AUTO_LLM", "1")
    with patch("parrot.clients.detection.detect_coding_agent_llm") as mock_detect:
        # call _extract_into_graph with no WIKI_EXTRACT_LLM set
        ...
    mock_detect.assert_not_called()


def test_ingest_model_resolution_both_unset_uses_detection(monkeypatch):
    with patch(
        "parrot.clients.detection.detect_coding_agent_llm",
        return_value="claude-code:claude-haiku-4-5-20251001",
    ):
        # invoke the ingest command via CliRunner with neither --model nor
        # --lightweight-model and neither env var set; assert both resolved to the same
        # detected spec.
        ...


def test_ingest_model_resolution_only_one_set_does_not_autodetect(monkeypatch):
    monkeypatch.setenv("WIKI_MODEL", "anthropic:claude-sonnet-5")
    with patch("parrot.clients.detection.detect_coding_agent_llm") as mock_detect:
        # invoke the ingest command with WIKI_LIGHTWEIGHT_MODEL unset; expect the existing
        # ClickException for the missing WIKI_LIGHTWEIGHT_MODEL, and detection never called.
        ...
    mock_detect.assert_not_called()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/wikitoolkit-cli-llm-fallback.spec.md` for full context.
2. **Check dependencies** — verify TASK-2892 is in `sdd/tasks/completed/` before starting.
3. **Verify the Codebase Contract** — `read` the relevant sections of
   `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (lines ~2694-2743 and ~3409-3720) to
   confirm line numbers/behavior are still accurate before editing, and run the "fourth call
   site" verification grep from the Codebase Contract above.
4. **Update status** in the per-spec index → `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Check the existing `packages/ai-parrot/tests/knowledge/wiki/test_cli.py`** for its
   existing fixtures/`CliRunner` setup before writing new tests — follow its conventions
   rather than introducing a parallel test-setup style.
7. **Verify** all acceptance criteria are met.
8. **Move this file** to `sdd/tasks/completed/TASK-2894-wikitoolkit-fallback.md`.
9. **Update the index** → `"done"`.
10. **Fill in the Completion Note** below, including the fourth-call-site verification result.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered. State
explicitly whether a fourth `WIKI_*` LLM-resolution call site was found.

**Deviations from spec**: none | describe if any
