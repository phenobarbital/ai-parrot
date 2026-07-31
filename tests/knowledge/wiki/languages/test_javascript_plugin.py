"""Unit tests for the JS/TS language plugin (heuristic mode).

Tree-sitter mode is exercised only when the optional
``ai-parrot[wiki-languages]`` extra (and the ``tree_sitter_typescript``/
``tree_sitter_javascript`` grammar wheels) is installed, which varies by
environment — so every outline test uses the ``force_heuristic`` fixture
to be explicit and environment-independent. The few tests that need a
real grammar say so and skip when it is unavailable.
"""

import pytest
from parrot.knowledge.wiki.languages import scanner_for, treesitter
from parrot.knowledge.wiki.languages.javascript import (
    JavaScriptScanner,
    _extract_script_blocks,
    _grammar_for,
)

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


def test_jsts_multiline_import_extracted(force_heuristic):
    # Common Prettier/ESLint output style — the import specifier's
    # `from '...'` clause lands on its own line, well after `import`.
    source = (
        "import {\n"
        "    Model,\n"
        "    Config,\n"
        "} from './base/model';\n"
    )
    scanner = JavaScriptScanner()
    result = scanner.outline(source, "src/services/user.ts")
    assert "./base/model" in result.imports


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


# ---------------------------------------------------------------------------
# FEAT-396 / TASK-2021 — <script> pre-extraction + lang-aware grammar choice
# ---------------------------------------------------------------------------

SVELTE_TS = (
    '<script context="module" lang="ts">\n'
    "  export const prerender = true\n"
    "</script>\n"
    "\n"
    '<script lang="ts">\n'
    "  import { helper } from './util'\n"
    "\n"
    "  /**\n"
    "   * Renders a widget.\n"
    "   */\n"
    "  export function greet(name: string): string { return name }\n"
    "\n"
    "  export interface Props { label: string }\n"
    "</script>\n"
    "\n"
    '<div class="wrapper">{label}</div>\n'
)


class TestExtractScriptBlocks:
    """The pre-extraction seam itself, independent of any grammar."""

    def test_instance_and_module_blocks_concatenated(self):
        """Both blocks are kept; the surrounding markup is dropped."""
        body, lang = _extract_script_blocks(SVELTE_TS, ".svelte")
        assert "prerender" in body
        assert "greet" in body
        assert "wrapper" not in body, "markup must not leak into the body"
        assert "<div" not in body
        assert lang == "ts"

    @pytest.mark.parametrize(
        ("attributes", "expected"),
        [
            ('lang="ts"', "ts"),
            ("lang='ts'", "ts"),
            ('lang="typescript"', "typescript"),
            ('lang="TS"', "ts"),
            ("", None),
            ('context="module"', None),
        ],
    )
    def test_lang_variants(self, attributes, expected):
        """`lang` is read regardless of quoting/case; absent means None."""
        src = f"<script {attributes}>\nexport const a = 1\n</script>\n<p>hi</p>\n"
        _body, lang = _extract_script_blocks(src, ".svelte")
        assert lang == expected

    def test_lang_read_in_any_attribute_order(self):
        """`lang` need not be the first attribute."""
        src = (
            '<script context="module" lang="ts">\nexport const a = 1\n</script>\n'
        )
        assert _extract_script_blocks(src, ".svelte")[1] == "ts"

    def test_lookalike_attribute_not_mistaken_for_lang(self):
        """`data-lang=` is not `lang=`."""
        src = '<script data-lang="ts">\nexport const a = 1\n</script>\n'
        assert _extract_script_blocks(src, ".svelte")[1] is None

    def test_typescript_declaration_wins_over_undeclared_block(self):
        """A module block without `lang` must not demote a `ts` instance."""
        src = (
            "<script module>\nexport const prerender = true\n</script>\n"
            '<script lang="ts">\nexport const a: number = 1\n</script>\n'
        )
        assert _extract_script_blocks(src, ".svelte")[1] == "ts"

    def test_no_script_returns_empty_body(self):
        """A markup-only component yields an empty body, not an error."""
        assert _extract_script_blocks("<div>only markup</div>\n", ".svelte") == (
            "",
            None,
        )

    def test_self_closing_script_returns_empty_body(self):
        """`<script />` has no body and must not raise."""
        body, lang = _extract_script_blocks('<script src="x.js" />\n', ".svelte")
        assert body == ""
        assert lang is None

    def test_empty_script_block(self):
        """An empty block is a body of `""`, still a valid parse input."""
        body, _lang = _extract_script_blocks("<script></script>\n", ".svelte")
        assert body == ""

    @pytest.mark.parametrize("suffix", [".ts", ".tsx", ".js", ".jsx", ".mjs"])
    def test_non_svelte_passthrough_is_byte_identical(self, suffix):
        """Non-component suffixes are returned untouched."""
        src = "export const a = 1\n<script>not markup</script>\n"
        assert _extract_script_blocks(src, suffix) == (src, None)


