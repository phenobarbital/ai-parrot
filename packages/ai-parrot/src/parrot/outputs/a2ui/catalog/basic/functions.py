"""A2UI v1.0 Basic Catalog — renderer-side ``FunctionEvaluator`` (TASK-2537).

Implements the 14 official Basic Catalog functions
(``required``/``regex``/``length``/``numeric``/``email`` -> ``ValidationResult``;
``formatString``/``formatNumber``/``formatCurrency``/``formatDate``/``pluralize``
-> ``str``; ``and``/``or``/``not`` -> ``bool``; ``openUrl`` -> no-op agent-side,
marked ``requiresUserActivation``), plus a hand-rolled ``${...}`` tokenizer for
``format_string`` (JSON-Pointer paths, named-arg function calls, ``\\${`` escape)
and the ``@index`` template-scope system function.

Deliberately contains NO ``eval``/``exec`` (``test_no_exec.py``) — every
expression is parsed with manual, balanced-delimiter scanning (no recursive
regex either).

One-way import rule (G8): this module MUST NEVER import from
``parrot.bots``, ``parrot.clients``, agents, or DatasetManager.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from parrot.outputs.a2ui.catalog.base import (
    INVALID_FUNCTION_CALL,
    CatalogValidationError,
)
from parrot.outputs.a2ui.models import (
    CheckRule,
    DataBinding,
    FunctionCall,
    ValidationResult,
)

__all__ = ["FunctionEvaluator"]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

#: Minimal ISO-4217 -> symbol map (Does NOT Exist: no locale/babel dependency).
_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}

#: TR35-lite pattern tokens -> ``strftime`` directives, longest-match-first.
_DATE_TOKENS: list[tuple[str, str]] = [
    ("yyyy", "%Y"),
    ("yy", "%y"),
    ("MMMM", "%B"),
    ("MMM", "%b"),
    ("MM", "%m"),
    ("dd", "%d"),
    ("EEEE", "%A"),
    ("E", "%a"),
    ("HH", "%H"),
    ("hh", "%I"),
    ("mm", "%M"),
    ("ss", "%S"),
    ("a", "%p"),
]


class FunctionEvaluator:
    """Pure, deterministic evaluator for the Basic Catalog's 14 functions.

    Stateless — safe to share a single instance. All methods are pure
    functions of their arguments (no I/O, no ``eval``/``exec``).
    """

    def __init__(self) -> None:
        self._handlers = {
            "required": self._required,
            "regex": self._regex,
            "length": self._length,
            "numeric": self._numeric,
            "email": self._email,
            "formatNumber": self._format_number,
            "formatCurrency": self._format_currency,
            "formatDate": self._format_date,
            "pluralize": self._pluralize,
            "openUrl": self._open_url,
            "and": self._and,
            "or": self._or,
            "not": self._not,
        }

    # -- Public API ---------------------------------------------------------

    def evaluate(
        self,
        call: FunctionCall,
        *,
        data_model: dict[str, Any],
        scope_path: str = "",
        index: int | None = None,
    ) -> Any:
        """Evaluate a :class:`FunctionCall` (renderer-side functions + ``@index``).

        Args:
            call: The function call to evaluate. ``call.args`` values may be
                literals, ``{"path": ...}`` (:class:`DataBinding`-shaped), or
                ``{"call": ...}`` (nested :class:`FunctionCall`-shaped) — all
                are resolved before dispatch.
            data_model: The surface data model.
            scope_path: The JSON Pointer of the current template item (for
                resolving relative paths and ``@index``'s scope).
            index: The current 0-based template index, if evaluating inside a
                ``ChildTemplate`` expansion. ``None`` outside template scope.

        Returns:
            A :class:`ValidationResult` (validators), ``str`` (format
            functions), ``bool`` (boolean functions), an ``int`` (``@index``),
            or ``None`` (``openUrl``).

        Raises:
            CatalogValidationError: (code ``INVALID_FUNCTION_CALL``) for an
                unknown function, or ``@index`` used outside template scope.
        """
        args = {
            key: self._resolve_arg_value(value, data_model=data_model, scope_path=scope_path, index=index)
            for key, value in call.args.items()
        }

        if call.call == "@index":
            if index is None:
                raise CatalogValidationError(
                    "'@index' may only be used when evaluating a ChildTemplate " "item (template scope).",
                    code=INVALID_FUNCTION_CALL,
                )
            return index + args.get("offset", 0)

        if call.call == "formatString":
            return self.format_string(
                str(args.get("value", "")),
                data_model=data_model,
                scope_path=scope_path,
                index=index,
            )

        handler = self._handlers.get(call.call)
        if handler is None:
            raise CatalogValidationError(
                f"Unknown or invalid function call {call.call!r}.",
                code=INVALID_FUNCTION_CALL,
            )
        return handler(args)

    def format_string(
        self,
        template: str,
        *,
        data_model: dict[str, Any],
        scope_path: str = "",
        index: int | None = None,
    ) -> str:
        """Interpolate ``${...}`` expressions in ``template`` (spec §2 ``formatString``).

        Supports JSON Pointer paths (``${/absolute/path}``, ``${relative/path}``,
        resolved against ``scope_path``), named-arg function calls
        (``${formatDate(value:${/d}, format:'MM-dd')}``), ``@index``, and the
        ``\\${`` escape for a literal ``${``.

        Args:
            template: The template string.
            data_model: The surface data model.
            scope_path: The JSON Pointer of the current template item.
            index: The current 0-based template index, if any.

        Returns:
            The interpolated string.
        """
        out: list[str] = []
        i = 0
        n = len(template)
        while i < n:
            if template[i] == "\\" and template[i : i + 3] == "\\${":
                out.append("${")
                i += 3
                continue
            if template[i] == "$" and i + 1 < n and template[i + 1] == "{":
                end = self._find_matching_brace(template, i + 1)
                expr = template[i + 2 : end]
                value = self._eval_expr(expr, data_model=data_model, scope_path=scope_path, index=index)
                out.append(self._stringify(value))
                i = end + 1
                continue
            out.append(template[i])
            i += 1
        return "".join(out)

    def check(
        self,
        rule: CheckRule,
        *,
        data_model: dict[str, Any],
        scope_path: str = "",
        index: int | None = None,
    ) -> ValidationResult:
        """Evaluate a :class:`CheckRule` condition to a :class:`ValidationResult`.

        Args:
            rule: The check rule (``condition`` is a ``FunctionCall`` or a
                ``DataBinding`` pointing at an already-computed result).
            data_model: The surface data model.
            scope_path: The JSON Pointer of the current template item.
            index: The current 0-based template index, if any.

        Returns:
            The :class:`ValidationResult`. If invalid and the result carries
            no ``message`` but ``rule.message`` is set, that fallback is used.
        """
        if isinstance(rule.condition, DataBinding):
            raw = self._resolve_pointer(rule.condition.path, data_model)
            result = raw if isinstance(raw, ValidationResult) else ValidationResult.model_validate(raw)
        else:
            result = self.evaluate(rule.condition, data_model=data_model, scope_path=scope_path, index=index)
            if not isinstance(result, ValidationResult):
                raise CatalogValidationError(
                    f"CheckRule condition {rule.condition.call!r} did not return a " "ValidationResult.",
                    code=INVALID_FUNCTION_CALL,
                )
        if not result.valid and not result.message and rule.message:
            result = result.model_copy(update={"message": rule.message})
        return result

    # -- ${...} tokenizer (manual, balanced-delimiter — no eval/regex-recursion) --

    @staticmethod
    def _find_matching_brace(s: str, open_index: int) -> int:
        """Return the index of the ``}`` matching ``s[open_index] == '{'``."""
        depth = 1
        i = open_index + 1
        in_string = False
        while i < len(s):
            c = s[i]
            if in_string:
                if c == "'":
                    in_string = False
            elif c == "'":
                in_string = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        raise ValueError(f"Unterminated '{{' in expression: {s!r}")

    @staticmethod
    def _find_matching_paren(s: str, open_index: int) -> int:
        """Return the index of the ``)`` matching ``s[open_index] == '('``.

        Skips over nested ``${...}`` spans wholesale (their own parens are
        resolved when THEY are evaluated, not while scanning for this one).
        """
        depth = 1
        i = open_index + 1
        in_string = False
        while i < len(s):
            c = s[i]
            if in_string:
                if c == "'":
                    in_string = False
                i += 1
                continue
            if c == "'":
                in_string = True
                i += 1
                continue
            if c == "$" and i + 1 < len(s) and s[i + 1] == "{":
                i = FunctionEvaluator._find_matching_brace(s, i + 1) + 1
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        raise ValueError(f"Unterminated '(' in expression: {s!r}")

    @staticmethod
    def _split_top_level(s: str, sep: str = ",") -> list[str]:
        """Split ``s`` on ``sep`` at depth 0, skipping quotes/parens/``${...}``."""
        parts: list[str] = []
        current: list[str] = []
        depth = 0
        in_string = False
        i = 0
        while i < len(s):
            c = s[i]
            if in_string:
                current.append(c)
                if c == "'":
                    in_string = False
                i += 1
                continue
            if c == "'":
                in_string = True
                current.append(c)
                i += 1
                continue
            if c == "$" and i + 1 < len(s) and s[i + 1] == "{":
                end = FunctionEvaluator._find_matching_brace(s, i + 1)
                current.append(s[i : end + 1])
                i = end + 1
                continue
            if c == "(":
                depth += 1
                current.append(c)
                i += 1
                continue
            if c == ")":
                depth -= 1
                current.append(c)
                i += 1
                continue
            if c == sep and depth == 0:
                parts.append("".join(current))
                current = []
                i += 1
                continue
            current.append(c)
            i += 1
        if current or parts:
            parts.append("".join(current))
        return [p for p in parts if p.strip()]

    def _eval_expr(self, expr: str, *, data_model: dict[str, Any], scope_path: str, index: int | None) -> Any:
        """Evaluate the content of one ``${...}`` (path, function call, or ``@index``)."""
        expr = expr.strip()
        if expr == "@index" or expr.startswith("@index("):
            return self._eval_index_expr(expr, index=index)

        paren = expr.find("(")
        if paren != -1 and expr.endswith(")"):
            name = expr[:paren]
            close = self._find_matching_paren(expr, paren)
            if close != len(expr) - 1:
                raise ValueError(f"Malformed function call expression: {expr!r}")
            args = self._parse_named_args(
                expr[paren + 1 : close],
                data_model=data_model,
                scope_path=scope_path,
                index=index,
            )
            return self.evaluate(
                FunctionCall(call=name, args=args),
                data_model=data_model,
                scope_path=scope_path,
                index=index,
            )

        pointer = self._resolve_scoped_pointer(expr, scope_path)
        return self._resolve_pointer(pointer, data_model)

    def _eval_index_expr(self, expr: str, *, index: int | None) -> int:
        if index is None:
            raise CatalogValidationError(
                "'@index' may only be used when evaluating a ChildTemplate " "item (template scope).",
                code=INVALID_FUNCTION_CALL,
            )
        if expr == "@index":
            return index
        paren = expr.index("(")
        close = self._find_matching_paren(expr, paren)
        args = self._parse_named_args(expr[paren + 1 : close], data_model={}, scope_path="", index=index)
        return index + int(args.get("offset", 0))

    def _parse_named_args(
        self, args_str: str, *, data_model: dict[str, Any], scope_path: str, index: int | None
    ) -> dict[str, Any]:
        args: dict[str, Any] = {}
        for part in self._split_top_level(args_str):
            name, _, raw_value = part.partition(":")
            name = name.strip()
            raw_value = raw_value.strip()
            args[name] = self._parse_arg_value(raw_value, data_model=data_model, scope_path=scope_path, index=index)
        return args

    def _parse_arg_value(self, raw: str, *, data_model: dict[str, Any], scope_path: str, index: int | None) -> Any:
        if len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
            return raw[1:-1]
        if raw.startswith("${") and raw.endswith("}"):
            return self._eval_expr(raw[2:-1], data_model=data_model, scope_path=scope_path, index=index)
        if raw in ("true", "false"):
            return raw == "true"
        try:
            return int(raw)
        except ValueError:
            pass
        try:
            return float(raw)
        except ValueError:
            pass
        return raw

    @staticmethod
    def _resolve_scoped_pointer(expr: str, scope_path: str) -> str:
        if expr.startswith("/"):
            return expr
        base = scope_path.rstrip("/")
        return f"{base}/{expr}" if base else f"/{expr}"

    def _resolve_pointer(self, pointer: str, data_model: dict[str, Any]) -> Any:
        if pointer in ("", "/"):
            return data_model
        if not pointer.startswith("/"):
            raise ValueError(f"Not a well-formed JSON Pointer: {pointer!r}")
        node: Any = data_model
        for raw_token in pointer.split("/")[1:]:
            token = raw_token.replace("~1", "/").replace("~0", "~")
            if isinstance(node, list):
                node = node[int(token)]
            elif isinstance(node, dict):
                if token not in node:
                    raise KeyError(f"Pointer {pointer!r}: {token!r} not found in data model.")
                node = node[token]
            else:
                raise KeyError(f"Cannot resolve pointer {pointer!r}: intermediate value is not a dict/list.")
        return node

    def _resolve_arg_value(self, value: Any, *, data_model: dict[str, Any], scope_path: str, index: int | None) -> Any:
        """Resolve a wire ``FunctionCall.args`` value (literal, binding, or nested call)."""
        if isinstance(value, dict) and "call" in value:
            return self.evaluate(
                FunctionCall.model_validate(value),
                data_model=data_model,
                scope_path=scope_path,
                index=index,
            )
        if isinstance(value, dict) and set(value) == {"path"}:
            return self._resolve_pointer(value["path"], data_model)
        if isinstance(value, list):
            return [
                self._resolve_arg_value(item, data_model=data_model, scope_path=scope_path, index=index)
                for item in value
            ]
        return value

    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    # -- The 14 official Basic Catalog functions -----------------------------

    @staticmethod
    def _required(args: dict[str, Any]) -> ValidationResult:
        value = args.get("value")
        empty = value is None or (isinstance(value, (str, list, dict)) and len(value) == 0)
        return ValidationResult(
            valid=not empty,
            code=None if not empty else "REQUIRED",
            message=None if not empty else "This value is required.",
        )

    @staticmethod
    def _regex(args: dict[str, Any]) -> ValidationResult:
        value = str(args.get("value", ""))
        pattern = args["pattern"]
        valid = re.search(pattern, value) is not None
        return ValidationResult(
            valid=valid,
            code=None if valid else "PATTERN_MISMATCH",
            message=None if valid else f"Value does not match pattern {pattern!r}.",
        )

    @staticmethod
    def _length(args: dict[str, Any]) -> ValidationResult:
        value = str(args.get("value", ""))
        min_len = args.get("min")
        max_len = args.get("max")
        valid = (min_len is None or len(value) >= min_len) and (max_len is None or len(value) <= max_len)
        return ValidationResult(
            valid=valid,
            code=None if valid else "LENGTH_OUT_OF_RANGE",
            message=None if valid else f"Length must be within [{min_len}, {max_len}].",
        )

    @staticmethod
    def _numeric(args: dict[str, Any]) -> ValidationResult:
        value = args.get("value")
        min_value = args.get("min")
        max_value = args.get("max")
        valid = (min_value is None or value >= min_value) and (max_value is None or value <= max_value)
        return ValidationResult(
            valid=valid,
            code=None if valid else "NUMERIC_OUT_OF_RANGE",
            message=None if valid else f"Value must be within [{min_value}, {max_value}].",
        )

    @staticmethod
    def _email(args: dict[str, Any]) -> ValidationResult:
        value = str(args.get("value", ""))
        valid = bool(_EMAIL_RE.match(value))
        return ValidationResult(
            valid=valid,
            code=None if valid else "INVALID_EMAIL",
            message=None if valid else "Not a valid email address.",
        )

    @staticmethod
    def _format_number(args: dict[str, Any]) -> str:
        value = float(args.get("value", 0))
        decimals = int(args.get("decimals", 0))
        grouping = args.get("grouping", True)
        spec = f",.{decimals}f" if grouping else f".{decimals}f"
        return format(value, spec)

    @staticmethod
    def _format_currency(args: dict[str, Any]) -> str:
        value = float(args.get("value", 0))
        currency = args.get("currency", "")
        decimals = int(args.get("decimals", 2))
        grouping = args.get("grouping", True)
        symbol = _CURRENCY_SYMBOLS.get(currency, f"{currency} ")
        spec = f",.{decimals}f" if grouping else f".{decimals}f"
        return f"{symbol}{format(value, spec)}"

    @staticmethod
    def _format_date(args: dict[str, Any]) -> str:
        value = args.get("value")
        fmt = args.get("format", "")
        if isinstance(value, (int, float)):
            timestamp = value / 1000 if value > 10_000_000_000 else value
            dt = datetime.fromtimestamp(timestamp, tz=UTC)
        elif isinstance(value, str):
            dt = datetime.fromisoformat(value)
        else:
            raise CatalogValidationError(
                f"formatDate: unsupported value type {type(value)!r}.",
                code=INVALID_FUNCTION_CALL,
            )
        strftime_fmt = fmt
        for token, directive in _DATE_TOKENS:
            strftime_fmt = strftime_fmt.replace(token, directive)
        return dt.strftime(strftime_fmt)

    @staticmethod
    def _pluralize(args: dict[str, Any]) -> str:
        value = args.get("value", 0)
        if value == 0 and "zero" in args:
            return args["zero"]
        if abs(value) == 1 and "one" in args:
            return args["one"]
        return args["other"]

    @staticmethod
    def _open_url(args: dict[str, Any]) -> None:
        # Renderer-side no-op marker (spec: requiresUserActivation, agent-side
        # execution is FEAT-469 territory). Real navigation is the renderer's
        # (browser/host's) job, not this pure evaluator's.
        return None

    @staticmethod
    def _and(args: dict[str, Any]) -> bool:
        return all(bool(v) for v in args.get("values", []))

    @staticmethod
    def _or(args: dict[str, Any]) -> bool:
        return any(bool(v) for v in args.get("values", []))

    @staticmethod
    def _not(args: dict[str, Any]) -> bool:
        return not bool(args.get("value"))
