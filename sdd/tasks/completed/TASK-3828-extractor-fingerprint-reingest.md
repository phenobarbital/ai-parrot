# TASK-3828: Extractor fingerprint: re-ingest a language when its extraction tier changes

**Feature**: FEAT-609 — Honest structural tier, Svelte component symbols, module-local JS functions, and federated symbol queries in wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-structural-coverage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3821, TASK-3822, TASK-3824
**Assigned-to**: unassigned

---

## Context

Spec §1 defect 1 ("installing the extra has no effect on an existing plane") / §3 Module 2 /
G2. Staleness is decided per file from mtime/content (`cli.py:765`,
`sources.entry_is_stale`). After `ast-grep-py` was installed on `navigator-svelte`, the scan
found 13,590 symbols, but a plain `build` reported `0 ingested, 6032 unchanged` and stored none.
Only `--force` recovered them.

This task records *what extracted the plane*, per language, and re-ingests exactly the
languages whose extractor changed. It does this through the existing `force_rel_paths`
mechanism of `_ingest_files` (`cli.py:693-699`, the FEAT-532 precedent), with no second
invalidation path.

---

## Scope

- Create `languages/fingerprint.py` with:
  - `ExtractorFingerprint(BaseModel)`: `schema_version: int = 1` and
    `languages: dict[str, str]`, where each value is `"<mode>:<sha1 of rule file>|none"`;
  - `current_fingerprint()`;
  - `changed_languages(old, new)`;
  - `async load_fingerprint(store)`;
  - `async save_fingerprint(store, fp)`.

  The rule file per scanner is `languages/rules/<file>.yaml`, mapped as follows:
  - `javascript` → `typescript.yaml`;
  - `php`, `rust`, `perl`, `python` → the same-named file;
  - `luau` → `none`.

  `mode` is the predictive mode from TASK-3821.
- `changed_languages(None, new)` returns every **structural-capable** scanner name, i.e. every
  scanner except `python` and `luau`. This is the one-time heal for planes built before this
  feature. Otherwise it returns the names whose entry differs, including a `python` entry whose
  `python.yaml` hash changed.
- `load_fingerprint` returns `None` when the value is absent, unparseable, or the backend raises
  `NotImplementedError`. It never raises. `save_fingerprint` swallows `NotImplementedError`
  (logging at `DEBUG`).
- `build`'s `_pipeline`:
  - after `_apply_roblox_enrichment` returns, compute `fp_now`, load `fp_old`, and **union**
    into `force_rel_paths` the rel_paths of every scanned file whose `FileSlice.language` is in
    `changed_languages(fp_old, fp_now)`;
  - after the ingest succeeds (next to `_record_roblox_enrichment_success`),
    `await save_fingerprint(store, fp_now)`.
- Write tests, including the end-to-end heal.

**NOT in scope**: the second `_ingest_files` call site (`cli.py:1816`), which already passes
`force=True`; meta backends (TASK-3822/3825); the warning (TASK-3824).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/fingerprint.py` | CREATE | model + compute/diff/load/save |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | union into `force_rel_paths`, save after success |
| `tests/knowledge/wiki/test_extractor_fingerprint.py` | CREATE | unit + build-heal integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.languages import all_scanners            # languages/__init__.py (cli.py:67 imports it)
from parrot.knowledge.wiki.store import BaseWikiStore               # store.py:525 (get_meta/set_meta from TASK-3822)
from pydantic import BaseModel, Field
```

### Existing Signatures to Use
```python
# languages/__init__.py:33-40
_SCANNERS = {"python": ..., "php": ..., "javascript": ..., "rust": ..., "perl": ..., "luau": ...}
# languages/astgrep.py:53
_RULES_DIR = Path(__file__).parent / "rules"      # files: perl.yaml php.yaml python.yaml rust.yaml typescript.yaml
# cli.py:693-699
async def _ingest_files(store, sources, root, scan, force: bool = False, force_rel_paths: set[str] | None = None) -> dict[str, Any]:
# cli.py:1548-1552  (inside build's `async def _pipeline()`; line numbers move after TASK-3824 — anchor by text)
            enriched_scan, force_rel_paths, enrichment_by_path = await _apply_roblox_enrichment(
                root, scan, output_dir, sources          # <- occurrences: 1 (`root, scan, output_dir, sources`)
            )
            counts = await _ingest_files(
                store, sources, root, enriched_scan, force=force, force_rel_paths=force_rel_paths
            )
# cli.py:1561
            _record_roblox_enrichment_success(output_dir, enrichment_by_path, counts["written_rel_paths"])   # occurrences: 1
# repo_scan.py:184  FileSlice.language: str | None
```

