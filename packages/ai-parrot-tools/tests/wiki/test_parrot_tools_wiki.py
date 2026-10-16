"""parrot_tools.wiki exports and lazy old paths (FEAT-540 M3)."""

import importlib
import sys


def test_new_path_exports() -> None:
    """New public imports resolve the moved wrappers."""
    from parrot_tools.wiki import LLMWikiToolkit, create_bulk_tools, create_wiki_tools

    assert LLMWikiToolkit and create_wiki_tools and create_bulk_tools


def test_old_path_same_object() -> None:
    """Legacy path resolves the exact moved toolkit object."""
    from parrot.knowledge.wiki.toolkit import LLMWikiToolkit as old
    from parrot_tools.wiki import LLMWikiToolkit as new

    assert old is new


def test_old_module_import_is_lazy() -> None:
    """Importing the old tools module does not load the framework base class."""
    sys.modules.pop("parrot.knowledge.wiki.tools", None)
    sys.modules.pop("parrot.tools.abstract", None)

    importlib.import_module("parrot.knowledge.wiki.tools")

    assert "parrot.tools.abstract" not in sys.modules
