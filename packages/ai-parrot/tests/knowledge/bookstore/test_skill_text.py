"""Mirror-sync test for the three bookstore skill-text copies (FEAT-533).

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
"""

from __future__ import annotations

from pathlib import Path

# packages/ai-parrot/tests/knowledge/bookstore/ -> repo root is 5 parents up.
_REPO_ROOT = Path(__file__).resolve().parents[5]

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


def test_skill_mirrors_share_funnel_section():
    skill_md = (_REPO_ROOT / ".agent" / "skills" / "bookstore" / "SKILL.md").read_text(encoding="utf-8")
    command_md = (_REPO_ROOT / ".claude" / "commands" / "bookstore.md").read_text(encoding="utf-8")
    assets_py = _bookstore_assets_text()

    for label, text in (
        ("SKILL.md", skill_md),
        ("bookstore.md", command_md),
        ("bookstore_assets.py", assets_py),
    ):
        assert FUNNEL_STEP_1B in text, f"funnel step 1b missing/out of sync in {label}"
        assert CITATION_RULE in text, f"citation rule missing/out of sync in {label}"
