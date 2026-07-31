"""Unit tests for the JS/TS language plugin (heuristic mode).

Tree-sitter mode is exercised only when the optional
``ai-parrot[wiki-languages]`` extra (and the ``tree_sitter_typescript``/
``tree_sitter_javascript`` grammar wheels) is installed — not the case in
this dev environment, so every outline test uses the ``force_heuristic``
fixture to be explicit and environment-independent.
"""

from parrot.knowledge.wiki.languages import scanner_for
from parrot.knowledge.wiki.languages.javascript import JavaScriptScanner

SAMPLE_TS = '''
import { Model } from './base/model';
import React from 'react';
export { helper } from './utils';

/**
 * Main service class.
 */
export class UserService {
    async getUser(id: string): Promise<User> { ... }
}

export interface UserConfig {
    name: string;
}

export type UserId = string;

export const DEFAULT_LIMIT = 10;

function internalHelper(): void { ... }
'''


def test_jsts_outline_exports(force_heuristic):
    scanner = JavaScriptScanner()
    result = scanner.outline(SAMPLE_TS, "src/services/user.ts")
    names = " ".join(result.outline)
    assert "UserService" in names
    assert "UserConfig" in names
    assert "UserId" in names
    assert "DEFAULT_LIMIT" in names


def test_jsts_export_class_prefixed(force_heuristic):
    scanner = JavaScriptScanner()
    result = scanner.outline(SAMPLE_TS, "src/services/user.ts")
    assert any(line.startswith("export class UserService") for line in result.outline)


def test_jsts_internal_function_not_export_prefixed(force_heuristic):
    scanner = JavaScriptScanner()
    result = scanner.outline(SAMPLE_TS, "src/services/user.ts")
    fn_lines = [line for line in result.outline if "internalHelper" in line]
    assert fn_lines
    assert fn_lines[0].startswith("function ")


def test_jsts_docblock_used_as_class_doc(force_heuristic):
    scanner = JavaScriptScanner()
    result = scanner.outline(SAMPLE_TS, "src/services/user.ts")
    assert any("Main service class." in line for line in result.outline)


def test_jsts_relative_resolution():
    # ``from_file`` sits directly in ``src/`` so "./base/model" and
    # "./utils" resolve relative to that directory — standard JS/TS
    # relative-import semantics (resolution is always relative to the
    # *importing file's own directory*, not some ancestor of it).
    scanner = JavaScriptScanner()
    rel_paths = ["src/user.ts", "src/base/model.ts", "src/utils/index.ts"]
    index = scanner.build_reference_index(rel_paths)
    assert (
        scanner.resolve_import("./base/model", "src/user.ts", index)
        == "src/base/model.ts"
    )
    assert (
        scanner.resolve_import("./utils", "src/user.ts", index)
        == "src/utils/index.ts"
    )
    assert scanner.resolve_import("react", "src/user.ts", index) is None


def test_jsts_parent_relative_resolution():
    scanner = JavaScriptScanner()
    rel_paths = ["src/services/nested/x.ts", "src/base/model.ts"]
    index = scanner.build_reference_index(rel_paths)
    target = scanner.resolve_import(
        "../../base/model", "src/services/nested/x.ts", index
    )
    assert target == "src/base/model.ts"


def test_jsts_imports_only_relative():
    scanner = JavaScriptScanner()
    result = scanner.outline(SAMPLE_TS, "src/services/user.ts")
    assert "./base/model" in result.imports
    assert "./utils" in result.imports
    assert "react" not in result.imports


def test_jsts_bare_package_resolves_to_none():
    scanner = JavaScriptScanner()
    rel_paths = ["src/services/user.ts"]
    index = scanner.build_reference_index(rel_paths)
    assert scanner.resolve_import("lodash", "src/services/user.ts", index) is None


def test_jsts_unresolvable_relative_returns_none():
    scanner = JavaScriptScanner()
    rel_paths = ["src/services/user.ts"]
    index = scanner.build_reference_index(rel_paths)
    result = scanner.resolve_import("./missing", "src/services/user.ts", index)
    assert result is None


def test_jsts_parse_failure_degrades_empty(force_heuristic, monkeypatch):
    scanner = JavaScriptScanner()

    def _boom(source):
        raise RuntimeError("boom")

    monkeypatch.setattr(scanner, "_outline_heuristic", _boom)
    result = scanner.outline("export class X {}", "x.ts")
    assert result.summary == ""
    assert result.outline == []
    assert result.imports == []


def test_scanner_for_all_jsts_suffixes():
    for suffix in (".js", ".jsx", ".mjs", ".ts", ".tsx"):
        assert isinstance(scanner_for(suffix), JavaScriptScanner)


def test_jsts_scanner_mode_is_heuristic_without_grammar(force_heuristic):
    assert JavaScriptScanner().mode == "heuristic"
