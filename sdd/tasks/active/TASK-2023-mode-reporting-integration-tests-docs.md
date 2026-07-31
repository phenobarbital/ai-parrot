# TASK-2023: Honest `mode` reporting, integration tests, and docs

**Feature**: FEAT-396 — Svelte / hardened-TypeScript support in the wiki repo scanner
**Spec**: `sdd/specs/wikitoolkit-svelte-typescript-support.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2019, TASK-2020, TASK-2021, TASK-2022
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of the spec (§3) — the closing task.

`JavaScriptScanner.mode` (`javascript.py:343-352`) returns `"tree-sitter"` if **either**
grammar loads. Since the JS grammar has always loaded and the TS grammar never did (the
defect TASK-2019 fixes), stats have been reporting `tree-sitter` for TypeScript files
that were actually parsed by regex. This task makes `mode` honest, adds the
cross-cutting integration tests, and documents `.svelte`.

**Expect the reported mode of existing repos to change after this lands. That is the
correction, not a regression** (spec §7).

---

## Scope

- Tighten `JavaScriptScanner.mode`: report `"tree-sitter"` only when **both** grammars
  this scanner can select (`javascript` **and** `typescript`) actually load; otherwise
  `"heuristic"`.
- Add the three integration tests from spec §4 (`test_scan_svelte_fixture_repo`,
  `test_svelte_heuristic_parity`, `test_polyglot_svelte_alongside_python`).
- Add `test_mode_requires_both_grammars`.
- Document `.svelte` in `documentation/parrot-wiki-cli.md` — the JS/TS row of the
  language table (line 173) and the `module` category line (line 132).
- Confirm the `wiki-languages` extra needs no change (it does not — no new dependency)
  and that its docs mention Svelte support comes from the TS/JS grammars.

**NOT in scope**:
- Any behaviour change to `_extract_script_blocks`, alias resolution, or the grammar
  loader — those are TASK-2019/2021/2022 and must not be revisited here.
- Adding `tree-sitter-svelte` to the extra — there is no such dependency in this feature.
- Scanning `navigator-svelte` in CI. The `> 0 references edges` acceptance criterion from
  spec §5 is verified **manually, once**, and the result recorded in the Completion Note.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py` | MODIFY | Tighten `mode` to require both grammars |
| `tests/knowledge/wiki/languages/test_javascript_plugin.py` | MODIFY | Add `test_mode_requires_both_grammars` |
| `tests/knowledge/wiki/languages/test_repo_scan_integration.py` | MODIFY | Add `test_scan_svelte_fixture_repo`, `test_svelte_heuristic_parity` |
| `tests/knowledge/wiki/languages/test_polyglot_integration.py` | MODIFY | Add `test_polyglot_svelte_alongside_python` |
| `documentation/parrot-wiki-cli.md` | MODIFY | List `.svelte` among supported suffixes |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against the working tree on 2026-07-31 (branch `dev`, commit
> `349a184c3`). TASKS 2019-2022 will have changed `javascript.py` substantially before
> this runs — **re-read it first**.

### Verified Imports

```python
# verified: languages/javascript.py:24
from parrot.knowledge.wiki.languages import treesitter
# verified: languages/__init__.py __all__
from parrot.knowledge.wiki.languages import scanned_suffixes, scanner_for, set_scan_root
```

### Existing Signatures to Use

```python
# languages/javascript.py — the CURRENT property to tighten, lines 343-352:
    @property
    def mode(self) -> str:
        """``"tree-sitter"`` when either JS/TS grammar loads, else
        ``"heuristic"``."""
        if (
            treesitter.get_parser("typescript") is not None
            or treesitter.get_parser("javascript") is not None   # <-- `or` becomes `and`
        ):
            return "tree-sitter"
        return "heuristic"

# languages/base.py
    @property
    @abstractmethod
    def mode(self) -> str:      # line 112
        """Active extraction mode: ``"ast" | "tree-sitter" | "heuristic"``."""

# languages/treesitter.py
_PARSER_CACHE: dict[str, Parser | None] = {}   # line 25 — CACHES None
def get_parser(language: str) -> Parser | None: ...  # line 38
```

### Existing test fixtures to reuse

```python
# tests/knowledge/wiki/languages/conftest.py
def _write(root: Path, rel: str, content: str) -> None: ...   # line 26
@pytest.fixture
def force_heuristic(monkeypatch): ...    # lines 11-23 — patches treesitter.get_parser -> None
@pytest.fixture
def polyglot_repo(tmp_path: Path) -> Path: ...   # lines 32-81
# `svelte_repo` is added by TASK-2022 — reuse it, do NOT redefine it
```

### Docs anchors (verified line numbers in `documentation/parrot-wiki-cli.md`)

```
line 132: | `module` | Source code (`.py`, `.php`, `.rs`, `.go`, `.ts`, `.sql`, …) |
line 173: | JS / TS | `.js`, `.jsx`, `.mjs`, `.ts`, `.tsx` | exported classes/functions/… |
line 185: **Installing accurate parsing** — the `wiki-languages` extra:
```

### Does NOT Exist

- ~~`tree-sitter-svelte`~~ — not a dependency of this feature, not in the extra
  (`pyproject.toml:202-208`), not in `_GRAMMAR_MODULES`. **Do not add it to the docs as
  a requirement.**
- ~~`LanguageScanner.mode` accepting a fourth value~~ — the contract is exactly
  `"ast" | "tree-sitter" | "heuristic"` (`base.py:112`). Do not invent `"partial"` or
  `"mixed"`.
- ~~`scanner.mode` being cached~~ — it is a plain property evaluated per access, and
  `get_parser` does the caching underneath.
