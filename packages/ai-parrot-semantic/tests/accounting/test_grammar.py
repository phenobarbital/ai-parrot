"""FEAT-713 M3 — closed metric grammar."""

from __future__ import annotations

from decimal import Decimal

import pytest

from parrot.semantic.accounting.errors import GrammarError
from parrot.semantic.accounting.grammar import BinOp, Neg, Num, Ref, Sum, parse_assertion, parse_expr, references


def test_grammar_accepts_closed_language() -> None:
    assert parse_expr("sum(revenue) - sum(cogs)") == BinOp("-", Sum("revenue"), Sum("cogs"))
    assert parse_expr("a + b * c") == BinOp("+", Ref("a"), BinOp("*", Ref("b"), Ref("c")))
    assert parse_expr("(a + b) * c") == BinOp("*", BinOp("+", Ref("a"), Ref("b")), Ref("c"))
    assert parse_expr("a - b - c") == BinOp("-", BinOp("-", Ref("a"), Ref("b")), Ref("c"))
    assert parse_expr("-a * b") == BinOp("*", Neg(Ref("a")), Ref("b"))
    assert parse_expr("a / 0.5") == BinOp("/", Ref("a"), Num(Decimal("0.5")))
    assert parse_expr("12") == Num(Decimal("12"))
    assert parse_expr("sum") == Ref("sum")
    left, right = parse_assertion("sum(assets) == sum(liabilities) + sum(equity)")
    assert left == Sum("assets")
    assert right == BinOp("+", Sum("liabilities"), Sum("equity"))
    sets, metrics = references(parse_expr("sum(a) / (b - sum(c)) + -d + 1"))
    assert sets == frozenset({"a", "c"})
    assert metrics == frozenset({"b", "d"})


@pytest.mark.parametrize(
    "text", ["if(a)", "max(revenue)", "'x'", "a % b", "sum(a); drop", "select 1", "a ==", "a == b == c"]
)
def test_grammar_rejects_everything_else(text: str) -> None:
    with pytest.raises(GrammarError) as info:
        parse_assertion(text)
    assert isinstance(info.value.position, int)
    if "==" not in text:
        with pytest.raises(GrammarError) as info2:
            parse_expr(text)
        assert isinstance(info2.value.position, int)
    else:
        with pytest.raises(GrammarError):
            parse_expr(text)


def test_grammar_error_positions() -> None:
    with pytest.raises(GrammarError) as info:
        parse_expr("a % b")
    assert info.value.position == 2
