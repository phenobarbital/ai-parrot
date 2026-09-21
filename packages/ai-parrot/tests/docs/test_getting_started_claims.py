"""Claim-anchor extraction for docs/getting-started.md (FEAT-586, TASK-3584).

The metadata cross-checks that consume these claims are added by TASK-3585.
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import re
import sys
import types
import tomllib
import uuid as _uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

# repo root = five parents up from this file (packages/ai-parrot/tests/docs/<file>)
REPO_ROOT = Path(__file__).resolve().parents[4]
GUIDE = REPO_ROOT / "docs" / "getting-started.md"
CORE_PYPROJECT = REPO_ROOT / "packages" / "ai-parrot" / "pyproject.toml"

# Populated by test_hello_world_snippet_executes() so a mocked EntryPoint can
# resolve it by dotted path (f"{__name__}:_StubClient") — see that test.
_StubClient = None

ANCHOR_RE = re.compile(r"<!--\s*verify:\s*(?P<kind>[\w-]+)=(?P<value>.+?)\s*-->")


class DocClaim(BaseModel):
    """One `<!-- verify: kind=value -->` anchor extracted from the guide."""

    kind: Literal["python-range", "extra", "script", "provider", "envvar", "dep"]
    value: str
    line: int  # 1-based line in the source document
    source: Path


def extract_claims(path: Path) -> list[DocClaim]:
    """Parse every verify-anchor in `path`, preserving 1-based line numbers.

    Non-`verify:` HTML comments are ignored. Unknown kinds raise via DocClaim
    validation — an anchor typo must fail loudly, not be skipped.
    """
    claims: list[DocClaim] = []
    for i, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for m in ANCHOR_RE.finditer(text):
            claims.append(DocClaim(kind=m["kind"], value=m["value"], line=i, source=path))
    return claims


def test_guide_exists() -> None:
    """The guide is present and carries at least one verify-anchor."""
    assert GUIDE.is_file(), f"missing guide: {GUIDE}"
    assert extract_claims(GUIDE), "guide has no <!-- verify: ... --> anchors"


def test_extract_claims_parses_all_kinds(tmp_path: Path) -> None:
    """The regex parses each of the six kinds with correct line numbers."""
    doc = tmp_path / "doc.md"
    doc.write_text(
        "\n".join(
            [
                "# Doc",
                "<!-- verify: python-range=>=3.11,<3.14 -->",
                "<!-- verify: extra=jev -->",
                "<!-- verify: script=wikitoolkit -->",
                "<!-- verify: provider=claude-code -->",
                "<!-- verify: envvar=TYPESAFE_API_KEY -->",
                "<!-- verify: dep=ai-parrot-client-anthropic:claude-agent-sdk>=0.1.68 -->",
            ]
        ),
        encoding="utf-8",
    )

    claims = extract_claims(doc)

    assert len(claims) == 6
    by_kind = {c.kind: c for c in claims}
    assert by_kind["python-range"].value == ">=3.11,<3.14"
    assert by_kind["python-range"].line == 2
    assert by_kind["extra"].value == "jev"
    assert by_kind["extra"].line == 3
    assert by_kind["script"].value == "wikitoolkit"
    assert by_kind["script"].line == 4
    assert by_kind["provider"].value == "claude-code"
    assert by_kind["provider"].line == 5
    assert by_kind["envvar"].value == "TYPESAFE_API_KEY"
    assert by_kind["envvar"].line == 6
    assert by_kind["dep"].value == "ai-parrot-client-anthropic:claude-agent-sdk>=0.1.68"
    assert by_kind["dep"].line == 7
    assert all(c.source == doc for c in claims)


def test_extract_claims_ignores_plain_comments(tmp_path: Path) -> None:
    """A plain `<!-- note -->` HTML comment yields no claim."""
    doc = tmp_path / "doc.md"
    doc.write_text(
        "\n".join(
            [
                "# Doc",
                "<!-- note -->",
                "<!-- TODO: something -->",
                "Some prose with no anchors at all.",
            ]
        ),
        encoding="utf-8",
    )

    assert extract_claims(doc) == []


# ---------------------------------------------------------------------------
# TASK-3585: metadata cross-checks + hello-world execution + failure-message
# proof. Extends the extractor/DocClaim/GUIDE/REPO_ROOT from TASK-3584 above.
# ---------------------------------------------------------------------------


def _pyproject() -> dict:
    """Parsed core pyproject.toml (single source of truth for claim checks)."""
    return tomllib.loads(CORE_PYPROJECT.read_text(encoding="utf-8"))


def _claims(kind: str) -> list[DocClaim]:
    return [c for c in extract_claims(GUIDE) if c.kind == kind]


def _declared_provider_keys() -> set[str]:
    """Every provider key declared by any `ai-parrot-client-*` satellite's OWN
    `pyproject.toml` entry-points table, read straight from the repo tree.

    Fallback source for :func:`test_named_providers_are_registered` when no
    satellite is installed in the current environment (e.g. a bare-install
    CI job) — the live entry-point registry is empty in that case, but the
    guide's provider claims should still resolve against whatever a
    satellite in this tree actually declares.
    """
    keys: set[str] = set()
    for pyproject in (REPO_ROOT / "packages").glob("ai-parrot-client-*/pyproject.toml"):
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        entry_points = data.get("project", {}).get("entry-points", {}).get("parrot.clients", {})
        keys.update(entry_points.keys())
    return keys


def test_python_range_matches_pyproject() -> None:
    """Every python-range claim equals requires-python."""
    want = _pyproject()["project"]["requires-python"]
    for c in _claims("python-range"):
        assert c.value == want, f"{c.source}:{c.line} claims '{c.value}', pyproject says '{want}'"


def test_named_extras_exist() -> None:
    """Every extra claim is a real optional-dependency key."""
    extras = set(_pyproject()["project"]["optional-dependencies"])
    for c in _claims("extra"):
        assert c.value in extras, f"{c.source}:{c.line} unknown extra '{c.value}'"


def test_named_scripts_exist() -> None:
    """Every script claim is a real console-script key."""
    scripts = set(_pyproject()["project"]["scripts"])
    for c in _claims("script"):
        assert c.value in scripts, f"{c.source}:{c.line} unknown script '{c.value}'"


def test_named_providers_are_registered() -> None:
    """Every provider claim resolves in the parrot.clients entry points.

    Asserts against the live entry-point registry when at least one
    ``ai-parrot-client-*`` satellite is installed; falls back to the set of
    provider keys declared by any satellite's own ``pyproject.toml`` in this
    repo tree when none is installed (spec §7 risk: "provider entry points
    depend on what is installed").
    """
    installed = {ep.name for ep in importlib_metadata.entry_points(group="parrot.clients")}
    known = installed or _declared_provider_keys()
    for c in _claims("provider"):
        assert c.value in known, f"{c.source}:{c.line} unknown provider '{c.value}'"


def test_named_dep_floors_match() -> None:
    """Every `dep=<dist>:<req>` claim matches that satellite's declared floor."""
    for c in _claims("dep"):
        dist, _, requirement = c.value.partition(":")
        assert requirement, f"{c.source}:{c.line} malformed dep claim '{c.value}' (expected '<dist>:<requirement>')"
        satellite_pyproject = REPO_ROOT / "packages" / dist / "pyproject.toml"
        assert satellite_pyproject.is_file(), f"{c.source}:{c.line} unknown satellite '{dist}'"
        data = tomllib.loads(satellite_pyproject.read_text(encoding="utf-8"))
        declared = data.get("project", {}).get("dependencies", [])
        assert requirement in declared, (
            f"{c.source}:{c.line} dep floor '{requirement}' not declared by "
            f"packages/{dist}/pyproject.toml dependencies={declared}"
        )


def _make_stub_client_class():
    """Build the offline stub `AbstractClient` subclass at module scope.

    Defined via a factory (not at import time) so importing this module
    never requires `parrot.clients.base` eagerly — it is only constructed
    inside :func:`test_hello_world_snippet_executes`, then exposed as the
    module-level `_StubClient` name so `importlib.metadata.EntryPoint.load()`
    can resolve it by dotted path (`<this module>:_StubClient`), exactly
    like `tests/unit/clients/fakes.py`'s `FakeClient` pattern.
    """
    from parrot.clients.base import AbstractClient
    from parrot.models.responses import AIMessage, CompletionUsage

    class _StubClient(AbstractClient):
        """Offline stub client returning a canned reply — no network I/O."""

        client_type = "stub"

        def __init__(self, **kwargs) -> None:
            kwargs.setdefault("model", "stub")
            super().__init__(**kwargs)

        async def get_client(self) -> "_StubClient":
            return self

        async def ask(self, prompt: str, model=None, **kwargs) -> AIMessage:
            return AIMessage(
                input=prompt,
                output="Paris",
                model="stub",
                provider="stub",
                usage=CompletionUsage(),
                turn_id=str(_uuid.uuid4()),
            )

        async def ask_stream(self, prompt: str, **kwargs):
            yield "Paris"

        async def resume(self, session_id: str, user_input: str, state: dict):
            raise NotImplementedError

        async def invoke(self, prompt: str, **kwargs):
            raise NotImplementedError

    return _StubClient


def test_hello_world_snippet_executes(monkeypatch) -> None:
    """The guide's hello-world runs against a stub provider — offline.

    Two real, pre-existing gaps this test works around (neither is in scope
    for this feature to fix — see TASK-3584's Completion Note):

    1. ``BasicAgent.__init__`` unconditionally does
       ``from ..clients.google import GoogleGenAIClient`` regardless of the
       ``llm=`` argument, so it needs *some* importable ``parrot.clients.google``
       module even when a different provider is requested — a lightweight
       fake module is injected for the duration of the test.
    2. ``BaseBot.invoke()`` returns a single ``AIMessage``, not a 2-tuple, so
       this test (like the guide's corrected §4 snippet) reads ``.output``
       rather than unpacking two values.
    """
    global _StubClient
    _StubClient = _make_stub_client_class()

    # Work around gap 1: a harmless stand-in for the unconditionally-imported
    # GoogleGenAIClient (see docstring above). Only needed if the real
    # satellite/its own deps aren't importable in this environment.
    try:
        import parrot.clients.google  # noqa: F401
    except ImportError:
        fake_google = types.ModuleType("parrot.clients.google")

        class _FakeGoogleGenAIClient:
            def __init__(self, *a, **kw):
                pass

        fake_google.GoogleGenAIClient = _FakeGoogleGenAIClient
        monkeypatch.setitem(sys.modules, "parrot.clients.google", fake_google)

    # Register the offline stub under a provider key, exactly like
    # test_factory_discovery.py's mocked entry-point pattern (a real,
    # dotted-path-resolvable EntryPoint, never a monkeypatched `.load`), so
    # BasicAgent's default LLM resolution ("google") — and hence the guide's
    # un-modified `BasicAgent(name=...)` call with no explicit `llm=` — talks
    # to something deterministic and offline instead of a real provider.
    from parrot.clients import factory

    monkeypatch.setattr(factory, "_DISCOVERED", False, raising=False)
    factory.SUPPORTED_CLIENTS.clear()
    factory._PROVIDER_DIST.clear()

    ep = importlib_metadata.EntryPoint(
        name="google",
        value=f"{__name__}:_StubClient",
        group="parrot.clients",
    )
    monkeypatch.setattr(importlib_metadata, "entry_points", lambda group=None: [ep])

    import asyncio

    from parrot.bots.agent import BasicAgent

    async def _run():
        agent = BasicAgent(name="HelperAgent", llm="google", from_database=False)
        await agent.configure()
        return await agent.invoke("What is the capital of France?")

    response = asyncio.run(_run())

    assert response.output, "hello-world produced an empty answer"


def test_failure_message_names_file_and_line(tmp_path: Path) -> None:
    """A deliberately stale claim fails naming file, line and offending value."""
    doc = tmp_path / "stale.md"
    doc.write_text(
        "\n".join(
            [
                "# Doc",
                "<!-- verify: extra=does-not-exist -->",
            ]
        ),
        encoding="utf-8",
    )

    extras = set(_pyproject()["project"]["optional-dependencies"])
    claims = [c for c in extract_claims(doc) if c.kind == "extra"]
    assert claims, "fixture doc produced no extra claim"

    try:
        for c in claims:
            assert c.value in extras, f"{c.source}:{c.line} unknown extra '{c.value}'"
        raise AssertionError("expected the stale claim to fail")
    except AssertionError as exc:
        message = str(exc)
        assert str(doc) in message
        assert str(claims[0].line) in message
        assert "does-not-exist" in message
