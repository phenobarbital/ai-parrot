"""Shared fixtures for the wiki language-scanner test suite (FEAT-394)."""

from __future__ import annotations

from pathlib import Path

import pytest
from parrot.knowledge.wiki.languages import astgrep, treesitter


def _has_astgrep() -> bool:
    """Whether ``ast-grep-py`` is importable (module-load-time probe)."""
    return astgrep.is_available()


#: Marker for tests that require the optional ``ast-grep-py`` extra —
#: skipped (not failed) when the ``wiki-structural`` extra is absent.
requires_astgrep = pytest.mark.skipif(not _has_astgrep(), reason="ast-grep-py not installed")


@pytest.fixture
def force_no_astgrep(monkeypatch):
    """Pretend ``ast-grep-py`` is not installed for this test.

    Monkeypatches :func:`parrot.knowledge.wiki.languages.astgrep.is_available`
    to always return ``False`` and clears the ``RuleSet.load`` cache, so
    scanners exercise their tree-sitter/heuristic tiers unconditionally
    regardless of whether the optional ``ai-parrot[wiki-structural]``
    extra happens to be installed in the environment running the suite.
    """
    monkeypatch.setattr(astgrep, "is_available", lambda: False)
    astgrep.RuleSet.load.cache_clear()
    yield
    astgrep.RuleSet.load.cache_clear()


@pytest.fixture
def force_heuristic(monkeypatch):
    """Force every scanner onto its heuristic path for this test.

    Monkeypatches :func:`parrot.knowledge.wiki.languages.treesitter.get_parser`
    to always return ``None`` and clears its cache afterwards, so tests can
    deterministically exercise the stdlib-only fallback regardless of
    whether the optional ``ai-parrot[wiki-languages]`` extra (and its
    grammar wheels) happen to be installed in the environment running
    the suite.
    """
    monkeypatch.setattr(treesitter, "get_parser", lambda language: None)
    yield


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def restore_scan_root():
    """Restore the module-level scan root after a test sets it.

    ``set_scan_root`` mutates process-global state, so a test that points
    it at its own ``tmp_path`` would otherwise leak that path into every
    test collected after it.
    """
    from parrot.knowledge.wiki.languages import get_scan_root, set_scan_root

    previous = get_scan_root()
    yield set_scan_root
    set_scan_root(previous)


@pytest.fixture
def svelte_repo(tmp_path: Path) -> Path:
    """Minimal SvelteKit-shaped repo whose alias is declared only by convention.

    No ``paths`` entry anywhere and no ``.svelte-kit/`` directory — the
    state of a fresh clone, where ``$lib`` resolves purely by SvelteKit
    convention (FEAT-396 spec, §2 "Alias discovery order", step 3).
    """
    _write(tmp_path, "svelte.config.js", "export default { kit: {} }\n")
    _write(tmp_path, "src/lib/util.ts", "export function helper(a: string) {}\n")
    _write(
        tmp_path,
        "src/lib/Widget.svelte",
        '<script lang="ts">\n'
        "  import { helper } from '$lib/util'\n"
        "  export const label = 'x'\n"
        "</script>\n"
        "<div>{label}</div>\n",
    )
    return tmp_path


@pytest.fixture
def polyglot_repo(tmp_path: Path) -> Path:
    """Tiny repo with one file per supported language plus HTML.

    ``src/app.py``, ``src/Service.php`` + ``composer.json``,
    ``web/index.ts`` + ``web/util/index.ts``, ``native/src/lib.rs`` +
    ``native/src/parser.rs``, ``lib/MyApp/Schema.pm`` +
    ``lib/MyApp/User.pm``, ``public/index.html``. Includes one
    resolvable cross-file import per deep-scanned language (Python is
    import-free here — its resolution is already exhaustively covered by
    ``test_repo_scan.py``) so ``references`` edges can be asserted
    per-language without any cross-language leakage.
    """
    _write(
        tmp_path, "src/app.py",
        '"""Application entrypoint."""\n\n\ndef main() -> None:\n'
        '    """Run the app."""\n\n\n'
        # FEAT-498 TASK-2752: a Python symbol every e2e assertion can
        # anchor on (`sym:src/app.py#helper`) without depending on the
        # entrypoint's own name.
        "def helper() -> int:\n"
        '    """A tiny helper."""\n'
        "    return 1\n",
    )
    _write(
        tmp_path, "src/Service.php",
        "<?php\nnamespace App;\n\nuse App\\Base\\Model;\n\n/**\n"
        " * Main application service.\n */\nclass Service extends Model {\n"
        "    /**\n     * Run the service.\n     */\n"
        "    public function run(): void { ... }\n}\n",
    )
    _write(
        tmp_path, "composer.json",
        '{"autoload": {"psr-4": {"App\\\\": "src/"}}}\n',
    )
    _write(
        tmp_path, "web/index.ts",
        "import { helper } from './util';\n\n/**\n * Main entry.\n */\n"
        "export function main(): void { ... }\n",
    )
    _write(
        tmp_path, "web/util/index.ts",
        'export function helper(): string {\n    return "ok";\n}\n',
    )
    _write(
        tmp_path, "native/src/lib.rs",
        "/// Native crate root.\npub mod parser;\n\npub fn init() {}\n",
    )
    _write(
        tmp_path, "native/src/parser.rs",
        "/// Parser module.\npub struct Parser;\n",
    )
    _write(
        tmp_path, "public/index.html",
        "<html><head><title>Public Site</title></head><body></body></html>\n",
    )
    _write(
        tmp_path, "lib/MyApp/Schema.pm",
        "package MyApp::Schema;\n\nsub connect { }\n1;\n",
    )
    _write(
        tmp_path, "lib/MyApp/User.pm",
        "package MyApp::User;\nuse MyApp::Schema;\n\n"
        "sub new {\n    my ($class) = @_;\n    return bless {}, $class;\n}\n1;\n",
    )
    # FEAT-498 TASK-2752: a Svelte file alongside everything else, so the
    # e2e suite's polyglot build covers every language `all_scanners()`
    # registers, not just the deep-scanned five. Routed through the JS/TS
    # scanner (FEAT-396) — an isolated file, no cross-language edges.
    _write(
        tmp_path, "src/lib/Widget.svelte",
        '<script lang="ts">\n'
        "  export function render(): string { return 'x' }\n"
        "</script>\n"
        "<div>hi</div>\n",
    )
    return tmp_path
