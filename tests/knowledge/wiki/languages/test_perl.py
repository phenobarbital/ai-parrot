"""Unit tests for the Perl language plugin (FEAT-432).

Heuristic-mode tests use the shared ``force_heuristic`` fixture
(``conftest.py``) to be explicit and environment-independent. Tree-sitter
tests are skipped unless the optional ``tree-sitter-perl`` grammar wheel
is installed.
"""

from __future__ import annotations

import textwrap

import pytest
from parrot.knowledge.wiki.languages import scanned_suffixes, scanner_for, treesitter
from parrot.knowledge.wiki.languages.base import LanguageOutline
from parrot.knowledge.wiki.languages.perl import PerlScanner

_TREESITTER_AVAILABLE = treesitter.get_parser("perl") is not None


@pytest.fixture
def scanner() -> PerlScanner:
    return PerlScanner()


@pytest.fixture
def moose_source() -> str:
    return textwrap.dedent("""\
        package MyApp::Model::User;
        use Moose;
        use MyApp::Schema;

        has 'name' => (is => 'ro', isa => 'Str');
        has 'email' => (is => 'rw', isa => 'Str');

        sub validate {
            my ($self) = @_;
            return 1;
        }

        sub to_hashref {
            my ($self) = @_;
            return { name => $self->name, email => $self->email };
        }

        __PACKAGE__->meta->make_immutable;
        1;
    """)


@pytest.fixture
def corinna_source() -> str:
    return textwrap.dedent("""\
        use v5.38;
        class Point {
            field $x :param;
            field $y :param;

            method coordinates () {
                return ($x, $y);
            }
        }
    """)


@pytest.fixture
def multi_package_source() -> str:
    return textwrap.dedent("""\
        package Foo;
        sub foo_method { }

        package Bar;
        sub bar_method { }
        1;
    """)


@pytest.fixture
def pod_source() -> str:
    return textwrap.dedent("""\
        =head1 NAME

        MyApp::Utils - Utility functions for MyApp

        =head1 DESCRIPTION

        This module provides common utilities.

        =cut

        package MyApp::Utils;
        sub helper { }
        1;
    """)


@pytest.fixture
def repo_paths() -> list[str]:
    return [
        "lib/MyApp/Model/User.pm",
        "lib/MyApp/Schema.pm",
        "lib/MyApp/Controller/Auth.pm",
        "bin/app.pl",
        "t/model_user.t",
    ]


# --- Registration -----------------------------------------------------------


class TestRegistration:
    def test_scanner_for_pm(self):
        assert isinstance(scanner_for(".pm"), PerlScanner)

    def test_scanner_for_pl(self):
        assert isinstance(scanner_for(".pl"), PerlScanner)

    def test_scanner_for_t(self):
        assert isinstance(scanner_for(".t"), PerlScanner)

    def test_suffixes_in_scanned(self):
        suffixes = scanned_suffixes()
        assert {".pm", ".pl", ".t"} <= suffixes

    def test_scanner_basics(self, scanner: PerlScanner):
        assert scanner.name == "perl"
        assert scanner.suffixes == frozenset({".pl", ".pm", ".t"})


# --- Heuristic mode (always available) --------------------------------------