- ~~A `pyproject.toml` change~~ — **no new dependency is introduced by this feature**
  (spec §7). `tree-sitter-typescript>=0.23` and `tree-sitter-javascript>=0.23` are
  already there; they just needed to load.

---

## Implementation Notes

### Key Constraints

- The `mode` change is a **one-word edit** (`or` → `and`) plus an updated docstring.
  Keep it that small.
- **`_PARSER_CACHE` caches `None`** (`treesitter.py:25`, `:52-57`). Any test that
  monkeypatches grammar availability **must** clear the cache, or ordering makes results
  non-deterministic. This is the single most likely source of a flaky test in this task.
- `test_svelte_heuristic_parity` is the important one: with grammars forced unavailable,
  **imports and edges must be identical** to the tree-sitter run; only the outline
  degrades, and it must still be non-empty.
- Every new code path must degrade with the optional extra absent — the whole suite must
  pass with tree-sitter uninstalled.
- Reuse `svelte_repo` from TASK-2022's conftest; do not duplicate the fixture.

### Manual verification for the `navigator-svelte` criterion

Spec §5 requires `> 0 references` edges out of `.svelte` files where the current build
produces 0. Run it once by hand against the real repo, and paste the before/after counts
into the Completion Note. Do **not** wire this into the test suite — it depends on a repo
outside this project.

### Testing this task

CI on `dev` is red since 2026-07-27 for an **unrelated** `pillow-heif` dependency
conflict (`ai-parrot[all]` wants `>=1.3.0`, `flowtask>=5.12.3` pins `==0.22.0`; `uv sync`
dies before any test runs). Do not fix it, do not wait for green.

```bash
cd packages/ai-parrot/src
SITE_ROOT=~/.local/share/parrot-site ENV=dev PYTHONPATH=. \
  ~/.venvs/parrot-lite/bin/python -m pytest ../../../tests/knowledge/wiki/languages/ -q
```

`SITE_ROOT` is mandatory or navconfig raises `FileExistsError`. Also run the wider wiki
suite once, per spec §5: `pytest ../../../tests/knowledge/wiki/ -v`.

### References in Codebase

- `languages/javascript.py:343-352` — the property to tighten
- `tests/knowledge/wiki/languages/test_polyglot_integration.py` — cross-language
  no-crosstalk assertions to extend
- `tests/knowledge/wiki/languages/test_repo_scan_integration.py` — end-to-end scan style

---

## Acceptance Criteria

- [ ] `mode` returns `"heuristic"` when only the JS grammar loads
- [ ] `mode` returns `"tree-sitter"` only when **both** grammars load
- [ ] Scanning the `svelte_repo` fixture produces a `references` edge from
      `src/lib/Widget.svelte` → `src/lib/util.ts`
- [ ] With grammars monkeypatched unavailable, imports and edges are **identical**;
      the outline degrades but stays non-empty
- [ ] `.svelte` and `.py` in one scan → both outlines present, no scanner cross-talk
- [ ] `documentation/parrot-wiki-cli.md` lists `.svelte` among supported suffixes
- [ ] The full existing suite passes: `pytest ../../../tests/knowledge/wiki/ -v`
- [ ] The whole suite passes with tree-sitter uninstalled
- [ ] `navigator-svelte` produces > 0 `references` edges out of `.svelte` files —
      verified manually, counts recorded in the Completion Note
- [ ] No lint errors on `javascript.py`

---

## Test Specification

```python
# tests/knowledge/wiki/languages/test_javascript_plugin.py — ADD

from parrot.knowledge.wiki.languages import treesitter
from parrot.knowledge.wiki.languages.javascript import JavaScriptScanner


def test_mode_requires_both_grammars(monkeypatch):
    """`mode` is honest: one grammar loading is not tree-sitter mode."""
    monkeypatch.setattr(
        treesitter,
        "get_parser",
        lambda language: object() if language == "javascript" else None,
    )
    assert JavaScriptScanner().mode == "heuristic"

    monkeypatch.setattr(treesitter, "get_parser", lambda language: object())
    assert JavaScriptScanner().mode == "tree-sitter"


# tests/knowledge/wiki/languages/test_repo_scan_integration.py — ADD

def test_scan_svelte_fixture_repo(svelte_repo):
    """A `$lib` import in a component becomes a real references edge."""
    # scan svelte_repo end-to-end; assert an edge
    #   src/lib/Widget.svelte -> src/lib/util.ts
    ...


def test_svelte_heuristic_parity(svelte_repo, force_heuristic):
    """Without grammars: same imports and edges, degraded but non-empty outline."""
    # scan twice (grammars on/off) and compare imports + edges for equality
    ...


# tests/knowledge/wiki/languages/test_polyglot_integration.py — ADD

def test_polyglot_svelte_alongside_python(tmp_path):
    """`.svelte` and `.py` in one scan — both outlined, no cross-talk."""
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §3 Module 5, §4 integration tests, §5 acceptance criteria
2. **Check dependencies** — TASK-2019, 2020, 2021 and 2022 must all be in
   `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — `javascript.py` has changed a lot by now; re-read
   `mode` and the conftest fixtures before writing code
4. **Update status** in `sdd/tasks/index/wikitoolkit-svelte-typescript-support.json`
5. **Implement** per scope
6. **Verify** every acceptance criterion, including the manual `navigator-svelte` run
7. **Move this file** to `sdd/tasks/completed/TASK-2023-mode-reporting-integration-tests-docs.md`
8. **Update index** → `"done"`, and set the feature's `completed_at`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**navigator-svelte verification**: `.svelte` references edges before: ___ / after: ___

**Deviations from spec**: none | describe if any
