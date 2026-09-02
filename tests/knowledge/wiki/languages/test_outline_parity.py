"""Byte-parity harness: ``outline()`` with and without the ast-grep seam.

Rule tasks (TASK-2742..2746) extend ``CASES`` with their own fixture and
re-run this same harness to prove strict parity once a rule file makes
the seam actually serve a file for that language; landing a rule file
also adds the language's key to ``SERVED_BY_RULE`` so
``test_seam_service_matches_available_rules`` tracks which languages are
currently expected to report ``mode == "ast-grep"``.
"""

from __future__ import annotations

import pytest
from parrot.knowledge.wiki.languages import astgrep, scanner_for

PHP_SRC = (
    "<?php\nnamespace App;\n\n/**\n * A service.\n */\nclass Service {\n"
    "    /**\n     * Run it.\n     */\n    public function run(): void { ... }\n}\n\n"
    "function helper(): void { ... }\n"
)

RUST_SRC = (
    "/// A parser.\npub struct Parser {\n    pub name: String,\n}\n\n"
    "impl Parser {\n    /// Create one.\n    pub fn new(name: &str) -> Self { ... }\n}\n\n"
    "pub fn free_fn() {}\n"
)

TS_SRC = (
    "/**\n * Main entry.\n */\nexport function main(): void { ... }\n\n"
    "export const LABEL = 'x';\n"
)

PERL_SRC = (
    "package MyApp::Schema;\n\n=head2 connect\n\nConnect to the DB.\n\n=cut\n\n"
    "sub connect { }\n1;\n"
)

CASES = [
    ("php", ".php", PHP_SRC),
    ("rust", ".rs", RUST_SRC),
    ("javascript", ".ts", TS_SRC),
    ("perl", ".pm", PERL_SRC),
]

#: Languages with a landed rule file (``languages/rules/<lang>.yaml``).
#: TASK-2742 lands ``typescript.yaml`` (served under the ``javascript``
#: scanner name); TASK-2743 lands ``php.yaml``; TASK-2744/2745 add
#: rust/perl here as they land.
SERVED_BY_RULE = {"javascript", "php"}


@pytest.mark.parametrize("lang,suffix,src", CASES, ids=[c[0] for c in CASES])
def test_outline_parity_with_and_without_seam(lang, suffix, src, monkeypatch):
    """``outline()`` is identical whether or not ``ast-grep-py`` is importable."""
    scanner = scanner_for(suffix)
    assert scanner is not None

    with_seam = scanner.outline(src, f"x{suffix}")

    monkeypatch.setattr(astgrep, "is_available", lambda: False)
    without_seam = scanner.outline(src, f"x{suffix}")

    assert with_seam.outline == without_seam.outline
    assert with_seam.summary == without_seam.summary
    assert with_seam.imports == without_seam.imports


@pytest.mark.parametrize("lang,suffix,src", CASES, ids=[c[0] for c in CASES])
def test_seam_service_matches_available_rules(lang, suffix, src):
    """``mode == "ast-grep"`` iff a rule file for ``lang`` has landed."""
    scanner = scanner_for(suffix)
    assert scanner is not None
    scanner.outline(src, f"x{suffix}")
    if lang in SERVED_BY_RULE:
        assert scanner.mode == "ast-grep"
    else:
        assert scanner.mode != "ast-grep"


def test_polyglot_repo_parity(polyglot_repo, monkeypatch):
    """Every deep-scanned language file in the polyglot fixture is stable."""
    per_language_files = {
        "src/Service.php": ".php",
        "web/index.ts": ".ts",
        "native/src/lib.rs": ".rs",
        "lib/MyApp/Schema.pm": ".pm",
    }
    baseline = {}
    for rel, suffix in per_language_files.items():
        scanner = scanner_for(suffix)
        source = (polyglot_repo / rel).read_text(encoding="utf-8")
        baseline[rel] = scanner.outline(source, rel)

    monkeypatch.setattr(astgrep, "is_available", lambda: False)
    for rel, suffix in per_language_files.items():
        scanner = scanner_for(suffix)
        source = (polyglot_repo / rel).read_text(encoding="utf-8")
        without_seam = scanner.outline(source, rel)
        assert without_seam.outline == baseline[rel].outline
        assert without_seam.summary == baseline[rel].summary
        assert without_seam.imports == baseline[rel].imports