class TestHeuristic:
    def test_package_statement(self, scanner: PerlScanner, force_heuristic):
        result = scanner.outline("package Foo::Bar;\n1;\n", "lib/Foo/Bar.pm")
        assert "package Foo::Bar" in result.outline

    def test_sub_declaration(self, scanner: PerlScanner, force_heuristic):
        source = "package Foo;\nsub bar { }\n1;\n"
        result = scanner.outline(source, "lib/Foo.pm")
        assert any("sub bar" in line for line in result.outline)

    def test_moose_has(self, scanner: PerlScanner, moose_source: str, force_heuristic, force_no_astgrep):
        # FEAT-498: force_no_astgrep is required too — perl.yaml's
        # ATTRIBUTE rule (TASK-2745) deliberately does not extract the
        # `isa => 'Type'` suffix (finding the value tied to the specific
        # key `isa`, as opposed to `is`, needs key/value pair matching
        # beyond the seam's generic field/path primitives), so only the
        # heuristic/tree-sitter tiers reproduce it.
        result = scanner.outline(moose_source, "lib/MyApp/Model/User.pm")
        assert any("has name" in line for line in result.outline)
        assert any("has email" in line for line in result.outline)
        assert any("Str" in line for line in result.outline if "has" in line)

    def test_corinna_class(self, scanner: PerlScanner, corinna_source: str, force_heuristic):
        result = scanner.outline(corinna_source, "lib/Point.pm")
        assert any("class Point" in line for line in result.outline)

    def test_corinna_role(self, scanner: PerlScanner, force_heuristic):
        result = scanner.outline("role Serializable {\n}\n", "lib/Serializable.pm")
        assert any("role Serializable" in line for line in result.outline)

    def test_corinna_field(self, scanner: PerlScanner, corinna_source: str, force_heuristic):
        result = scanner.outline(corinna_source, "lib/Point.pm")
        assert any("field $x" in line for line in result.outline)
        assert any("field $y" in line for line in result.outline)

    def test_corinna_method(self, scanner: PerlScanner, corinna_source: str, force_heuristic):
        result = scanner.outline(corinna_source, "lib/Point.pm")
        assert any("method coordinates" in line for line in result.outline)

    def test_pod_summary(self, scanner: PerlScanner, pod_source: str, force_heuristic):
        result = scanner.outline(pod_source, "lib/MyApp/Utils.pm")
        assert "MyApp::Utils" in result.summary
        assert "Utility functions" in result.summary

    def test_multiple_packages(self, scanner: PerlScanner, multi_package_source: str, force_heuristic):
        result = scanner.outline(multi_package_source, "lib/Multi.pm")
        assert "package Foo" in result.outline
        assert "package Bar" in result.outline
        assert any("foo_method" in line for line in result.outline)
        assert any("bar_method" in line for line in result.outline)

    def test_nested_sub_indentation(self, scanner: PerlScanner, moose_source: str, force_heuristic):
        result = scanner.outline(moose_source, "lib/MyApp/Model/User.pm")
        sub_lines = [line for line in result.outline if "sub validate" in line]
        assert sub_lines
        assert sub_lines[0].startswith("    ")

    def test_standalone_sub_not_indented(self, scanner: PerlScanner, force_heuristic):
        result = scanner.outline("sub standalone { }\n", "bin/app.pl")
        sub_lines = [line for line in result.outline if "standalone" in line]
        assert sub_lines
        assert not sub_lines[0].startswith(" ")

    def test_use_require_imports(self, scanner: PerlScanner, moose_source: str, force_heuristic):
        result = scanner.outline(moose_source, "lib/MyApp/Model/User.pm")
        assert "MyApp::Schema" in result.imports

    def test_require_imports(self, scanner: PerlScanner, force_heuristic):
        result = scanner.outline("use Foo::Bar;\nrequire Baz::Qux;\n", "lib/App.pm")
        assert "Foo::Bar" in result.imports
        assert "Baz::Qux" in result.imports

    def test_use_parent_base_imports(self, scanner: PerlScanner, force_heuristic):
        source = "use parent 'Foo::Bar';\nuse base qw(Baz::Qux);\n"
        result = scanner.outline(source, "lib/App.pm")
        assert "Foo::Bar" in result.imports
        assert "Baz::Qux" in result.imports

    def test_sub_params_from_my_unpack(self, scanner: PerlScanner, force_heuristic, force_no_astgrep):
        # FEAT-498: force_no_astgrep is required too — perl.yaml's
        # `function` rule (TASK-2745) reads a real signature node only
        # (matching perl.py's tree-sitter tier); the heuristic-only
        # `my ($self, $x) = @_` unpack fallback is not reproduced.
        source = "sub bar {\n    my ($self, $x) = @_;\n    return $x;\n}\n"
        result = scanner.outline(source, "lib/Foo.pm")
        assert any("$self" in line and "$x" in line for line in result.outline)

    def test_pragmas_and_versions_filtered_from_imports(self, scanner: PerlScanner, force_heuristic):
        source = (
            "use strict;\nuse warnings;\nuse v5.38;\nuse feature 'say';\n"
            "use 5.038;\nuse Moose;\nuse MyApp::Schema;\n"
        )
        result = scanner.outline(source, "lib/App.pm")
        assert "strict" not in result.imports
        assert "warnings" not in result.imports
        assert "v5" not in result.imports
        assert "feature" not in result.imports
        assert "5" not in result.imports
        assert "Moose" in result.imports
        assert "MyApp::Schema" in result.imports


# --- tree-sitter mode (skip if not installed) -------------------------------


