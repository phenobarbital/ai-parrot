"""Closed metric-expression grammar (FEAT-713 M3). Standard library only."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Union

from .errors import GrammarError


@dataclass(frozen=True)
class Sum:
    """``sum(set)`` — total of a named account set."""

    set_name: str


@dataclass(frozen=True)
class Ref:
    """Reference to another metric by name."""

    metric: str


@dataclass(frozen=True)
class Num:
    """Decimal literal."""

    value: Decimal


@dataclass(frozen=True)
class Neg:
    """Unary minus."""

    operand: "Expr"


@dataclass(frozen=True)
class BinOp:
    """Binary arithmetic operation."""

    op: Literal["+", "-", "*", "/"]
    left: "Expr"
    right: "Expr"


Expr = Union[Sum, Ref, Num, Neg, BinOp]

_TOKEN = re.compile(r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?P<op>==|[-+*/()]))")
_WS = re.compile(r"\s*")
_BP = {"+": 10, "-": 10, "*": 20, "/": 20}
_NEG_BP = 30


def _tokenize(text: str) -> list[tuple[str, str, int]]:
    """Return (kind, value, position) tokens plus a final ("end", "", len(text)).

    Raises:
        GrammarError: At the first character no token matches.
    """
    tokens: list[tuple[str, str, int]] = []
    pos = 0
    while True:
        pos = _WS.match(text, pos).end()  # type: ignore[union-attr]
        if pos >= len(text):
            break
        match = _TOKEN.match(text, pos)
        if match is None:
            raise GrammarError(f"Unexpected character {text[pos]!r}", pos)
        kind = match.lastgroup or ""
        tokens.append((kind, match.group(kind), match.start(kind)))
        pos = match.end()
    tokens.append(("end", "", len(text)))
    return tokens


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = _tokenize(text)
        self.index = 0

    def peek(self) -> tuple[str, str, int]:
        return self.tokens[self.index]

    def advance(self) -> tuple[str, str, int]:
        token = self.tokens[self.index]
        if token[0] != "end":
            self.index += 1
        return token

    def expect_op(self, value: str) -> None:
        kind, val, pos = self.advance()
        if kind != "op" or val != value:
            raise GrammarError(f"Expected {value!r}", pos)

    def expect_end(self) -> None:
        kind, val, pos = self.peek()
        if kind != "end":
            raise GrammarError(f"Unexpected token {val!r}", pos)

    def expr(self, min_bp: int = 0) -> Expr:
        """Pratt loop: binding power 10 for + -, 20 for * /; unary minus binds tighter than * /."""
        kind, val, pos = self.advance()
        left: Expr
        if kind == "num":
            left = Num(Decimal(val))
        elif kind == "name":
            nxt = self.peek()
            if val == "sum" and nxt[0] == "op" and nxt[1] == "(":
                self.advance()
                set_kind, set_name, set_pos = self.advance()
                if set_kind != "name":
                    raise GrammarError("Expected a set name", set_pos)
                self.expect_op(")")
                left = Sum(set_name)
            else:
                left = Ref(val)
        elif kind == "op" and val == "(":
            left = self.expr(0)
            self.expect_op(")")
        elif kind == "op" and val == "-":
            left = Neg(self.expr(_NEG_BP))
        else:
            raise GrammarError("Unexpected token" if kind != "end" else "Unexpected end of expression", pos)
        while True:
            kind, val, pos = self.peek()
            if kind != "op" or val not in _BP:
                break
            bp = _BP[val]
            if bp <= min_bp:
                break
            self.advance()
            right = self.expr(bp)
            left = BinOp(val, left, right)  # type: ignore[arg-type]
        return left


def parse_expr(text: str) -> Expr:
    """Parse a metric expression; raise GrammarError(position) on any token outside the grammar."""
    parser = _Parser(text)
    result = parser.expr()
    parser.expect_end()
    return result


def parse_assertion(text: str) -> tuple[Expr, Expr]:
    """Parse ``<expr> == <expr>``; raise GrammarError otherwise."""
    parser = _Parser(text)
    left = parser.expr()
    parser.expect_op("==")
    right = parser.expr()
    parser.expect_end()
    return left, right


def references(expr: Expr) -> tuple[frozenset[str], frozenset[str]]:
    """Return (set_names, metric_names) referenced by *expr*."""
    if isinstance(expr, Sum):
        return frozenset({expr.set_name}), frozenset()
    if isinstance(expr, Ref):
        return frozenset(), frozenset({expr.metric})
    if isinstance(expr, Num):
        return frozenset(), frozenset()
    if isinstance(expr, Neg):
        return references(expr.operand)
    ls, lm = references(expr.left)
    rs, rm = references(expr.right)
    return ls | rs, lm | rm
