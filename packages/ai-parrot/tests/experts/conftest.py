"""Shared fixtures for FEAT-778 tests (spec §4 Test Data). Pure files — no network, no LLM."""

from __future__ import annotations

from pathlib import Path

import pytest

MANIFEST = """\
name: sample-expert
display_name: Sample Expert
description: Sample expert used by the FEAT-778 tests
tier: balanced
knowledge:
  - {source: wiki, mode: retrieval}
  - {source: bundled, mode: inline}
  - {source: adr, mode: inline, filter: {status: [accepted]}}
"""


@pytest.fixture
def expert_bundle(tmp_path: Path) -> Path:
    """Create an AGENTS_DIR expert bundle with tier-one and tenant-shadowed knowledge."""
    root = tmp_path / "experts" / "sample-expert"
    (root / "identity").mkdir(parents=True)
    (root / "knowledge").mkdir()
    (root / "rules").mkdir()
    (root / "tenants" / "acme" / "knowledge").mkdir(parents=True)
    (root / "expert.yaml").write_text(MANIFEST, encoding="utf-8")
    (root / "identity" / "role.md").write_text("You are a sample expert.\n", encoding="utf-8")
    (root / "identity" / "goal.md").write_text("Provide evidence-based guidance.\n", encoding="utf-8")
    (root / "knowledge" / "method.md").write_text("Use primary sources.\n", encoding="utf-8")
    (root / "rules" / "governance.md").write_text(
        "## Mandated\nALWAYS cite sources\n## Forbidden\nNEVER delegate\n", encoding="utf-8"
    )
    (root / "persona.md").write_text("This file is documentation only.\n", encoding="utf-8")
    (root / "tenants" / "acme" / "knowledge" / "method.md").write_text("Use Acme primary sources.\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def governance_dir(tmp_path: Path) -> Path:
    """Create the org, team, and project governance rules directory."""
    root = tmp_path / "governance"
    root.mkdir()
    (root / "org.md").write_text(
        "## Mandated\nALWAYS cite sources\n## Forbidden\nNEVER disclose secrets\n", encoding="utf-8"
    )
    (root / "team.md").write_text(
        "## Mandated\nALWAYS review evidence\n## Forbidden\nNEVER bypass review\n", encoding="utf-8"
    )
    (root / "project.md").write_text(
        "## Mandated\nALWAYS cite sources\n## Forbidden\nNEVER skip validation\n", encoding="utf-8"
    )
    return tmp_path
