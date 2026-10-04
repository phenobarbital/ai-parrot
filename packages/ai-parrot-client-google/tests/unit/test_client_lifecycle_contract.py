"""Structural contract: no async method may touch ``self.client`` before awaiting ``_ensure_client()``.

``docs/clients/per-loop-cache.md`` makes this a rule for subclass authors — the per-loop cache only
builds an SDK client when a method asks it to, so any method that reaches for ``self.client`` first
crashes with ``'NoneType' object has no attribute 'aio'`` for a caller that never opened the client.

Behavioural tests cover the individual entry points; this one pins the invariant for the whole
module, including methods added later.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import parrot.clients.google as google_pkg

MODULES = ("client.py", "analysis.py", "generation.py")

#: Async methods allowed to touch ``self.client`` unguarded, with the reason they are safe.
ALLOWED: dict[str, str] = {
    "_upload_video": "private; only called from video_understanding(), which ensures first",
    "_upload_document": "private; only called from document_understanding(), which ensures first",
}

#: Synchronous methods that cannot await ``_ensure_client()`` at all. They call the blocking
#: ``self.client.models.*`` API and raise ``AttributeError`` on an unopened client. Fixing them
#: means making them async (a breaking change) or dropping them — tracked, not silently ignored.
SYNC_GAPS = frozenset(
    {
        "analyze_sentiment",
        "analyze_product_review",
        "summarize_text",
        "translate_text",
        "extract_key_points",
    }
)


def _methods(path: Path):
    """Yield ``(name, is_async, first self.client line, first _ensure_client line)`` per method."""
    for cls in (n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.ClassDef)):
        for fn in (n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            if fn.name in ("_ensure_client", "_client_invalid_for_current", "client"):
                continue
            uses = [
                n.lineno
                for n in ast.walk(fn)
                if isinstance(n, ast.Attribute)
                and n.attr == "client"
                and isinstance(n.value, ast.Name)
                and n.value.id == "self"
            ]
            if not uses:
                continue
            ensures = [
                n.lineno
                for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_ensure_client"
            ]
            yield fn.name, isinstance(fn, ast.AsyncFunctionDef), min(uses), (min(ensures) if ensures else None)


@pytest.fixture(scope="module")
def modules() -> list[Path]:
    """The Google client modules that drive the SDK."""
    root = Path(google_pkg.__file__).parent
    return [root / name for name in MODULES]


def test_every_async_method_ensures_its_client_first(modules):
    """A new method that reads ``self.client`` without ensuring it fails here, not in production."""
    violations = [
        f"{path.name}::{name} — self.client at line {use}, "
        f"{'_ensure_client at line ' + str(ensure) if ensure else 'no _ensure_client'}"
        for path in modules
        for name, is_async, use, ensure in _methods(path)
        if is_async and name not in ALLOWED and (ensure is None or ensure > use)
    ]
    assert not violations, "async methods touching self.client before building it:\n  " + "\n  ".join(violations)


def test_the_allowlist_has_no_stale_entries(modules):
    """An allowlisted method that started ensuring (or disappeared) must leave the allowlist."""
    still_unguarded = {
        name
        for path in modules
        for name, is_async, use, ensure in _methods(path)
        if is_async and (ensure is None or ensure > use)
    }
    stale = set(ALLOWED) - still_unguarded
    assert not stale, f"remove from ALLOWED — no longer unguarded: {sorted(stale)}"


def test_the_known_sync_gaps_are_the_documented_ones(modules):
    """Pins the blast radius of the un-fixable sync methods: a new one must be a deliberate choice."""
    sync_gaps = {
        name for path in modules for name, is_async, use, ensure in _methods(path) if not is_async and ensure is None
    }
    assert sync_gaps == SYNC_GAPS, (
        "the set of synchronous methods using an unbuilt self.client changed: "
        f"added={sorted(sync_gaps - SYNC_GAPS)} removed={sorted(SYNC_GAPS - sync_gaps)}"
    )