@pytest.mark.skipif(not _TREESITTER_AVAILABLE, reason="tree-sitter-perl not installed")
class TestTreeSitter:
    def test_sub_declaration(self, scanner: PerlScanner):
        source = "package Foo;\nsub bar { }\n1;\n"
        result = scanner.outline(source, "lib/Foo.pm")
        assert any("sub bar" in line for line in result.outline)

    def test_corinna_class(self, scanner: PerlScanner, corinna_source: str):
        result = scanner.outline(corinna_source, "lib/Point.pm")
        assert any("class Point" in line for line in result.outline)
        assert any("method coordinates" in line for line in result.outline)
        assert any("field $x" in line for line in result.outline)

    def test_moose_has(self, scanner: PerlScanner, moose_source: str):
        result = scanner.outline(moose_source, "lib/MyApp/Model/User.pm")
        assert any("has name" in line for line in result.outline)
        assert any("has email" in line for line in result.outline)

    def test_multiple_packages(self, scanner: PerlScanner, multi_package_source: str):
        result = scanner.outline(multi_package_source, "lib/Multi.pm")
        assert "package Foo" in result.outline
        assert "package Bar" in result.outline

    def test_pod_summary(self, scanner: PerlScanner, pod_source: str):
        result = scanner.outline(pod_source, "lib/MyApp/Utils.pm")
        assert "MyApp::Utils" in result.summary

    def test_mode_is_tree_sitter(self, scanner: PerlScanner):
        assert scanner.mode == "tree-sitter"


def test_mode_is_heuristic_without_grammar(force_heuristic):
    assert PerlScanner().mode == "heuristic"


def test_heuristic_mode_forced(scanner: PerlScanner, moose_source: str, monkeypatch):
    monkeypatch.setattr(treesitter, "get_parser", lambda language: None)
    result = scanner.outline(moose_source, "lib/MyApp/Model/User.pm")
    assert any("sub validate" in line for line in result.outline)


# --- Import resolution -------------------------------------------------------


class TestImportResolution:
    def test_resolve_module_name(self, scanner: PerlScanner, repo_paths: list[str]):
        index = scanner.build_reference_index(repo_paths)
        resolved = scanner.resolve_import("MyApp::Schema", "lib/MyApp/Model/User.pm", index)
        assert resolved == "lib/MyApp/Schema.pm"

    def test_resolve_in_lib_dir(self, scanner: PerlScanner, repo_paths: list[str]):
        index = scanner.build_reference_index(repo_paths)
        resolved = scanner.resolve_import("MyApp::Controller::Auth", "lib/MyApp/Model/User.pm", index)
        assert resolved == "lib/MyApp/Controller/Auth.pm"

    def test_resolve_unresolvable(self, scanner: PerlScanner, repo_paths: list[str]):
        index = scanner.build_reference_index(repo_paths)
        resolved = scanner.resolve_import("Some::CPAN::Module", "lib/MyApp/Model/User.pm", index)
        assert resolved is None

    def test_resolve_relative_require(self, scanner: PerlScanner):
        index = scanner.build_reference_index(["bin/lib.pl", "bin/app.pl"])
        resolved = scanner.resolve_import("require:./lib.pl", "bin/app.pl", index)
        assert resolved == "bin/lib.pl"

    def test_build_reference_index(self, scanner: PerlScanner, repo_paths: list[str]):
        file_set, lib_dirs = scanner.build_reference_index(repo_paths)
        assert "lib/MyApp/Model/User.pm" in file_set
        assert "bin/app.pl" in file_set
        assert "t/model_user.t" in file_set
        assert "lib" in lib_dirs


# --- Safety contract ----------------------------------------------------------


class TestSafety:
    def test_never_raises_garbage(self, scanner: PerlScanner):
        result = scanner.outline("{{{{garbage not perl at all", "test.pl")
        assert isinstance(result, LanguageOutline)

    def test_never_raises_empty(self, scanner: PerlScanner):
        result = scanner.outline("", "empty.pl")
        assert isinstance(result, LanguageOutline)
        assert result.outline == []

    def test_never_raises_binary(self, scanner: PerlScanner):
        garbage = bytes(range(256)).decode("latin-1")
        result = scanner.outline(garbage, "binary.pl")
        assert isinstance(result, LanguageOutline)

    def test_outline_failure_degrades_empty(self, scanner: PerlScanner, monkeypatch, force_no_astgrep):
        # FEAT-498: force_no_astgrep is required too now that perl.yaml
        # (TASK-2745) makes the ast-grep seam a real, working first tier.
        def _boom(source: str) -> tuple[str, list[str]]:
            raise RuntimeError("boom")

        monkeypatch.setattr(scanner, "_outline_heuristic", _boom)
        monkeypatch.setattr(treesitter, "get_parser", lambda language: None)
        result = scanner.outline("package Foo;\n", "lib/Foo.pm")
        assert result.summary == ""
        assert result.outline == []
        assert result.imports == []
