"""Unit tests for the PHP language plugin (heuristic mode).

Tree-sitter mode is exercised only when the optional
``ai-parrot[wiki-languages]`` extra (and the ``tree_sitter_php`` grammar
wheel) is installed — not the case in this dev environment, so
``PhpScanner().mode`` naturally reports ``"heuristic"`` here and every
outline test uses the ``force_heuristic`` fixture to be explicit and
environment-independent.
"""

from parrot.knowledge.wiki import languages as languages_module
from parrot.knowledge.wiki.languages import scanner_for
from parrot.knowledge.wiki.languages.php import PhpScanner

SAMPLE_PHP = '''<?php
namespace App\\Models;

use App\\Base\\Model;
use App\\Traits\\{HasTimestamps, SoftDeletes};

/**
 * User model for authentication.
 */
class User extends Model {
    /**
     * Get the full name.
     */
    public function getFullName(): string { ... }
}

function helper_function(string $x): void { ... }
'''


def test_php_outline_heuristic(force_heuristic):
    scanner = PhpScanner()
    result = scanner.outline(SAMPLE_PHP, "src/Models/User.php")
    assert any("class User" in line for line in result.outline)
    assert any("getFullName" in line for line in result.outline)
    assert "App\\Base\\Model" in result.imports


def test_php_group_use_expanded(force_heuristic):
    scanner = PhpScanner()
    result = scanner.outline(SAMPLE_PHP, "src/Models/User.php")
    assert "App\\Traits\\HasTimestamps" in result.imports
    assert "App\\Traits\\SoftDeletes" in result.imports


def test_php_method_indented_under_class(force_heuristic):
    scanner = PhpScanner()
    result = scanner.outline(SAMPLE_PHP, "src/Models/User.php")
    method_lines = [line for line in result.outline if "getFullName" in line]
    assert method_lines
    assert method_lines[0].startswith("    def ")


def test_php_toplevel_function_not_indented(force_heuristic):
    scanner = PhpScanner()
    result = scanner.outline(SAMPLE_PHP, "src/Models/User.php")
    fn_lines = [line for line in result.outline if "helper_function" in line]
    assert fn_lines
    assert fn_lines[0].startswith("function ")


def test_php_docblock_first_line_used(force_heuristic):
    scanner = PhpScanner()
    result = scanner.outline(SAMPLE_PHP, "src/Models/User.php")
    assert any("Get the full name." in line for line in result.outline)


def test_php_psr4_resolution():
    # No real composer.json exists on disk for this fixture, so the PSR-4
    # map is empty and resolution falls through to namespace-tail
    # matching — still enough to resolve this unambiguous case.
    scanner = PhpScanner()
    rel_paths = ["src/Models/User.php", "src/Base/Model.php", "composer.json"]
    index = scanner.build_reference_index(rel_paths)
    target = scanner.resolve_import("App\\Base\\Model", "src/Models/User.php", index)
    assert target == "src/Base/Model.php"


def test_php_psr4_resolution_uses_scan_root_not_cwd(tmp_path, monkeypatch):
    """PSR-4 resolution must read ``composer.json`` relative to the
    *scanned repo root*, not the process CWD — the common case for
    ``wikitoolkit build --path /other/repo`` where the two differ."""
    (tmp_path / "src" / "Models").mkdir(parents=True)
    (tmp_path / "src" / "Base").mkdir(parents=True)
    (tmp_path / "src" / "Models" / "User.php").write_text("<?php\n")
    (tmp_path / "src" / "Base" / "Model.php").write_text("<?php\n")
    (tmp_path / "composer.json").write_text(
        '{"autoload": {"psr-4": {"App\\\\": "src/"}}}'
    )
    # CWD is genuinely different from the scanned root.
    monkeypatch.chdir(tmp_path.parent)
    monkeypatch.setattr(languages_module, "_scan_root", tmp_path)

    scanner = PhpScanner()
    rel_paths = ["src/Models/User.php", "src/Base/Model.php", "composer.json"]
    index = scanner.build_reference_index(rel_paths)
    psr4_map, _file_set = index
    assert psr4_map == {"App\\": "src/"}
    target = scanner.resolve_import("App\\Base\\Model", "src/Models/User.php", index)
    assert target == "src/Base/Model.php"


def test_php_psr4_falls_back_to_cwd_without_scan_root(monkeypatch):
    """With no scan root recorded, PSR-4 lookup degrades to the pre-fix
    CWD-relative behaviour rather than raising."""
    monkeypatch.setattr(languages_module, "_scan_root", None)
    scanner = PhpScanner()
    rel_paths = ["src/Models/User.php", "composer.json"]
    index = scanner.build_reference_index(rel_paths)  # composer.json absent from CWD
    psr4_map, _file_set = index
    assert psr4_map == {}


def test_php_require_relative():
    scanner = PhpScanner()
    rel_paths = ["lib/a.php", "lib/helpers/b.php"]
    index = scanner.build_reference_index(rel_paths)
    target = scanner.resolve_import("helpers/b.php", "lib/a.php", index)
    assert target == "lib/helpers/b.php"


def test_php_require_dir_concatenation_extracted(force_heuristic):
    scanner = PhpScanner()
    source = "<?php\nrequire __DIR__ . '/helpers/b.php';\n"
    result = scanner.outline(source, "lib/a.php")
    assert "/helpers/b.php" in result.imports


def test_php_unresolvable_import_returns_none():
    scanner = PhpScanner()
    rel_paths = ["src/Models/User.php"]
    index = scanner.build_reference_index(rel_paths)
    result = scanner.resolve_import(
        "Totally\\Unknown\\Thing", "src/Models/User.php", index
    )
    assert result is None


def test_php_tolerates_html_prefix(force_heuristic):
    source = "<html><body><?php class Foo {} ?>"
    scanner = PhpScanner()
    result = scanner.outline(source, "mixed.php")
    assert any("Foo" in line for line in result.outline)


def test_php_parse_failure_degrades_empty(force_heuristic, force_no_astgrep, monkeypatch):
    # FEAT-498: force_no_astgrep is required too now that php.yaml
    # (TASK-2743) makes the ast-grep seam a real, working first tier.
    scanner = PhpScanner()

    def _boom(source):
        raise RuntimeError("boom")

    monkeypatch.setattr(scanner, "_outline_heuristic", _boom)
    result = scanner.outline("<?php class X {}", "x.php")
    assert result.summary == ""
    assert result.outline == []
    assert result.imports == []


def test_scanner_for_php_returns_php_scanner():
    assert isinstance(scanner_for(".php"), PhpScanner)


def test_php_scanner_mode_is_heuristic_without_grammar(force_heuristic):
    assert PhpScanner().mode == "heuristic"
