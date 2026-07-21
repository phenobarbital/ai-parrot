"""Structural regression tests for the Porygon identity migration (FEAT-321).

Porygon's runtime deps are heavy (Google LLM client, pandas stack, BigQuery/
Postgres drivers) and ``agents/`` is gitignored, so these checks assert on
source text and file existence rather than importing/instantiating the
agent. `agents/porygon.py` also lives outside any installed package (repo
root, gitignored) — resolve the path relative to this test file instead of
importing it.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PORYGON = REPO / "agents" / "porygon.py"
IDENTITY = REPO / "agents" / "porygon" / "identity"

IDENTITY_FILE_NAMES = ("role", "goal", "capabilities", "backstory", "rationale")


class TestPorygonMigration:
    def test_identity_files_exist(self):
        for name in IDENTITY_FILE_NAMES:
            f = IDENTITY / f"{name}.md"
            assert f.is_file(), f"missing {f}"
            assert f.read_text(encoding="utf-8").strip()

    def test_backstory_constant_removed(self):
        src = PORYGON.read_text(encoding="utf-8")
        assert "BACKSTORY = " not in src
        assert "backstory=BACKSTORY" not in src

    def test_mixin_adopted(self):
        src = PORYGON.read_text(encoding="utf-8")
        assert "IdentityMixin" in src
        assert "enable_identity: bool = True" in src
        assert "identity_dir = " in src
        assert "_configure_identity()" in src
        # IdentityMixin must be FIRST in the bases list (spec §3 Module 4).
        assert "class Porygon(IdentityMixin, " in src

    def test_content_parity_markers(self):
        merged = " ".join(
            (IDENTITY / f"{n}.md").read_text(encoding="utf-8")
            for n in IDENTITY_FILE_NAMES
        )
        # Distinctive phrases pulled from the original BACKSTORY constant
        # before it was removed — proves the split preserved substance.
        markers = (
            "operations analyst for TROC",
            "Organizational Hierarchy",
            "Lost Revenue Window",
            "Kiosk-Merchandiser Ratio (KMR)",
            "Always Contextualize",
        )
        for marker in markers:
            assert marker in merged, f"missing marker: {marker!r}"