class TestGrammarSelection:
    """`.svelte` selects on `lang`; every other suffix on the suffix."""

    @pytest.mark.parametrize(
        ("suffix", "lang", "expected"),
        [
            (".svelte", "ts", "typescript"),
            (".svelte", "typescript", "typescript"),
            (".svelte", None, "javascript"),
            (".svelte", "js", "javascript"),
            # Unchanged suffix rule for everything else.
            (".ts", None, "typescript"),
            (".tsx", None, "typescript"),
            (".js", None, "javascript"),
            (".jsx", None, "javascript"),
            (".mjs", None, "javascript"),
        ],
    )
    def test_grammar_for(self, suffix, lang, expected):
        assert _grammar_for(suffix, lang) == expected


class TestSvelteOutline:
    """End-to-end `outline()` behaviour on components."""

    def test_svelte_outline_exports(self, force_heuristic):
        """Symbols inside `<script lang="ts">` reach the outline."""
        result = JavaScriptScanner().outline(SVELTE_TS, "src/lib/Widget.svelte")
        assert result.outline, "a scripted component must not be empty"
        rendered = " ".join(result.outline)
        assert "greet" in rendered
        assert "Props" in rendered
        assert "prerender" in rendered, "the module block must be included too"

    def test_svelte_summary_is_not_script_tag(self, force_heuristic):
        """The summary is never the literal `<script …>` line."""
        result = JavaScriptScanner().outline(SVELTE_TS, "src/lib/Widget.svelte")
        assert "<script" not in result.summary
        assert "lang=" not in result.summary

    def test_svelte_outline_via_treesitter(self):
        """Same guarantee on the real grammar path, when available."""
        if treesitter.get_parser("typescript") is None:
            pytest.skip("typescript grammar not available")
        result = JavaScriptScanner().outline(SVELTE_TS, "src/lib/Widget.svelte")
        assert result.outline
        assert "<script" not in result.summary
        rendered = " ".join(result.outline)
        assert "greet" in rendered

    def test_svelte_no_script_degrades_without_raising(self, force_heuristic):
        """Markup-only component: empty outline, no exception."""
        result = JavaScriptScanner().outline(
            "<div>only markup</div>\n", "src/lib/Plain.svelte"
        )
        assert result.outline == []
        assert result.summary == ""

    def test_svelte_imports_still_from_raw_source(self, force_heuristic):
        """Imports keep coming from the raw file, per TASK-2020's guarantee."""
        result = JavaScriptScanner().outline(SVELTE_TS, "src/lib/Widget.svelte")
        assert "./util" in result.imports

    def test_jsts_outline_unchanged_by_the_seam(self, force_heuristic):
        """A `.ts` file is unaffected: same symbols as before FEAT-396."""
        result = JavaScriptScanner().outline(SAMPLE_TS, "src/services/user.ts")
        names = " ".join(result.outline)
        assert "UserService" in names
        assert "UserConfig" in names
        assert "DEFAULT_LIMIT" in names

    def test_scanner_for_svelte(self):
        assert isinstance(scanner_for(".svelte"), JavaScriptScanner)
