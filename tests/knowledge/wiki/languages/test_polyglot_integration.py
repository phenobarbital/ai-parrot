"""Polyglot integration test for the registry-driven repo scanner (FEAT-394).

Scans a tiny fixture repo covering every deep-scanned language plus HTML,
and verifies: every file gets a page, ``FileSlice.language`` is set (or
not) correctly per file, per-language ``references`` edges are derived
correctly, and — the isolation guarantee at the heart of Module 3 — a
PHP import can never resolve into a JS/TS (or any other language's)
file page.
"""

from pathlib import Path

from parrot.knowledge.wiki.languages import all_scanners
from parrot.knowledge.wiki.repo_scan import file_concept_id, scan_repository


def _write(root: Path, rel: str, content: str) -> None:
    """Write a fixture file, creating parent directories as needed."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_scan_repository_polyglot_fixture(polyglot_repo):
    scan = scan_repository(polyglot_repo)

    # All files scanned.
    paths = {fs.rel_path for fs in scan.files}
    assert "src/app.py" in paths
    assert "src/Service.php" in paths
    assert "web/index.ts" in paths
    assert "web/util/index.ts" in paths
    assert "native/src/lib.rs" in paths
    assert "native/src/parser.rs" in paths
    assert "public/index.html" in paths
    assert "composer.json" in paths
    assert "lib/MyApp/Schema.pm" in paths
    assert "lib/MyApp/User.pm" in paths

    # Language field set correctly.
    by_path = {fs.rel_path: fs for fs in scan.files}
    assert by_path["src/app.py"].language == "python"
    assert by_path["src/Service.php"].language == "php"
    assert by_path["web/index.ts"].language == "javascript"
    assert by_path["native/src/lib.rs"].language == "rust"
    assert by_path["lib/MyApp/User.pm"].language == "perl"
    assert by_path["public/index.html"].language is None  # shallow scan, no scanner
    assert by_path["composer.json"].language is None  # config, no scanner

    # HTML got a title-based summary, no outline.
    assert by_path["public/index.html"].record.summary == "Public Site"
    assert "## API outline" not in by_path["public/index.html"].record.body

    # Every deep-scanned language got an outline.
    assert "## API outline" in by_path["src/app.py"].record.body
    assert "## API outline" in by_path["src/Service.php"].record.body
    assert "## API outline" in by_path["web/index.ts"].record.body
    assert "## API outline" in by_path["native/src/lib.rs"].record.body
    assert "## API outline" in by_path["lib/MyApp/User.pm"].record.body

    edges = set(scan.import_edges)

    # JS/TS edge: web/index.ts imports './util' -> web/util/index.ts.
    assert (
        file_concept_id("web/index.ts"),
        file_concept_id("web/util/index.ts"),
        "references",
    ) in edges

    # Rust edge: native/src/lib.rs declares `mod parser;` -> parser.rs.
    assert (
        file_concept_id("native/src/lib.rs"),
        file_concept_id("native/src/parser.rs"),
        "references",
    ) in edges

    # Perl edge: lib/MyApp/User.pm `use MyApp::Schema;` -> lib/MyApp/Schema.pm.
    assert (
        file_concept_id("lib/MyApp/User.pm"),
        file_concept_id("lib/MyApp/Schema.pm"),
        "references",
    ) in edges

    # Isolation guarantee: no PHP-sourced edge ever targets a JS/TS file
    # (Service.php's `use App\Base\Model` is unresolvable here — no
    # Base/Model.php exists — so it produces no edge at all, but the
    # invariant holds unconditionally regardless of what PHP imports).
    for src, dst, _rel in edges:
        if src == file_concept_id("src/Service.php"):
            assert not dst.endswith(".ts")
            assert not dst.endswith(".js")


def test_stats_languages_block():
    """``all_scanners()`` reports every registered language's active mode —
    the same mapping ``_write_build_stats``/``status`` expose as the
    ``languages`` block."""
    languages = {name: scanner.mode for name, scanner in all_scanners().items()}
    assert languages["python"] == "ast"
    assert "php" in languages
    assert "javascript" in languages
    assert "rust" in languages
    assert "perl" in languages
    assert set(languages.values()) <= {"ast", "tree-sitter", "heuristic"}


def test_polyglot_svelte_alongside_python(tmp_path):
    """`.svelte` and `.py` in one scan: both outlined, no cross-talk.

    FEAT-396 / TASK-2023. Guards the registry boundary — claiming
    `.svelte` for the JS scanner must not let a Svelte import resolve
    into a Python page, nor vice versa.
    """
    _write(
        tmp_path, "svelte.config.js", "export default { kit: {} }\n"
    )
    _write(
        tmp_path,
        "src/app.py",
        '"""Application entrypoint."""\n\n\ndef main() -> None:\n'
        '    """Run the app."""\n',
    )
    _write(tmp_path, "src/lib/util.ts", "export function helper() {}\n")
    _write(
        tmp_path,
        "src/lib/Widget.svelte",
        '<script lang="ts">\n'
        "  import { helper } from '$lib/util'\n"
        "  export function render(): string { return 'x' }\n"
        "</script>\n"
        "<div>hi</div>\n",
    )

    scan = scan_repository(tmp_path, use_git=False)
    by_path = {fs.rel_path: fs for fs in scan.files}

    # Both languages present, each routed to its own scanner.
    assert by_path["src/app.py"].language == "python"
    assert by_path["src/lib/Widget.svelte"].language == "javascript"

    # Both got a real outline — the component is no longer a shallow page.
    assert "## API outline" in by_path["src/app.py"].record.body
    assert "## API outline" in by_path["src/lib/Widget.svelte"].record.body
    assert "render" in by_path["src/lib/Widget.svelte"].record.body

    # The alias edge exists...
    edges = set(scan.import_edges)
    assert (
        file_concept_id("src/lib/Widget.svelte"),
        file_concept_id("src/lib/util.ts"),
        "references",
    ) in edges

    # ...and no Svelte-sourced edge ever lands on a Python page.
    for src, dst, _rel in edges:
        if src == file_concept_id("src/lib/Widget.svelte"):
            assert dst != file_concept_id("src/app.py")
