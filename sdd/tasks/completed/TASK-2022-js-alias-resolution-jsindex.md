# TASK-2022: Alias-aware import resolution (`JsIndex`, `$lib`, tsconfig `paths`)

**Feature**: FEAT-396 — Svelte / hardened-TypeScript support in the wiki repo scanner
**Spec**: `sdd/specs/wikitoolkit-svelte-typescript-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2020
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of the spec (§3).

Even a perfect `.svelte` outline loses roughly two thirds of the cross-file edges,
because **65% of internal imports are alias-based**. Measured on the motivating repo
(spec §1): 2976 `$lib` imports and 271 `$app` imports against 1625 relative ones.
`_extract_imports` currently drops every non-relative specifier at extraction time
(`javascript.py:119`), so those 2976 imports never even reach `resolve_import`.

This task makes the index alias-aware: `build_reference_index` returns a richer `JsIndex`
(the existing file set **plus** an alias map read once from the scan root), and
`resolve_import` tries the alias map before giving up on a non-relative specifier.

The **SvelteKit convention fallback is the common case, not a convenience**: in the
motivating repo the only declaration of `$lib` lives in `.svelte-kit/tsconfig.json`,
which is generated and **gitignored**. A scanner reading only committed files would
resolve zero aliases on a fresh clone.

---

## Scope

- Add a frozen dataclass `JsIndex` with `files: frozenset[str]` and
  `aliases: tuple[tuple[str, str], ...]` (**longest prefix first**, so the match is a
  plain ordered scan and the object stays hashable/immutable like the frozenset it
  replaces).
- Change `build_reference_index` to return a `JsIndex`, discovering aliases **once per
  scan** against `get_scan_root()`, in this order:
  1. `svelte.config.js` → `kit.alias` block when present (**regex-scraped, never
     JS-evaluated**).
  2. `tsconfig.json` / `jsconfig.json` → `compilerOptions.paths`, resolved relative to
     `baseUrl`.
  3. **SvelteKit convention fallback**: if a `svelte.config.js` exists at the root, map
     `$lib/` → `src/lib/` even when nothing declares it.
- Add an alias branch to `resolve_import`, tried before the existing relative branch
  gives up; after expanding the prefix, reuse the **existing** extension-guessing and
  `/index.*` logic.
- Relax `_extract_imports` so non-relative specifiers survive extraction and are filtered
  at **resolution** time instead.
- Add the five Module-4 unit tests from spec §4.

**NOT in scope**:
- `mode` tightening, integration tests, docs, pyproject — TASK-2023.
- Resolving `$app/*`, `$env/*` and other SvelteKit **virtual** modules — they have no
  file in the repository, so the edge is correctly **dropped** (271 imports, by design,
  spec §1 Non-Goals).
- Recording unresolved specifiers as a distinct "external" edge kind — open question in
  spec §8, owned by Jesús Lara, explicitly **not** decided here.
- Changing the `LanguageScanner` ABC. `build_reference_index` is declared to return
  `Any` (`base.py:75-89`), so a richer object needs **no** ABC change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py` | MODIFY | `JsIndex`, alias discovery, `resolve_import` alias branch, `_extract_imports` relaxation |
| `tests/knowledge/wiki/languages/test_javascript_plugin.py` | MODIFY | Add the five Module-4 unit tests |
| `tests/knowledge/wiki/languages/conftest.py` | MODIFY | Add the `svelte_repo` fixture from spec §4 |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against the working tree on 2026-07-31 (branch `dev`, commit
> `349a184c3`).

### Verified Imports

```python
# verified: languages/javascript.py:16-25 (already present)
from __future__ import annotations
import logging
import re
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any, ClassVar

# NEW imports this task needs — all stdlib, no new dependency
import json
from dataclasses import dataclass
from pathlib import Path

# verified: languages/__init__.py:99-106 — MUST be imported LOCALLY inside the method,
# see the circular-import note under "Pattern to Follow"
from parrot.knowledge.wiki.languages import get_scan_root
```

### Existing Signatures to Use

```python
# languages/base.py — the ABC, UNCHANGED by this task
def build_reference_index(self, rel_paths: Iterable[str]) -> Any: ...   # line 75
def resolve_import(self, spec: str, from_file: str, index: Any) -> str | None: ...  # line 92

# languages/javascript.py — CURRENT bodies being changed
def _extract_imports(source: str) -> list[str]:            # line 111
    """Raw import specifiers, relative-only (bare package names dropped)."""
    specs: list[str] = []
    for pattern in (_RE_IMPORT_FROM, _RE_IMPORT_SIDE_EFFECT, _RE_REQUIRE):
        specs.extend(m.group(1) for m in pattern.finditer(source))
    seen: set[str] = set()
    ordered: list[str] = []
    for spec in specs:
        if spec.startswith(".") and spec not in seen:      # <-- line 119, the filter to relax
            seen.add(spec)
            ordered.append(spec)
    return ordered

def _normalize_posix(path: PurePosixPath) -> str: ...      # line 125 — REUSE, collapses ./..

    def build_reference_index(self, rel_paths: Iterable[str]) -> Any:      # line 298
        return frozenset(PurePosixPath(p).as_posix() for p in rel_paths)   # line 307

    def resolve_import(self, spec: str, from_file: str, index: Any) -> str | None:  # line 309
        if not spec.startswith("."):
            return None                                    # <-- the early-out to extend
        file_set: frozenset[str] = index
        base = PurePosixPath(from_file).parent / spec
        base_str = _normalize_posix(base)
        if base_str in file_set:
            return base_str
        for ext in _EXTENSION_CANDIDATES:
            candidate = base_str + ext
            if candidate in file_set:
                return candidate
        for idx in _INDEX_CANDIDATES:
            candidate = f"{base_str}/{idx}"
            if candidate in file_set:
                return candidate
        return None

_EXTENSION_CANDIDATES: tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx", ".mjs")  # line 77
_INDEX_CANDIDATES: tuple[str, ...] = (                                           # lines 78-80
    "index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs",
)

# languages/__init__.py
def get_scan_root() -> Path | None: ...    # line 99 — returns None outside a scan
def set_scan_root(root) -> None: ...       # called once per scan at repo_scan.py:795
```

### The PHP precedent to mirror (`php.py:349-377`, verified)

```python
        # Local import: `parrot.knowledge.wiki.languages` (the package
        # __init__) imports this module during its own initialization, so
        # a module-level import of a sibling name from it here would be
        # circular. By call time, package init has long finished.
        from parrot.knowledge.wiki.languages import get_scan_root

        scan_root = get_scan_root()
        for candidate in sorted(file_set):
            if PurePosixPath(candidate).name != "composer.json":
                continue
            path = (scan_root / candidate) if scan_root is not None else Path(candidate)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                logger.debug("Could not read/parse %s: %s", candidate, exc)
                continue
```

### Does NOT Exist

- ~~`LanguageScanner.aliases`~~ — no such ABC member. The ABC is **frozen**
  (`base.py:40-114`). The alias map lives **inside** `JsIndex`.
- ~~`tsconfig` / `pyjson5` / `json5` / `commentjson`~~ — **no new dependency is
  introduced by this feature** (spec §7). `tsconfig.json` is read with stdlib `json`;
  if it fails to parse (comments/trailing commas are legal in real tsconfig but not in
  stdlib `json`), **degrade** to the next discovery step rather than raising.
- ~~`svelte.config.js` being importable/evaluatable~~ — it is JavaScript. **Regex-scrape
  the `kit.alias` block; never evaluate it.**
- ~~`.svelte-kit/tsconfig.json` as a required input~~ — it exists only after a build and
  is **gitignored**. Never treat it as required; that is exactly why step 3 exists.
- ~~`JsIndex` already existing~~ — this task creates it. There is no `JsIndex`,
  `JsAliasMap` or `ReferenceIndex` in the tree today.
- ~~`index` being a `dict`~~ — after this task it is a `JsIndex`. `resolve_import` must
  not assume `frozenset` any more, but must stay tolerant per the ABC's "opaque index"
  contract.

---

## Implementation Notes

### Pattern to Follow

```python
@dataclass(frozen=True)
class JsIndex:
    """Scanned file set plus the repo's import-alias prefix map.

    Attributes:
        files: Every scanned repo file, POSIX rel paths.
        aliases: ``(prefix, target)`` pairs such as ``("$lib/", "src/lib/")``,
            ordered **longest prefix first** so a plain ordered scan yields the
            most specific match.
    """

    files: frozenset[str]
    aliases: tuple[tuple[str, str], ...] = ()
```

Alias discovery mirrors `php.py:349-377` exactly: local import of `get_scan_root`,
`scan_root / candidate` when the root is known, `try/except (OSError, ValueError)` with
a `logger.debug` and `continue` on failure.

In `resolve_import`, keep the relative branch first and unchanged, then:

```python
        for prefix, target in index.aliases:        # already longest-first
            if spec.startswith(prefix):
                base_str = _normalize_posix(
                    PurePosixPath(target + spec[len(prefix):])
                )
                # then reuse the SAME extension / index candidate loops
                break
```

### Key Constraints

- **Alias config is read once per scan**, inside `build_reference_index`, never per file.
  That method is called once per scanner per scan (`base.py:75-89`).
- **`build_reference_index` receives every scanned path**, not just this scanner's
  (`base.py:78-81`) — so `svelte.config.js` and `tsconfig.json` **are** visible in the
  index even though `.js`/`.json` are scanned by other categories. Find them there.
- **Sort aliases longest-prefix-first** so `$lib/components/` beats `$lib/`.
- **Svelte 5 runes are not imports.** `$state`, `$derived`, `$effect` are compiler
  intrinsics. The alias matcher keys on a declared prefix **ending in `/`**, so `$state(`
  can never match `$lib/`. Worth an explicit test.
- **Relaxing `_extract_imports` changes what reaches `resolve_import` for ALL JS/TS
  files**, not only Svelte. Bare specifiers (`react`, `lodash`) will now arrive and
  **must be rejected** there — guard with `test_bare_package_still_unresolved`.
- Unresolvable specifiers return `None`, so the edge is **dropped, not left dangling**.
- `get_scan_root()` returns `None` outside a scan (e.g. a unit test calling the method
  directly) — handle it, exactly as `php.py` does.
- Google-style docstrings + type hints.

### Testing this task

CI on `dev` is red since 2026-07-27 for an **unrelated** `pillow-heif` dependency
conflict that kills `uv sync` before any test runs. Do not fix it, do not wait for green.

```bash
cd packages/ai-parrot/src
SITE_ROOT=~/.local/share/parrot-site ENV=dev PYTHONPATH=. \
  ~/.venvs/parrot-lite/bin/python -m pytest ../../../tests/knowledge/wiki/languages/ -q
```

`SITE_ROOT` is mandatory or navconfig raises `FileExistsError`.

### References in Codebase

- `languages/php.py:349-377` — **the** reference implementation: the only existing
  scanner that reads an auxiliary config file from the scan root and builds a prefix map
- `languages/javascript.py:298-341` — the two methods to change
- `tests/knowledge/wiki/languages/conftest.py:26-29` — the `_write(root, rel, content)`
  helper to reuse in the new fixture
- `tests/knowledge/wiki/languages/test_php_plugin.py` — how the PSR-4 prefix map is tested

---

## Acceptance Criteria

- [ ] `build_reference_index` returns a `JsIndex`; `JsIndex.aliases` is longest-prefix-first
- [ ] A `paths` entry `"$lib/*": ["src/lib/*"]` resolves `$lib/x` → `src/lib/x.ts`
- [ ] A repo with `svelte.config.js` and **no** declared paths still resolves `$lib/`
      (the convention fallback)
- [ ] `$lib/components/` wins over `$lib/` when both are declared
- [ ] `$app/environment` resolves to `None` — dropped, not dangling
- [ ] Bare packages (`react`, `lodash`) resolve to `None`
- [ ] Svelte 5 runes (`$state`, `$derived`) are never mistaken for aliases
- [ ] `svelte.config.js` is regex-scraped, never evaluated
- [ ] A malformed `tsconfig.json` degrades to the next discovery step, never raises
- [ ] Relative imports still resolve exactly as before — existing
      `test_javascript_plugin.py` resolution tests pass untouched
- [ ] Alias config is read **once** per scan, not per file
- [ ] Full suite green: `pytest ../../../tests/knowledge/wiki/languages/ -q`
- [ ] No lint errors on `javascript.py`

---

## Test Specification

```python
# tests/knowledge/wiki/languages/conftest.py — ADD (from spec §4)

@pytest.fixture
def svelte_repo(tmp_path):
    """Minimal SvelteKit-shaped repo: alias declared only by convention."""
    (tmp_path / "svelte.config.js").write_text("export default { kit: {} }\n")
    (tmp_path / "src/lib").mkdir(parents=True)
    (tmp_path / "src/lib/util.ts").write_text("export function helper(a: string) {}\n")
    (tmp_path / "src/lib/Widget.svelte").write_text(
        '<script lang="ts">\n'
        "  import { helper } from '$lib/util'\n"
        "  export const label = 'x'\n"
        "</script>\n"
        "<div>{label}</div>\n"
    )
    return tmp_path


# tests/knowledge/wiki/languages/test_javascript_plugin.py — ADD

import pytest
from parrot.knowledge.wiki.languages import set_scan_root
from parrot.knowledge.wiki.languages.javascript import JavaScriptScanner


def test_alias_from_tsconfig_paths(tmp_path):
    """A declared `paths` entry expands and then extension-guesses."""
    (tmp_path / "tsconfig.json").write_text(
        '{"compilerOptions": {"baseUrl": ".", '
        '"paths": {"$lib/*": ["src/lib/*"]}}}'
    )
    (tmp_path / "src/lib").mkdir(parents=True)
    (tmp_path / "src/lib/util.ts").write_text("export function helper() {}\n")
    set_scan_root(tmp_path)
    scanner = JavaScriptScanner()
    index = scanner.build_reference_index(
        ["tsconfig.json", "src/lib/util.ts", "src/lib/Widget.svelte"]
    )
    assert scanner.resolve_import(
        "$lib/util", "src/lib/Widget.svelte", index
    ) == "src/lib/util.ts"


def test_alias_sveltekit_convention_fallback(svelte_repo):
    """`$lib/` resolves with nothing but svelte.config.js present."""
    set_scan_root(svelte_repo)
    scanner = JavaScriptScanner()
    index = scanner.build_reference_index(
        ["svelte.config.js", "src/lib/util.ts", "src/lib/Widget.svelte"]
    )
    assert scanner.resolve_import(
        "$lib/util", "src/lib/Widget.svelte", index
    ) == "src/lib/util.ts"


def test_alias_longest_prefix_wins(tmp_path):
    """`$lib/components/` beats `$lib/` when both are declared."""
    (tmp_path / "tsconfig.json").write_text(
        '{"compilerOptions": {"baseUrl": ".", "paths": {'
        '"$lib/*": ["src/lib/*"], '
        '"$lib/components/*": ["src/widgets/*"]}}}'
    )
    (tmp_path / "src/widgets").mkdir(parents=True)
    (tmp_path / "src/widgets/Btn.ts").write_text("export const Btn = 1\n")
    set_scan_root(tmp_path)
    scanner = JavaScriptScanner()
    index = scanner.build_reference_index(["tsconfig.json", "src/widgets/Btn.ts"])
    assert scanner.resolve_import(
        "$lib/components/Btn", "src/routes/+page.svelte", index
    ) == "src/widgets/Btn.ts"


@pytest.mark.parametrize("spec", ["$app/environment", "$env/static/public"])
def test_alias_unresolved_returns_none(svelte_repo, spec):
    """SvelteKit virtual modules are dropped, not left dangling."""
    set_scan_root(svelte_repo)
    scanner = JavaScriptScanner()
    index = scanner.build_reference_index(["svelte.config.js", "src/lib/util.ts"])
    assert scanner.resolve_import(spec, "src/lib/Widget.svelte", index) is None


@pytest.mark.parametrize("spec", ["react", "lodash", "@sveltejs/kit"])
def test_bare_package_still_unresolved(svelte_repo, spec):
    """Bare packages now REACH resolve_import and must be rejected there."""
    set_scan_root(svelte_repo)
    scanner = JavaScriptScanner()
    index = scanner.build_reference_index(["svelte.config.js", "src/lib/util.ts"])
    assert scanner.resolve_import(spec, "src/lib/Widget.svelte", index) is None


def test_svelte_runes_are_not_aliases(svelte_repo):
    """`$state`/`$derived` are compiler intrinsics, never alias matches."""
    set_scan_root(svelte_repo)
    scanner = JavaScriptScanner()
    index = scanner.build_reference_index(["svelte.config.js", "src/lib/util.ts"])
    for rune in ("$state", "$derived", "$effect"):
        assert scanner.resolve_import(rune, "src/lib/Widget.svelte", index) is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 "Alias discovery order", §3 Module 4, §7
2. **Check dependencies** — TASK-2020 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-read `build_reference_index` / `resolve_import`
   and `php.py:349-377` before writing code
4. **Update status** in `sdd/tasks/index/wikitoolkit-svelte-typescript-support.json`
5. **Implement** per scope
6. **Verify** every acceptance criterion
7. **Move this file** to `sdd/tasks/completed/TASK-2022-js-alias-resolution-jsindex.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Code session (Opus 5), with Emmanuel Arroyo
**Date**: 2026-07-31

**Notes**:

`JsIndex` (frozen dataclass, `files` + longest-prefix-first `aliases`) replaces the
bare `frozenset`. `build_reference_index` discovers aliases once per scan via
`_discover_aliases`, following the `php.py:349-377` precedent exactly — local
import of `get_scan_root` to dodge the circular package init, `scan_root / rel`
when a root is set, `try/except` + `logger.debug` + continue on any unreadable or
unparseable file.

Discovery order, first declaration of a prefix winning: `svelte.config.js`
`kit.alias` (regex-scraped, never evaluated) → `tsconfig.json`/`jsconfig.json`
`compilerOptions.paths` (resolved through `baseUrl`, itself relative to the config's
own directory) → the SvelteKit convention fallback.

`resolve_import` keeps the relative branch first and unchanged, then scans the
alias map. The extension-guessing and `/index.*` tail moved into a shared
`_guess_target` so both branches use identical matching rather than a copy.

End-to-end on the motivating shape — a repo whose alias is declared **nowhere**,
only implied by the presence of `svelte.config.js`:

```
files scanned : src/lib/Widget.svelte, src/lib/util.ts, svelte.config.js
imports       : ['$lib/util']
edge $lib/util -> src/lib/util.ts : YES   (0 such edges before this task)
```

**Behaviour change worth flagging to the owner.** Relaxing `_extract_imports` was
unavoidable — `$lib/util` does not start with `.`, so it was being dropped before
`resolve_import` ever saw it — but it changes `LanguageOutline.imports` for **every**
JS/TS file, not only components: bare package names (`react`, `lodash`) now appear
there. Edges are unaffected, since `resolve_import` rejects them, but the `imports`
list rendered on every JS/TS wiki page grows. The pre-existing
`test_jsts_imports_only_relative` asserted the opposite and had to be inverted; it
is now `test_jsts_imports_include_bare_specifiers`, carrying the reasoning. This is
the spec's own §7 prediction, not a surprise — but it is the one user-visible
regression risk in this task, and it is worth a line in the PR description.

Two things beyond the task's letter:

1. **`restore_scan_root` fixture** (in `conftest.py`). `set_scan_root` mutates
   process-global state, so a test pointing it at its own `tmp_path` leaks that
   path into every test collected afterwards. The task's own test scaffold called
   `set_scan_root(tmp_path)` bare; that would have been an order-dependent
   time bomb, the same class of bug as the `_PARSER_CACHE` one in TASK-2019.
2. **Non-wildcard alias entries are supported** (`"$lib": "src/lib"` as well as
   `"$lib/*": ["src/lib/*"]`), normalized by `_as_prefix_pair` to a
   `/`-terminated pair either way.

*Known limitation, deliberate:* an alias is always a `/`-terminated **prefix**, so a
bare `import x from '$components'` (exact match, no subpath) does not resolve. That
is what makes the Svelte 5 rune guarantee structural rather than a special case —
`$state` cannot prefix-match `$lib/` — and it matches the spec's declared data
model. Worth revisiting only if a real repo hits it.

Tests: 17 added. Covers the task's five plus the `kit.alias` scrape path, a
malformed `tsconfig.json` (comments + trailing comma — legal tsconfig, invalid
stdlib json) degrading to the convention fallback, `get_scan_root()` returning
`None` outside a scan, relative resolution unchanged, `JsIndex` hashability/frozenness,
and all four Svelte 5 runes parametrized.

Verification (`~/.venvs/parrot-lite`):
- `tests/knowledge/wiki/languages/` — **132 passed, 1 skipped** (115+1 after
  TASK-2021; +17)
- wider `tests/knowledge/wiki/` — 166 failed / 395 passed, **identical failure
  count to clean `dev`** (166/333)
- `ruff check` — clean, after fixing a real B017 it caught in my own test (blind
  `pytest.raises(Exception)` → `FrozenInstanceError`)

**Deviations from spec**: none. No `mode` change, no docs, no integration tests —
those are TASK-2023.
