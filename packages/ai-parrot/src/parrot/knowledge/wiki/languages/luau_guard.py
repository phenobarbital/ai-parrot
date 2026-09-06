"""Measured Luau parse admission/cancellation/fallback guard (FEAT-532 TASK-2899).

Implements the three combined resource-policy guards TASK-2896 measured
and recorded in ``docs/design/luau-parser-resource-policy.md`` §3:

1. **Pre-parse size admission** (:func:`admit_for_treesitter`) — the
   primary, cheap defense. At the 1 MiB cap the worst measured shape
   (nested table constructors) parses in ≈0.53s, ~4x under the deadline.
2. **ERROR-node density** (:func:`error_density`) — a post-parse
   diagnostic signal, never a cancellation mechanism (TASK-2896 measured
   that tree-sitter's own error recovery does not hang at these sizes —
   there is nothing left to interrupt once ``parse()`` has returned).
3. **Enforceable parse timeout** (:func:`run_isolated`) — genuine
   OS-level cancellation. TASK-2896 confirmed the installed
   ``tree_sitter.Parser`` exposes no cancellation/timeout attribute, so
   neither an ``asyncio`` cancellation nor a ``threading.Thread`` join
   can interrupt a stalled native parse; only process termination can.
   This guard forks a child process per call and terminates (SIGTERM,
   escalating to SIGKILL) it on deadline expiry.

   Per ``docs/design/luau-parser-resource-policy.md`` §1/§3, this is
   **NOT** wired into :meth:`~parrot.knowledge.wiki.languages.luau.LuauScanner.outline`'s
   per-file production hot path — the measured pre-parse byte cap
   (:func:`admit_for_treesitter`) already bounds worst-case wall time to
   well under the deadline, and tree-sitter's own error recovery does
   not hang or raise at these sizes, so there is nothing left for a
   per-file fork to usefully cancel there. :func:`run_isolated` is
   reserved for the *offline benchmark/CI regression* path
   (``scripts/benchmarks/luau_parser_limits.py``,
   ``test_resource_corpus.py``) — the guard against a future
   tree-sitter-luau grammar regression that reintroduces a genuine hang.

   Deliberately uses the ``"fork"`` start method where available (cheap:
   no full interpreter re-init) rather than ``"spawn"``: TASK-2896 used
   ``"spawn"`` for its own benchmark specifically to avoid measuring
   around a shared already-loaded parser/module state across *repeated*
   calls in one long-lived benchmark process. Here every call forks a
   brand-new, short-lived child that parses exactly once and exits
   immediately — there is no reused parser or carried-over state to
   contaminate, so ``"fork"``'s cheaper cost is safe. Falls back to
   ``"spawn"`` on platforms without ``"fork"`` (job callables passed to
   :func:`run_isolated` must then be plain module-level functions, not
   closures, since ``"spawn"`` pickles them by reference).
"""

from __future__ import annotations

import multiprocessing as mp
from collections.abc import Callable
from typing import Any, TypeVar

#: Reviewed policy (docs/design/luau-parser-resource-policy.md §3).
BYTE_LIMIT = 1024 * 1024
DENSITY_THRESHOLD = 0.10
DEADLINE_SECONDS = 2.0
FALLBACK_BYTE_LIMIT = 4 * 1024 * 1024

T = TypeVar("T")


def admit_for_treesitter(source_bytes: bytes) -> bool:
    """Whether ``source_bytes`` is small enough to attempt a tree-sitter parse.

    Args:
        source_bytes: The encoded source, pre-parse.

    Returns:
        ``True`` when at or under :data:`BYTE_LIMIT`.
    """
    return len(source_bytes) <= BYTE_LIMIT


def admit_for_heuristic(source_bytes: bytes) -> bool:
    """Whether ``source_bytes`` is small enough for the bounded heuristic path.

    Args:
        source_bytes: The encoded source.

    Returns:
        ``True`` when at or under :data:`FALLBACK_BYTE_LIMIT`.
    """
    return len(source_bytes) <= FALLBACK_BYTE_LIMIT


def error_density(root: Any) -> float:
    """ERROR-node density of a parsed tree-sitter tree: ``errors / total``.

    Iterative (explicit stack), never recursive — TASK-2896 measured a
    naive recursive walk raising ``RecursionError`` on deeply nested Luau
    trees; this must never repeat that mistake.

    Args:
        root: A tree-sitter ``Node`` (typically ``tree.root_node``).

    Returns:
        The fraction of nodes with type ``"ERROR"`` (``0.0`` for an empty
        tree).
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
    return errors / total if total else 0.0


def _run_and_report(fn: Callable[..., T], args: tuple[Any, ...], queue: mp.Queue) -> None:
    """Child-process entry point: run ``fn(*args)`` and report the result.

    Deliberately a plain module-level function (never a closure) so it
    stays picklable-by-reference under the ``"spawn"`` start method —
    only ``fn``/``args``/``queue`` (passed as ``Process(args=...)``, thus
    pickled independently) carry the actual job-specific state.
    """
    try:
        queue.put({"ok": True, "value": fn(*args)})
    except Exception as exc:  # noqa: BLE001 - reported to parent, not raised
        queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def run_isolated(
    fn: Callable[..., T], args: tuple[Any, ...], deadline_seconds: float = DEADLINE_SECONDS
) -> tuple[T | None, str | None]:
    """Run ``fn(*args)`` in a freshly forked, killable child process.

    Args:
        fn: A plain, module-level callable (required for the ``"spawn"``
            fallback to pickle it by reference; a closure or bound method
            only works under ``"fork"``). Must return a picklable value.
        args: Positional arguments passed to ``fn``, must be picklable.
        deadline_seconds: Wall-clock budget. On expiry the child is
            terminated (SIGTERM), then killed (SIGKILL) if still alive.

    Returns:
        ``(result, None)`` on success, or ``(None, reason)`` on timeout,
        child exception, or unexpected exit. Never raises. Always joins
        the child before returning — no zombie/leaked process.
    """
    start_method = "fork" if "fork" in mp.get_all_start_methods() else "spawn"
    ctx = mp.get_context(start_method)
    queue: mp.Queue = ctx.Queue()

    process = ctx.Process(target=_run_and_report, args=(fn, args, queue), daemon=True)
    process.start()
    process.join(timeout=deadline_seconds)

    if process.is_alive():
        process.terminate()
        process.join(timeout=1.0)
        if process.is_alive():
            process.kill()
            process.join(timeout=1.0)
        return None, "timeout"

    try:
        # A short, bounded `get(timeout=...)` rather than `empty()` + `get()`
        # — `Queue.empty()` can read stale/false before the feeder thread has
        # flushed a just-`put()` item, a documented multiprocessing race. The
        # child has already exited at this point (checked above), so the
        # item — if the child produced one — is either already flushed or
        # arrives within a small, bounded window.
        payload = queue.get(timeout=1.0)
    except Exception:  # noqa: BLE001 - queue.Empty or any other queue failure
        return None, f"child exited (code={process.exitcode}) with no result"
    if payload["ok"]:
        return payload["value"], None
    return None, payload["error"]
