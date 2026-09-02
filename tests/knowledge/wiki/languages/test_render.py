"""Unit tests for the FEAT-498 byte-parity outline renderer (TASK-2740)."""

from __future__ import annotations

from parrot.knowledge.wiki.languages.render import render_outline
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord


def _sym(**overrides) -> SymbolRecord:
    defaults = {
        "rel_path": "a.txt",
        "language": "x",
        "kind": SymbolKind.FUNCTION,
        "name": "f",
        "qualname": "f",
        "start_line": 1,
        "end_line": 1,
        "start_byte": 0,
        "end_byte": 1,
        "content_hash": "deadbeef",
    }
    defaults.update(overrides)
    return SymbolRecord(**defaults)


class TestRenderPhp:
    def test_class_with_doc(self):
        sym = _sym(kind=SymbolKind.CLASS, name="Foo", doc="A foo.", start_byte=0)
        assert render_outline([sym], "php") == ["class Foo: A foo."]

    def test_class_without_doc_rstrips_colon(self):
        sym = _sym(kind=SymbolKind.CLASS, name="Foo", doc="", start_byte=0)
        assert render_outline([sym], "php") == ["class Foo"]

    def test_method_indented(self):
        sym = _sym(kind=SymbolKind.METHOD, name="bar", signature="int $x", doc="Bar.", parent="Foo", start_byte=5)
        assert render_outline([sym], "php") == ["    def bar(int $x): Bar."]

    def test_function_top_level(self):
        sym = _sym(kind=SymbolKind.FUNCTION, name="baz", signature="", doc="", start_byte=0)
        assert render_outline([sym], "php") == ["function baz()"]

    def test_container_before_member_source_order(self):
        cls = _sym(kind=SymbolKind.CLASS, name="Foo", doc="", start_byte=0)
        method = _sym(kind=SymbolKind.METHOD, name="bar", signature="", doc="", parent="Foo", start_byte=10)
        assert render_outline([method, cls], "php") == ["class Foo", "    def bar()"]


class TestRenderRust:
    def test_pub_struct_rendered(self):
        sym = _sym(kind=SymbolKind.STRUCT, name="Foo", doc="Doc.", exported=True, start_byte=0)
        assert render_outline([sym], "rust") == ["pub struct Foo: Doc."]

    def test_private_struct_not_rendered(self):
        sym = _sym(kind=SymbolKind.STRUCT, name="Foo", doc="", exported=False, start_byte=0)
        assert render_outline([sym], "rust") == []

    def test_pub_mod(self):
        sym = _sym(kind=SymbolKind.MOD, name="util", exported=True, start_byte=0)
        assert render_outline([sym], "rust") == ["pub mod util"]

    def test_impl_header_and_member_fn_regardless_of_pub(self):
        impl = _sym(kind=SymbolKind.IMPL, name="Foo", start_byte=0)
        fn = _sym(
            kind=SymbolKind.FUNCTION, name="new", signature="", doc="", parent="Foo", exported=False, start_byte=5
        )
        assert render_outline([impl, fn], "rust") == ["impl Foo:", "    pub fn new()"]

    def test_top_level_fn_requires_pub(self):
        fn = _sym(kind=SymbolKind.FUNCTION, name="helper", signature="", doc="", exported=False, start_byte=0)
        assert render_outline([fn], "rust") == []
        pub_fn = _sym(
            kind=SymbolKind.FUNCTION, name="helper", signature="a: u32", doc="Doc.", exported=True, start_byte=0
        )
        assert render_outline([pub_fn], "rust") == ["pub fn helper(a: u32): Doc."]


class TestRenderJavaScript:
    def test_exported_class(self):
        sym = _sym(kind=SymbolKind.CLASS, name="Foo", doc="Doc.", exported=True, start_byte=0)
        assert render_outline([sym], "javascript") == ["export class Foo: Doc."]

    def test_non_exported_function(self):
        sym = _sym(kind=SymbolKind.FUNCTION, name="helper", doc="", exported=False, start_byte=0)
        assert render_outline([sym], "javascript") == ["function helper"]

    def test_const(self):
        sym = _sym(kind=SymbolKind.CONST, name="LABEL", doc="", exported=True, start_byte=0)
        assert render_outline([sym], "javascript") == ["export const LABEL"]

    def test_method_never_rendered(self):
        sym = _sym(kind=SymbolKind.METHOD, name="bar", parent="Foo", start_byte=5)
        assert render_outline([sym], "javascript") == []

    def test_typescript_and_tsx_use_same_renderer(self):
        sym = _sym(kind=SymbolKind.INTERFACE, name="Foo", doc="", exported=False, start_byte=0)
        assert render_outline([sym], "typescript") == ["interface Foo"]
        assert render_outline([sym], "tsx") == ["interface Foo"]


class TestRenderPerl:
    def test_package(self):
        sym = _sym(kind=SymbolKind.PACKAGE, name="Foo::Bar", start_byte=0)
        assert render_outline([sym], "perl") == ["package Foo::Bar"]

    def test_class_and_role(self):
        cls = _sym(kind=SymbolKind.CLASS, name="Foo", doc="Doc.", start_byte=0)
        role = _sym(kind=SymbolKind.ROLE, name="Bar", doc="", start_byte=1)
        assert render_outline([cls, role], "perl") == ["class Foo: Doc.", "role Bar"]

    def test_sub_indented_under_package(self):
        sym = _sym(kind=SymbolKind.FUNCTION, name="bar", signature="", doc="", parent="Foo", start_byte=5)
        assert render_outline([sym], "perl") == ["    sub bar()"]

    def test_sub_top_level_no_indent(self):
        sym = _sym(kind=SymbolKind.FUNCTION, name="bar", signature="", doc="", parent=None, start_byte=0)
        assert render_outline([sym], "perl") == ["sub bar()"]

    def test_method_always_indented(self):
        sym = _sym(kind=SymbolKind.METHOD, name="bar", signature="", doc="Doc.", parent="Foo", start_byte=5)
        assert render_outline([sym], "perl") == ["    method bar(): Doc."]

    def test_field(self):
        sym = _sym(kind=SymbolKind.FIELD, name="$x", start_byte=5)
        assert render_outline([sym], "perl") == ["    field $x"]

    def test_attribute_with_and_without_isa(self):
        plain = _sym(kind=SymbolKind.ATTRIBUTE, name="name", signature="", start_byte=5)
        assert render_outline([plain], "perl") == ["    has name"]
        typed = _sym(kind=SymbolKind.ATTRIBUTE, name="name", signature="Str", start_byte=5)
        assert render_outline([typed], "perl") == ["    has name: Str"]


def test_unknown_language_renders_nothing():
    sym = _sym(kind=SymbolKind.CLASS, name="Foo")
    assert render_outline([sym], "cobol") == []
