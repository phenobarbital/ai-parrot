"""
Tests for the parrot.memory.skills deprecation re-export shim.

Verifies that:
1. Imports from the new parrot.skills namespace work correctly.
2. Imports from the old parrot.memory.skills namespace still work
   but issue a DeprecationWarning.
3. Both paths resolve to the same objects.
"""
import warnings

import pytest


class TestSkillsNamespacePromotion:
    """Verify the new parrot.skills namespace and the deprecation shim."""

    def test_new_import_works(self):
        """New top-level import resolves without error."""
        from parrot.skills import SkillFileRegistry  # noqa: F401

        assert SkillFileRegistry is not None

    def test_new_import_all_names(self):
        """All names in __all__ are importable from parrot.skills."""
        import parrot.skills

        for name in parrot.skills.__all__:
            assert hasattr(parrot.skills, name), f"Missing export: {name}"

    def test_old_import_warns(self):
        """Importing from parrot.memory.skills issues a DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # Trigger the __getattr__ shim
            from parrot.memory.skills import SkillFileRegistry  # noqa: F811

            deprecation_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) > 0, (
                "Expected DeprecationWarning when importing from parrot.memory.skills"
            )

    def test_old_and_new_resolve_same(self):
        """Both import paths resolve to the identical class object."""
        from parrot.skills import SkillDefinition as New

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from parrot.memory.skills import SkillDefinition as Old  # noqa: F811

        assert New is Old, "parrot.skills.SkillDefinition and parrot.memory.skills.SkillDefinition must be the same object"

    def test_old_import_message_contains_new_path(self):
        """DeprecationWarning message mentions parrot.skills."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from parrot.memory.skills import SkillRegistryMixin  # noqa: F811

            dep_warnings = [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]
            assert dep_warnings, "Expected at least one DeprecationWarning"
            msg = str(dep_warnings[0].message)
            assert "parrot.skills" in msg, f"Warning message should mention 'parrot.skills': {msg}"
