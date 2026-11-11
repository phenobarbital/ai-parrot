"""Mirror-sync test for the bookstore skill-text copies (FEAT-533, FEAT-876).

The funnel step 1b ("expand by relations") and the relation-origin
citation rule must read identically in all three places the skill text
is duplicated:

- ``.agent/skills/bookstore/SKILL.md``
- ``.claude/commands/bookstore.md``
- ``packages/ai-parrot/src/parrot/knowledge/wiki/google/bookstore_assets.py``
  (``BOOKSTORE_SKILL``)

Frontmatter/prose differences between the three files are expected and
must not fail this test — only the specific funnel/citation strings
below are compared, verbatim, across all three.

FEAT-876 adds the funnel step 1 (``bookstore_find_books`` first, with
``bookstore_catalog_search`` as the fallback) and the notebook citation
rule; both are also asserted in ``.agents/skills/bookstore/SKILL.md``,
which carries no step 1b.
"""

from __future__ import annotations

from pathlib import Path

# packages/ai-parrot/tests/knowledge/bookstore/ -> repo root is 5 parents up.
_REPO_ROOT = Path(__file__).resolve().parents[5]

FUNNEL_STEP_1 = (
    '1. **`bookstore_find_books(query)`** — ALWAYS start here. It answers "which books\n'
    "   treat X, and where\" from the librarian's sectors, with direct table-of-contents\n"
    "   pointers; it falls back to `bookstore_catalog_search`."
)

NOTEBOOK_RULE = (
    "Annotations returned next to a section are the reader's notes — cite them as "
    "*Notebook: <title>*, never as book pages."
)

FUNNEL_STEP_1B = (
    "1b. **Expand by relations** — before opening any book, call\n"
    "    `bookstore_related_books(book_id)` on the best `bookstore_catalog_search`\n"
    "    hit to find the author's other works, sibling works of the same\n"
    "    tradition/era, or conceptually adjacent works. For thematic or\n"
    '    comparative questions ("what schools of thought does this library\n'
    '    cover?"), call `bookstore_communities()` instead.'
)

CITATION_RULE = (
    'When a relation drives a claim, cite its origin: "the library links\n'
    'these as parallels (LLM-inferred, 0.7)" vs "same author\n'
    '(deterministic)".'
)


def _bookstore_assets_text() -> str:
    from parrot.knowledge.wiki.google.bookstore_assets import BOOKSTORE_SKILL

    return BOOKSTORE_SKILL


def _read(*parts: str) -> str:
    return (_REPO_ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def test_skill_mirrors_share_funnel_section():
    skill_md = _read(".agent", "skills", "bookstore", "SKILL.md")
    command_md = _read(".claude", "commands", "bookstore.md")
    assets_py = _bookstore_assets_text()

    for label, text in (
        ("SKILL.md", skill_md),
        ("bookstore.md", command_md),
        ("bookstore_assets.py", assets_py),
    ):
        assert FUNNEL_STEP_1B in text, f"funnel step 1b missing/out of sync in {label}"
        assert CITATION_RULE in text, f"citation rule missing/out of sync in {label}"


def test_skill_text_funnel_starts_with_find_books():
    """Every tracked copy opens the funnel with find_books and carries the notebook rule."""
    for label, text in (
        (".agent/skills/bookstore/SKILL.md", _read(".agent", "skills", "bookstore", "SKILL.md")),
        (".claude/commands/bookstore.md", _read(".claude", "commands", "bookstore.md")),
        ("bookstore_assets.py", _bookstore_assets_text()),
        (".agents/skills/bookstore/SKILL.md", _read(".agents", "skills", "bookstore", "SKILL.md")),
    ):
        assert FUNNEL_STEP_1 in text, f"funnel step 1 (find_books) missing/out of sync in {label}"
        assert NOTEBOOK_RULE in text, f"notebook citation rule missing/out of sync in {label}"
        # find_books is step 1: it precedes every other numbered funnel step.
        step_1 = text.index(FUNNEL_STEP_1)
        assert step_1 < text.index("\n2. "), f"find_books is not the first funnel step in {label}"
        assert "1. Start with `bookstore_catalog_search" not in text, f"stale catalog-first step 1 in {label}"
        assert "1. **`bookstore_catalog_search(query)`**" not in text, f"stale catalog-first step 1 in {label}"
