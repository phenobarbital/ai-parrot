"""Protocol-conformance tests for `Narrator` (FEAT-420 Module 3)."""

from typing import Any, Optional

from parrot.tools.infographic_recipes.narrator import Narrator


class _Stub:
    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]:
        return "prose"


class TestNarratorProtocol:
    def test_stub_satisfies_protocol(self):
        assert isinstance(_Stub(), Narrator)

    def test_non_conforming_object_does_not(self):
        assert not isinstance(object(), Narrator)

    def test_narrator_module_imports_nothing_from_parrot(self):
        """G8 hygiene: keep this a pure typing module."""
        import inspect

        from parrot.tools.infographic_recipes import narrator

        src = inspect.getsource(narrator)
        assert "from parrot" not in src and "import parrot" not in src
