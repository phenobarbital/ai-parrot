"""Claim-anchor extraction for docs/getting-started.md (FEAT-586, TASK-3584).

The metadata cross-checks that consume these claims are added by TASK-3585.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

# repo root = five parents up from this file (packages/ai-parrot/tests/docs/<file>)
REPO_ROOT = Path(__file__).resolve().parents[4]
GUIDE = REPO_ROOT / "docs" / "getting-started.md"

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