### Does NOT Exist
- ~~`BaseWikiStore.get_meta` before TASK-3822~~: this task depends on it.
- ~~A public `astgrep.RULES_DIR`~~: `_RULES_DIR` is private. Build the path in `fingerprint.py`
  as `Path(__file__).parent / "rules"` (the same directory: `fingerprint.py` lives in
  `languages/`).
- ~~`force_rel_paths` being a frozenset~~: `_apply_roblox_enrichment` returns a `set`. Verify,
  and copy it before mutating if it could be shared.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/languages/fingerprint.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_extractor_fingerprint.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_ingest_files",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#build",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Save only after success.** A failed build must leave the old fingerprint, so the next run
  retries. The same reasoning is already written next to the Roblox fingerprint at
  `cli.py:1557-1560`.
- **No churn.** Two consecutive plain builds with nothing changed must ingest 0 files the second
  time (spec integration test `test_build_fingerprint_no_churn`).
- The fingerprint lives in store meta under the key `extractor_fingerprint`, as the JSON of the
  model (spec §2 Data Models).

---

## Implementation Blueprint

### Steps (in order)
1. Create `fingerprint.py`. 2. Wire it into `build`. 3. Write the unit tests, then the
heal and no-churn integration tests. 4. Mutation-check the heal.

### `packages/ai-parrot/src/parrot/knowledge/wiki/languages/fingerprint.py` (CREATE)
```python
"""Extractor fingerprint: which tier + rule file produced a plane's symbols (FEAT-609 M2).

A plane stores this under the meta key ``extractor_fingerprint``. When a language's
entry changes — ast-grep installed or removed, a rule file edited — ``build`` re-ingests
that language's files once, instead of trusting per-file staleness, which cannot see a
change in the extractor.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from parrot.knowledge.wiki.languages import all_scanners
from parrot.knowledge.wiki.store import BaseWikiStore

logger = logging.getLogger(__name__)

META_KEY = "extractor_fingerprint"
_RULES_DIR = Path(__file__).parent / "rules"
_RULE_FILES: dict[str, str | None] = {
    "javascript": "typescript.yaml",
    "php": "php.yaml",
    "rust": "rust.yaml",
    "perl": "perl.yaml",
    "python": "python.yaml",
    "luau": None,
}
_NON_STRUCTURAL = frozenset({"python", "luau"})


class ExtractorFingerprint(BaseModel):
    """Per-language identity of what produced a plane's symbols."""

    schema_version: int = 1
    languages: dict[str, str] = Field(default_factory=dict)


def _rule_hash(scanner_name: str) -> str:
    rule_file = _RULE_FILES.get(scanner_name)
    if rule_file is None:
        return "none"
    path = _RULES_DIR / rule_file
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return "none"


def current_fingerprint() -> ExtractorFingerprint:
    """Fingerprint of the scanners as installed in this process."""
    return ExtractorFingerprint(
        languages={name: f"{scanner.mode}:{_rule_hash(name)}" for name, scanner in all_scanners().items()}
    )


def changed_languages(old: ExtractorFingerprint | None, new: ExtractorFingerprint) -> set[str]:
    """Scanner names whose entry differs; every structural-capable one when ``old`` is None."""
    if old is None:
        return {name for name in new.languages if name not in _NON_STRUCTURAL}
    return {name for name, entry in new.languages.items() if old.languages.get(name) != entry}


async def load_fingerprint(store: BaseWikiStore) -> ExtractorFingerprint | None:
    """Stored fingerprint, or ``None`` when absent/unparseable/unsupported. Never raises."""
    try:
        raw = await store.get_meta(META_KEY)
    except NotImplementedError:
        return None
    except Exception as exc:  # noqa: BLE001 - an unreadable fingerprint means "unknown"
        logger.debug("load_fingerprint failed: %s", exc)
        return None
    if not raw:
        return None
    try:
        return ExtractorFingerprint.model_validate_json(raw)
    except ValidationError:
        return None


async def save_fingerprint(store: BaseWikiStore, fp: ExtractorFingerprint) -> None:
    """Persist ``fp``; a backend without meta support is skipped, not an error."""
    try:
        await store.set_meta(META_KEY, fp.model_dump_json())
    except NotImplementedError:
        logger.debug("%s has no meta support; extractor fingerprint not saved", type(store).__name__)
```
**Why**: this module sits in `languages/` and imports `store`. Check for an import cycle
(`python -c "import parrot.knowledge.wiki.languages.fingerprint"`). If `store` imports
`languages` at module level, type the parameter as `Any` under `TYPE_CHECKING`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY) — force set
```python
# occurrences: 1 (verified: grep -c '                root, scan, output_dir, sources' cli.py)
# AFTER — insert below the closing `            )` of the `_apply_roblox_enrichment(` call whose
#         argument line is `                root, scan, output_dir, sources` (verified at spec time: cli.py:1548-1550)
            # FEAT-609 M2: re-ingest every file of a language whose extractor changed
            # (ast-grep installed/removed, rule file edited) — per-file staleness cannot see it.
            fp_now = current_fingerprint()
            changed = changed_languages(await load_fingerprint(store), fp_now)
            if changed:
                force_rel_paths = set(force_rel_paths) | {
                    f.rel_path for f in enriched_scan.files if f.language in changed
                }
```

### `cli.py` (MODIFY) — save after success
```python
# occurrences: 1 (verified: grep -c '_record_roblox_enrichment_success(output_dir, enrichment_by_path, counts\["written_rel_paths"\])' cli.py)
# AFTER — insert below that line (verified at spec time: cli.py:1561)
            await save_fingerprint(store, fp_now)
```
Add `from parrot.knowledge.wiki.languages.fingerprint import changed_languages, current_fingerprint, load_fingerprint, save_fingerprint`
next to the `all_scanners` import (`cli.py:67`).

### `tests/knowledge/wiki/test_extractor_fingerprint.py` (CREATE)
```python
"""FEAT-609 M2: a changed extractor re-ingests its language on the next plain build."""

from __future__ import annotations

from parrot.knowledge.wiki.languages import astgrep
from parrot.knowledge.wiki.languages.fingerprint import (
    ExtractorFingerprint,
    changed_languages,
    current_fingerprint,
)


def test_fingerprint_changed_languages_tier_flip(monkeypatch) -> None:
    before = current_fingerprint()
    monkeypatch.setattr(astgrep, "is_available", lambda: False)
    after = current_fingerprint()
    # FILL IN: when ast-grep was available in `before`, "javascript" is in the diff and
    # "luau" is not — skip (pytest.skip) when ast-grep is not installed at all
    assert "luau" not in changed_languages(before, after)


def test_fingerprint_none_marks_all_structural() -> None:
    assert changed_languages(None, current_fingerprint()) == {"javascript", "php", "rust", "perl"}


def test_fingerprint_rule_hash_change() -> None:
    fp = current_fingerprint()
    edited = ExtractorFingerprint(languages={**fp.languages, "php": fp.languages["php"] + "x"})
    assert changed_languages(fp, edited) == {"php"}


def test_build_heals_after_extra_installed(tmp_path, monkeypatch) -> None:
    # FILL IN: tmp repo with one .ts file; `wikitoolkit build` (CliRunner, as
    # tests/knowledge/wiki/test_cli.py does) with astgrep.is_available patched False
    # -> 0 symbols; un-patch; plain `build` (NO --force) -> sym: pages exist.
    # Mutation proof: comment out the force-set union and this test must go RED.
    ...


def test_build_fingerprint_no_churn(tmp_path) -> None:
    # FILL IN: two consecutive plain builds with nothing changed -> the second reports
    # "0 ingested" — bounded by spec integration test of the same name
    ...
```

### FILL IN checklist
- [ ] The tier-flip assertion. Bound: skip cleanly without ast-grep.
- [ ] `test_build_heals_after_extra_installed`. Bound: plain build, no `--force`, a real
  sqlite plane.
- [ ] `test_build_fingerprint_no_churn`. Bound: `0 ingested` on the second build.
- [ ] The import-cycle check for `fingerprint.py`.

---

## Acceptance Criteria

- [ ] A plane built without ast-grep gains `sym:` pages on the next **plain** build once
      ast-grep is installed (spec AC).
- [ ] No churn: a second build with nothing changed ingests 0 files.
- [ ] The fingerprint is saved only after a successful ingest, through `set_meta`. No JSON file
      is written.
- [ ] Mutation-checked: without the union, `test_build_heals_after_extra_installed` goes RED.

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_extractor_fingerprint.py -q`
- `pytest tests/knowledge/wiki/test_cli.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree**
   (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-structural-coverage --feature-id FEAT-609`).
2. Confirm TASK-3821, TASK-3822 and TASK-3824 are `done`. Re-locate the `cli.py` anchors by
   text, because TASK-3824 shifted the line numbers.
3. Implement, validate, mutation-check, and stage only the listed files.
4. Close with `scripts/sdd/close_task.sh TASK-3828 wikitoolkit-structural-coverage verified`,
   then fill in the Completion Note.

---

## Completion Note

Implemented as specified; no import cycle. Mutations RED: disabling the force-set union -> test_build_heals_after_extra_installed + no_churn + saved_via_meta; skipping save_fingerprint -> the same. Full tests/knowledge/wiki: 1981 passed (test_sources json-stale failure pre-existing, deselected). Note: tests/ plane test_cli_status_sqlite stays green.
