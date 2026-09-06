#!/usr/bin/env python
"""Deterministic corpus + isolated-process measurement runner for the Luau
tree-sitter grammar (FEAT-532 TASK-2896).

Spec sections 3.1/8 require the scanner's resource policy (pre-parse byte
limit, ERROR-node density threshold, parse deadline, fallback input bound,
mapping JSON byte/depth limits) to be *measured*, not guessed from the
brainstorm's 32 KiB hypothesis. This module owns that measurement:

1. :func:`build_corpus` deterministically generates a small set of Luau/Lua
   byte strings (valid, malformed, deeply nested, a single long line, an
   incompatible-language sample, and an ~842 KiB pathological sample) —
   entirely from local string construction, never vendored code.
2. :func:`run_isolated` executes one parse in a **killable child process**
   (``multiprocessing`` "spawn" context) with a hard wall-clock deadline.
   This is deliberate: a stalled ``tree_sitter.Parser.parse()`` call is
   native code holding the GIL — a cancelled ``asyncio`` future or a
   ``threading.Thread`` cannot terminate it, only OS-level process
   termination (SIGTERM, escalating to SIGKILL) can.
3. ``main()`` runs the full corpus, prints a human-readable table, and
   writes a machine-readable JSON report plus an ``artifacts/logs`` copy
   for the completion record.

Usage:
    python scripts/benchmarks/luau_parser_limits.py \\
        [--deadline-seconds 2.0] [--out artifacts/logs/luau-parser-limits.json]

Linux/macOS: uses the "spawn" multiprocessing start method for isolation
parity across platforms (fork-based isolation would still share the
parent's loaded tree-sitter shared library state, which is exactly what
"the shared parser cache must not carry interrupted parse state into the
next file" (spec §7 Known Risks) warns against measuring around).
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import platform
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "packages" / "ai-parrot" / "src"
sys.path.insert(0, str(_SRC))

Outcome = Literal["completed", "timeout", "error"]


@dataclass
class CorpusCase:
    """One deterministically generated benchmark input."""

    name: str
    source: bytes
    description: str


@dataclass
class BenchmarkResult:
    """Measured outcome of parsing one :class:`CorpusCase`."""

    name: str
    size_bytes: int
    outcome: Outcome
    duration_seconds: float
    node_count: int | None = None
    error_node_count: int | None = None
    error_density: float | None = None
    detail: str | None = None


@dataclass
class PolicyReport:
    """Full measurement report: environment + per-case results."""

    python_version: str = field(default_factory=platform.python_version)
    platform: str = field(default_factory=platform.platform)
    tree_sitter_version: str = ""
    tree_sitter_luau_version: str | None = None
    deadline_seconds: float = 2.0
    results: list[BenchmarkResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Deterministic corpus generation
# ---------------------------------------------------------------------------


def _valid_small() -> bytes:
    return (
        b"-- A small, valid ModuleScript.\n"
        b"local Module = {}\n"
        b"\n"
        b"--- Adds two numbers.\n"
        b"function Module.add(a: number, b: number): number\n"
        b"\treturn a + b\n"
        b"end\n"
        b"\n"
        b"function Module:greet(name: string)\n"
        b'\tprint("hello " .. name)\n'
        b"end\n"
        b"\n"
        b"export type Point = { x: number, y: number }\n"
        b"\n"
        b"return Module\n"
    )


def _valid_medium(n_functions: int = 200) -> bytes:
    """A larger, still-valid module: ``n_functions`` typed functions."""
    lines = [b"-- Deterministically generated medium-sized valid module.\n"]
    lines.append(b"local Module = {}\n")
    for i in range(n_functions):
        lines.append(
            f"--- Function number {i}.\n"
            f"function Module.fn_{i}(a: number, b: string): boolean\n"
            f"\tlocal t{i} = {{ a = a, b = b }}\n"
            f"\treturn t{i}.a > 0\n"
            f"end\n".encode("utf-8")
        )
    lines.append(b"return Module\n")
    return b"".join(lines)


def _malformed_unbalanced() -> bytes:
    """Deliberately malformed: missing ``end`` tokens and a stray brace."""
    return (
        b"local Module = {}\n"
        b"function Module.broken(a\n"
        b"\tif a > 0 then\n"
        b"\t\tprint(a\n"
        b"local t = { a = 1, b = \n"
        b"return Module\n"
    )


def _deeply_nested(depth: int = 800) -> bytes:
    """``depth`` levels of nested ``if`` blocks — stresses tree depth."""
    tab = "\t"
    parts = [b"local function nested()\n"]
    for i in range(depth):
        indent = tab * (i + 1)
        parts.append(f"{indent}if x{i} then\n".encode("utf-8"))
    indent = tab * (depth + 1)
    parts.append(f"{indent}return true\n".encode("utf-8"))
    for i in range(depth, 0, -1):
        indent = tab * i
        parts.append(f"{indent}end\n".encode("utf-8"))
    parts.append(b"end\n")
    return b"".join(parts)


def _long_line(char_count: int = 200_000) -> bytes:
    """A single line: one very long string concatenation expression."""
    segments = " .. ".join(f'"seg{i}"' for i in range(char_count // 10))
    return f"local s = {segments}\n".encode("utf-8")


def _incompatible_python() -> bytes:
    """A full Python module fed to the Luau grammar (wrong-language input)."""
    return (
        b"class Foo:\n"
        b"    def __init__(self, x):\n"
        b"        self.x = x\n"
        b"\n"
        b"    def bar(self):\n"
        b"        return self.x ** 2\n"
        b"\n"
        b"if __name__ == '__main__':\n"
        b"    print(Foo(3).bar())\n"
    )


def _pathological(target_bytes: int = 842 * 1024) -> bytes:
    """~842 KiB of deeply parenthesized/nested table-constructor expressions.

    Mirrors the brainstorm's observed pathological size progression: nested
    parenthesized arithmetic wrapped inside nested table constructors,
    repeated until the target size is reached. Fully deterministic.
    """
    unit = b"({a=1,b=(1+2+3+4+5+6+7+8+9+10),c={1,2,3,4,5,6,7,8,9,10}})"
    repeats = max(1, target_bytes // len(unit))
    body = unit * repeats
    header = b"local t = {\n"
    footer = b"\n}\nreturn t\n"
    return header + body + footer


def build_corpus() -> list[CorpusCase]:
    """Build the deterministic measurement corpus.

    Returns:
        The fixed, ordered list of :class:`CorpusCase` instances. Calling
        this twice with no arguments always yields byte-identical sources
        (required by ``test_corpus_is_repeatable``).
    """
    return [
        CorpusCase("valid_small", _valid_small(), "Small valid ModuleScript"),
        CorpusCase("valid_medium", _valid_medium(), "200 typed functions, still valid"),
        CorpusCase(
            "malformed_unbalanced",
            _malformed_unbalanced(),
            "Missing 'end' tokens and unbalanced braces",
        ),
        CorpusCase("deeply_nested", _deeply_nested(), "800 levels of nested if-blocks"),
        CorpusCase("long_line", _long_line(), "One 200,000-character concatenation line"),
        CorpusCase(
            "incompatible_python",
            _incompatible_python(),
            "A full Python module (wrong language) fed to the Luau grammar",
        ),
        CorpusCase(
            "pathological_842kb",
            _pathological(),
            "~842 KiB of nested parenthesized table constructors",
        ),
    ]


# ---------------------------------------------------------------------------
# Isolated (killable) benchmark execution
# ---------------------------------------------------------------------------


def _count_nodes(root: Any) -> tuple[int, int]:
    """Iterative (non-recursive) count of ``(total_nodes, error_nodes)``.

    Deliberately iterative with an explicit stack: the deeply-nested and
    pathological corpus cases produce parse trees far deeper than Python's
    default recursion limit — a naive recursive walk raised
    ``RecursionError`` during measurement, which is itself evidence for the
    policy (see docs/design/luau-parser-resource-policy.md): any downstream
    tree-walking code (enrichment, outline rendering) must avoid recursive
    descent over untrusted-depth Luau trees.
    """
    total = 0
    errors = 0
    stack = [root]
    while stack:
        node = stack.pop()
        total += 1
        if node.type == "ERROR":
            errors += 1
        stack.extend(node.children)
    return total, errors


def _parse_worker(source: bytes, queue: "mp.Queue[dict[str, Any]]") -> None:
    """Child-process entry point: parse ``source`` and report node stats.

    Runs entirely inside the isolated child. Any exception is caught and
    reported back through the queue rather than propagated, so the parent's
    ``run_isolated`` can distinguish "the child crashed" from "the child was
    killed for exceeding the deadline".
    """
    try:
        # Deliberately built directly from ``tree_sitter_luau`` rather than
        # through ``parrot.knowledge.wiki.languages.treesitter.get_parser``:
        # registering "luau" in that module's grammar map is TASK-2899's
        # scope (the scanner task), not this measurement task's. This
        # benchmark must run standalone against the raw grammar.
        import tree_sitter_luau
        from tree_sitter import Language, Parser

        start = time.monotonic()
        ts_language = Language(tree_sitter_luau.language())
        parser = Parser(ts_language)
        tree = parser.parse(source)
        duration = time.monotonic() - start
        if tree is None:
            queue.put({"status": "error", "detail": "parser.parse returned None"})
            return
        total, errors = _count_nodes(tree.root_node)
        queue.put(
            {
                "status": "completed",
                "duration": duration,
                "node_count": total,
                "error_node_count": errors,
            }
        )
    except Exception as exc:  # noqa: BLE001 - reported to parent, not raised
        queue.put({"status": "error", "detail": f"{type(exc).__name__}: {exc}"})


def run_isolated(source: bytes, deadline_seconds: float) -> BenchmarkResult:
    """Parse ``source`` in a killable child process with a hard deadline.

    Args:
        source: Luau/Lua bytes to parse.
        deadline_seconds: Wall-clock budget. Exceeding it terminates the
            child (SIGTERM, escalating to SIGKILL if it does not exit
            promptly) and reports ``outcome="timeout"``.

    Returns:
        The measured :class:`BenchmarkResult`. Guarantees the child process
        is joined (no zombie/leaked process) before returning.
    """
    ctx = mp.get_context("spawn")
    queue: "mp.Queue[dict[str, Any]]" = ctx.Queue()
    process = ctx.Process(target=_parse_worker, args=(source, queue), daemon=True)

    start = time.monotonic()
    process.start()
    process.join(timeout=deadline_seconds)
    elapsed = time.monotonic() - start

    if process.is_alive():
        process.terminate()
        process.join(timeout=1.0)
        if process.is_alive():
            process.kill()
            process.join(timeout=1.0)
        return BenchmarkResult(
            name="",
            size_bytes=len(source),
            outcome="timeout",
            duration_seconds=elapsed,
            detail="deadline exceeded, child killed",
        )

    if not queue.empty():
        payload = queue.get()
        if payload["status"] == "completed":
            total = payload["node_count"]
            errors = payload["error_node_count"]
            density = errors / total if total else 0.0
            return BenchmarkResult(
                name="",
                size_bytes=len(source),
                outcome="completed",
                duration_seconds=payload["duration"],
                node_count=total,
                error_node_count=errors,
                error_density=density,
            )
        return BenchmarkResult(
            name="",
            size_bytes=len(source),
            outcome="error",
            duration_seconds=elapsed,
            detail=payload.get("detail"),
        )

    return BenchmarkResult(
        name="",
        size_bytes=len(source),
        outcome="error",
        duration_seconds=elapsed,
        detail=f"child exited (code={process.exitcode}) with no result",
    )


def _stall_worker(_source: bytes, _queue: "mp.Queue[dict[str, Any]]") -> None:
    """Test-only worker that never returns — simulates a stuck native parse."""
    while True:
        time.sleep(3600)


def run_isolated_with_worker(
    source: bytes,
    deadline_seconds: float,
    worker: Any,
) -> BenchmarkResult:
    """Same as :func:`run_isolated` but with an injectable worker target.

    Exists so tests can exercise the kill path deterministically (via
    :func:`_stall_worker`) without depending on ever actually deadlocking a
    real tree-sitter parse.
    """
    ctx = mp.get_context("spawn")
    queue: "mp.Queue[dict[str, Any]]" = ctx.Queue()
    process = ctx.Process(target=worker, args=(source, queue), daemon=True)

    start = time.monotonic()
    process.start()
    process.join(timeout=deadline_seconds)
    elapsed = time.monotonic() - start

    if process.is_alive():
        process.terminate()
        process.join(timeout=1.0)
        if process.is_alive():
            process.kill()
            process.join(timeout=1.0)
        return BenchmarkResult(
            name="",
            size_bytes=len(source),
            outcome="timeout",
            duration_seconds=elapsed,
            detail="deadline exceeded, child killed",
        )

    if not queue.empty():
        payload = queue.get()
        if payload["status"] == "completed":
            total = payload["node_count"]
            errors = payload["error_node_count"]
            density = errors / total if total else 0.0
            return BenchmarkResult(
                name="",
                size_bytes=len(source),
                outcome="completed",
                duration_seconds=payload["duration"],
                node_count=total,
                error_node_count=errors,
                error_density=density,
            )
        return BenchmarkResult(
            name="",
            size_bytes=len(source),
            outcome="error",
            duration_seconds=elapsed,
            detail=payload.get("detail"),
        )

    return BenchmarkResult(
        name="",
        size_bytes=len(source),
        outcome="error",
        duration_seconds=elapsed,
        detail=f"child exited (code={process.exitcode}) with no result",
    )


def run_corpus(deadline_seconds: float = 2.0) -> PolicyReport:
    """Run :func:`build_corpus` end-to-end and return the full report."""
    import tree_sitter

    try:
        import importlib.metadata as importlib_metadata

        luau_version = importlib_metadata.version("tree-sitter-luau")
    except Exception:  # noqa: BLE001 - version is informational only
        luau_version = None

    report = PolicyReport(
        tree_sitter_version=getattr(tree_sitter, "__version__", "unknown"),
        tree_sitter_luau_version=luau_version,
        deadline_seconds=deadline_seconds,
    )
    for case in build_corpus():
        result = run_isolated(case.source, deadline_seconds)
        result.name = case.name
        report.results.append(result)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deadline-seconds", type=float, default=2.0)
    parser.add_argument(
        "--out",
        type=Path,
        default=_REPO_ROOT / "artifacts" / "logs" / "luau-parser-limits.json",
    )
    args = parser.parse_args(argv)

    report = run_corpus(deadline_seconds=args.deadline_seconds)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(asdict(report), indent=2, default=str), encoding="utf-8")

    print(f"tree-sitter: {report.tree_sitter_version}")
    print(f"tree-sitter-luau: {report.tree_sitter_luau_version}")
    print(f"platform: {report.platform} / python {report.python_version}")
    print(f"deadline: {report.deadline_seconds}s\n")
    print(f"{'case':<24}{'size(B)':>10}{'outcome':>10}{'time(s)':>10}" f"{'nodes':>10}{'err_nodes':>10}{'density':>10}")
    for r in report.results:
        print(
            f"{r.name:<24}{r.size_bytes:>10}{r.outcome:>10}"
            f"{r.duration_seconds:>10.4f}"
            f"{(r.node_count or 0):>10}{(r.error_node_count or 0):>10}"
            f"{(r.error_density or 0.0):>10.4f}"
        )
    print(f"\nReport written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
