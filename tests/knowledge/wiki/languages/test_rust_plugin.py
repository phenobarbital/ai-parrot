"""Unit tests for the Rust language plugin (heuristic mode).

Tree-sitter mode is exercised only when the optional
``ai-parrot[wiki-languages]`` extra (and the ``tree_sitter_rust`` grammar
wheel) is installed — not the case in this dev environment, so every
outline test uses the ``force_heuristic`` fixture to be explicit and
environment-independent.
"""

from parrot.knowledge.wiki.languages import scanner_for
from parrot.knowledge.wiki.languages.rust import RustScanner

SAMPLE_RUST = '''
/// A document parser.
pub struct Parser {
    pub name: String,
    buffer: Vec<u8>,
}

/// Parser implementation.
impl Parser {
    /// Create a new parser.
    pub fn new(name: &str) -> Self { ... }

    /// Parse the input.
    pub async fn parse(&self, input: &str) -> Result<Doc, Error> { ... }
}

pub enum Format {
    Json,
    Yaml,
}

/// Utility trait.
pub trait Serializable {
    /// Serialize to bytes.
    fn to_bytes(&self) -> Vec<u8>;
}

mod tests;
use crate::utils::helpers;
'''


def test_rust_outline_pub_items(force_heuristic):
    scanner = RustScanner()
    result = scanner.outline(SAMPLE_RUST, "src/parser.rs")
    names = " ".join(result.outline)
    assert "Parser" in names
    assert "Format" in names
    assert "Serializable" in names
    assert "new" in names
    assert "parse" in names


def test_rust_impl_methods_indented(force_heuristic):
    scanner = RustScanner()
    result = scanner.outline(SAMPLE_RUST, "src/parser.rs")
    new_lines = [line for line in result.outline if "fn new" in line]
    assert new_lines
    assert new_lines[0].startswith("    ")


def test_rust_impl_header_rendered(force_heuristic):
    scanner = RustScanner()
    result = scanner.outline(SAMPLE_RUST, "src/parser.rs")
    assert "impl Parser:" in result.outline


def test_rust_doc_comments(force_heuristic):
    scanner = RustScanner()
    result = scanner.outline(SAMPLE_RUST, "src/parser.rs")
    assert any("document parser" in line.lower() for line in result.outline)


def test_rust_summary_from_leading_doc(force_heuristic):
    scanner = RustScanner()
    result = scanner.outline(SAMPLE_RUST, "src/parser.rs")
    assert result.summary == "A document parser."


def test_rust_mod_and_use_extracted(force_heuristic):
    scanner = RustScanner()
    result = scanner.outline(SAMPLE_RUST, "src/parser.rs")
    assert "mod:tests" in result.imports
    assert "crate::utils::helpers" in result.imports


def test_rust_mod_resolution():
    scanner = RustScanner()
    rel_paths = ["src/lib.rs", "src/parser.rs", "src/utils/mod.rs", "src/utils/helpers.rs"]
    index = scanner.build_reference_index(rel_paths)
    assert scanner.resolve_import("mod:parser", "src/lib.rs", index) == "src/parser.rs"
    assert scanner.resolve_import("mod:utils", "src/lib.rs", index) == "src/utils/mod.rs"


def test_rust_use_crate_resolution():
    scanner = RustScanner()
    rel_paths = ["src/lib.rs", "src/parser.rs", "src/utils/helpers.rs"]
    index = scanner.build_reference_index(rel_paths)
    target = scanner.resolve_import(
        "crate::utils::helpers", "src/parser.rs", index
    )
    assert target == "src/utils/helpers.rs"


def test_rust_unresolvable_mod_returns_none():
    scanner = RustScanner()
    rel_paths = ["src/lib.rs"]
    index = scanner.build_reference_index(rel_paths)
    assert scanner.resolve_import("mod:missing", "src/lib.rs", index) is None


def test_rust_use_crate_without_root_returns_none():
    scanner = RustScanner()
    rel_paths = ["parser.rs"]  # no lib.rs/main.rs anywhere
    index = scanner.build_reference_index(rel_paths)
    assert scanner.resolve_import("crate::utils::helpers", "parser.rs", index) is None


def test_rust_parse_failure_degrades_empty(force_heuristic, monkeypatch):
    scanner = RustScanner()

    def _boom(source):
        raise RuntimeError("boom")

    monkeypatch.setattr(scanner, "_outline_heuristic", _boom)
    result = scanner.outline("pub struct X {}", "x.rs")
    assert result.summary == ""
    assert result.outline == []
    assert result.imports == []


def test_scanner_for_rs_returns_rust_scanner():
    assert isinstance(scanner_for(".rs"), RustScanner)


def test_rust_scanner_mode_is_heuristic_without_grammar(force_heuristic):
    assert RustScanner().mode == "heuristic"
