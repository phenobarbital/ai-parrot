"""FEAT-878 docs facts: the page operators are pointed to names every switch and both guard fixes."""

from pathlib import Path

from parrot.userstore import GLOBAL_SWITCH, SWITCHES

REPO = Path(__file__).resolve().parents[4]
PAGE = REPO / "wiki" / "stores" / "user-stores.md"


def test_page_names_every_switch():
    text = PAGE.read_text(encoding="utf-8")
    for name in [GLOBAL_SWITCH, *SWITCHES, "PARROT_USER_STORE_REDIS_URL", "CREW_RESULT_STORAGE"]:
        assert name in text, name


def test_page_names_guard_fixes_and_cli():
    text = PAGE.read_text(encoding="utf-8")
    assert "PARROT_USER_STORE=documentdb" in text and "PARROT_USER_STORE=redis" in text
    assert "python -m parrot.userstore.copy" in text
