"""Unit tests for the JS/TS language plugin (heuristic mode).

Tree-sitter mode is exercised only when the optional
``ai-parrot[wiki-languages]`` extra (and the ``tree_sitter_typescript``/
``tree_sitter_javascript`` grammar wheels) is installed, which varies by
environment — so every outline test uses the ``force_heuristic`` fixture
to be explicit and environment-independent. The few tests that need a
real grammar say so and skip when it is unavailable.
"""

from dataclasses import FrozenInstanceError

import pytest
from parrot.knowledge.wiki.languages import scanner_for, treesitter
from parrot.knowledge.wiki.languages.javascript import (
    JavaScriptScanner,
    JsIndex,
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


def test_jsts_imports_include_bare_specifiers():
    """Every specifier survives extraction as of FEAT-396.

    Bare package names used to be dropped here; they now reach
    ``resolve_import``, which rejects them (see
    ``test_bare_package_still_unresolved``). Extraction cannot make that
    call itself — telling a repo alias from an npm package needs the
    per-scan alias map, which does not exist at this point.
    """
    scanner = JavaScriptScanner()
    result = scanner.outline(SAMPLE_TS, "src/services/user.ts")
    assert "./base/model" in result.imports
    assert "./utils" in result.imports
    assert "react" in result.imports


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


# ---------------------------------------------------------------------------
# FEAT-396 / TASK-2022 — alias-aware import resolution
# ---------------------------------------------------------------------------


class TestAliasResolution:
    """`$lib/...` and tsconfig `paths` resolve to repository files."""

    def test_alias_from_tsconfig_paths(self, tmp_path, restore_scan_root):
        """A declared `paths` entry expands, then extension-guesses."""
        (tmp_path / "tsconfig.json").write_text(
            '{"compilerOptions": {"baseUrl": ".", '
            '"paths": {"$lib/*": ["src/lib/*"]}}}'
        )
        (tmp_path / "src/lib").mkdir(parents=True)
        (tmp_path / "src/lib/util.ts").write_text("export function helper() {}\n")
        restore_scan_root(tmp_path)

        scanner = JavaScriptScanner()
        index = scanner.build_reference_index(
            ["tsconfig.json", "src/lib/util.ts", "src/lib/Widget.svelte"]
        )
        assert (
            scanner.resolve_import("$lib/util", "src/lib/Widget.svelte", index)
            == "src/lib/util.ts"
        )

    def test_alias_sveltekit_convention_fallback(
        self, svelte_repo, restore_scan_root
    ):
        """`$lib/` resolves with nothing declared but svelte.config.js.

        The motivating case: on a fresh clone the only `$lib` declaration
        lives in the generated, gitignored `.svelte-kit/tsconfig.json`.
        """
        restore_scan_root(svelte_repo)
        scanner = JavaScriptScanner()
        index = scanner.build_reference_index(
            ["svelte.config.js", "src/lib/util.ts", "src/lib/Widget.svelte"]
        )
        assert (
            scanner.resolve_import("$lib/util", "src/lib/Widget.svelte", index)
            == "src/lib/util.ts"
        )

    def test_alias_from_svelte_config_block(self, tmp_path, restore_scan_root):
        """An explicit `kit.alias` block is scraped, not evaluated."""
        (tmp_path / "svelte.config.js").write_text(
            "export default {\n"
            "  kit: {\n"
            "    alias: {\n"
            "      '$components': 'src/widgets',\n"
            "    }\n"
            "  }\n"
            "};\n"
        )
        (tmp_path / "src/widgets").mkdir(parents=True)
        (tmp_path / "src/widgets/Btn.ts").write_text("export const Btn = 1\n")
        restore_scan_root(tmp_path)

        scanner = JavaScriptScanner()
        index = scanner.build_reference_index(
            ["svelte.config.js", "src/widgets/Btn.ts"]
        )
        assert (
            scanner.resolve_import("$components/Btn", "src/routes/x.svelte", index)
            == "src/widgets/Btn.ts"
        )

    def test_alias_longest_prefix_wins(self, tmp_path, restore_scan_root):
        """`$lib/components/` beats `$lib/` when both are declared."""
        (tmp_path / "tsconfig.json").write_text(
            '{"compilerOptions": {"baseUrl": ".", "paths": {'
            '"$lib/*": ["src/lib/*"], '
            '"$lib/components/*": ["src/widgets/*"]}}}'
        )
        (tmp_path / "src/widgets").mkdir(parents=True)
        (tmp_path / "src/widgets/Btn.ts").write_text("export const Btn = 1\n")
        (tmp_path / "src/lib/components").mkdir(parents=True)
        (tmp_path / "src/lib/components/Btn.ts").write_text("export const X = 2\n")
        restore_scan_root(tmp_path)

        scanner = JavaScriptScanner()
        index = scanner.build_reference_index([
            "tsconfig.json", "src/widgets/Btn.ts", "src/lib/components/Btn.ts",
        ])
        assert index.aliases[0][0] == "$lib/components/"
        assert (
            scanner.resolve_import(
                "$lib/components/Btn", "src/routes/+page.svelte", index
            )
            == "src/widgets/Btn.ts"
        )

    def test_alias_falls_through_to_shorter_prefix(
        self, tmp_path, restore_scan_root
    ):
        """A more specific alias that expands to nothing must not shadow.

        `$lib/components/*` -> `src/widgets/*` is the longest match for
        `$lib/components/Btn`, but no such file exists; the broader
        `$lib/*` -> `src/lib/*` does resolve and must still be tried.
        """
        (tmp_path / "tsconfig.json").write_text(
            '{"compilerOptions": {"baseUrl": ".", "paths": {'
            '"$lib/*": ["src/lib/*"], '
            '"$lib/components/*": ["src/widgets/*"]}}}'
        )
        (tmp_path / "src/widgets").mkdir(parents=True)
        (tmp_path / "src/widgets/Other.ts").write_text("export const O = 1\n")
        (tmp_path / "src/lib/components").mkdir(parents=True)
        (tmp_path / "src/lib/components/Btn.ts").write_text("export const B = 2\n")
        restore_scan_root(tmp_path)

        scanner = JavaScriptScanner()
        index = scanner.build_reference_index([
            "tsconfig.json", "src/widgets/Other.ts", "src/lib/components/Btn.ts",
        ])
        # The longest prefix is tried first and misses...
        assert index.aliases[0][0] == "$lib/components/"
        # ...but resolution falls through to `$lib/` rather than giving up.
        assert (
            scanner.resolve_import(
                "$lib/components/Btn", "src/routes/+page.svelte", index
            )
            == "src/lib/components/Btn.ts"
        )

    @pytest.mark.parametrize("spec", ["$app/environment", "$env/static/public"])
    def test_alias_unresolved_returns_none(
        self, svelte_repo, restore_scan_root, spec
    ):
        """SvelteKit virtual modules are dropped, not left dangling."""
        restore_scan_root(svelte_repo)
        scanner = JavaScriptScanner()
        index = scanner.build_reference_index(
            ["svelte.config.js", "src/lib/util.ts"]
        )
        assert scanner.resolve_import(spec, "src/lib/Widget.svelte", index) is None

    @pytest.mark.parametrize("spec", ["react", "lodash", "@sveltejs/kit"])
    def test_bare_package_still_unresolved(
        self, svelte_repo, restore_scan_root, spec
    ):
        """Bare packages now REACH resolve_import and must be rejected."""
        restore_scan_root(svelte_repo)
        scanner = JavaScriptScanner()
        index = scanner.build_reference_index(
            ["svelte.config.js", "src/lib/util.ts"]
        )
        assert scanner.resolve_import(spec, "src/lib/Widget.svelte", index) is None

    @pytest.mark.parametrize("rune", ["$state", "$derived", "$effect", "$props"])
    def test_svelte_runes_are_not_aliases(
        self, svelte_repo, restore_scan_root, rune
    ):
        """Svelte 5 runes are compiler intrinsics, never alias matches.

        Guaranteed structurally: every alias prefix ends in `/`, so a
        bare `$state` cannot prefix-match `$lib/`.
        """
        restore_scan_root(svelte_repo)
        scanner = JavaScriptScanner()
        index = scanner.build_reference_index(
            ["svelte.config.js", "src/lib/util.ts"]
        )
        assert all(prefix.endswith("/") for prefix, _ in index.aliases)
        assert scanner.resolve_import(rune, "src/lib/Widget.svelte", index) is None

    def test_malformed_tsconfig_degrades_to_convention(
        self, tmp_path, restore_scan_root
    ):
        """Comments/trailing commas are legal tsconfig but not stdlib json."""
        (tmp_path / "svelte.config.js").write_text("export default { kit: {} }\n")
        (tmp_path / "tsconfig.json").write_text(
            '{\n  // a comment stdlib json cannot parse\n'
            '  "compilerOptions": {"paths": {"$lib/*": ["nope/*"]},}\n}\n'
        )
        (tmp_path / "src/lib").mkdir(parents=True)
        (tmp_path / "src/lib/util.ts").write_text("export function helper() {}\n")
        restore_scan_root(tmp_path)

        scanner = JavaScriptScanner()
        index = scanner.build_reference_index(
            ["svelte.config.js", "tsconfig.json", "src/lib/util.ts"]
        )
        assert (
            scanner.resolve_import("$lib/util", "src/lib/Widget.svelte", index)
            == "src/lib/util.ts"
        )

    def test_no_scan_root_does_not_raise(self, restore_scan_root):
        """A scanner used outside a scan still builds a usable index."""
        restore_scan_root(None)
        scanner = JavaScriptScanner()
        index = scanner.build_reference_index(["src/a.ts", "src/b.ts"])
        assert isinstance(index, JsIndex)
        assert (
            scanner.resolve_import("./b", "src/a.ts", index) == "src/b.ts"
        )

    def test_relative_resolution_unchanged_by_alias_branch(
        self, restore_scan_root
    ):
        """The pre-existing relative path stays first and untouched."""
        restore_scan_root(None)
        scanner = JavaScriptScanner()
        index = scanner.build_reference_index(
            ["src/user.ts", "src/base/model.ts", "src/utils/index.ts"]
        )
        assert (
            scanner.resolve_import("./base/model", "src/user.ts", index)
            == "src/base/model.ts"
        )
        assert (
            scanner.resolve_import("./utils", "src/user.ts", index)
            == "src/utils/index.ts"
        )

    def test_index_is_hashable_and_frozen(self, restore_scan_root):
        """JsIndex keeps the frozenset's immutability guarantees."""
        restore_scan_root(None)
        index = JavaScriptScanner().build_reference_index(["a.ts"])
        assert hash(index) is not None
        with pytest.raises(FrozenInstanceError):
            index.files = frozenset()


# ---------------------------------------------------------------------------
# FEAT-396 / TASK-2023 — honest mode reporting
# ---------------------------------------------------------------------------


class TestModeReporting:
    """`mode` must not overstate what the outlines are worth."""

    @pytest.mark.parametrize(
        ("available", "expected"),
        [
            (("javascript",), "heuristic"),
            (("typescript",), "heuristic"),
            ((), "heuristic"),
            (("javascript", "typescript"), "tree-sitter"),
        ],
    )
    def test_mode_requires_both_grammars(self, monkeypatch, available, expected):
        """One grammar loading is not tree-sitter mode.

        Before FEAT-396 this was an `or`, and the JavaScript grammar
        always loaded — so TypeScript files were reported as tree-sitter
        while actually being parsed by regex.
        """
        monkeypatch.setattr(
            treesitter,
            "get_parser",
            lambda language: object() if language in available else None,
        )
        assert JavaScriptScanner().mode == expected
