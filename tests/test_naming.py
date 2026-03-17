"""Tests for parrot.utils.naming — slug generation and de-duplication."""
import pytest
from parrot.utils.naming import slugify_name, deduplicate_name


# ── slugify_name ──────────────────────────────────────────────────────

class TestSlugifyName:
    """Unit tests for slugify_name()."""

    def test_basic(self):
        assert slugify_name("My Cool Bot") == "my-cool-bot"

    def test_special_chars(self):
        assert slugify_name("Bot @#$ Test!") == "bot-test"

    def test_consecutive_hyphens(self):
        assert slugify_name("Bot - - Test") == "bot-test"

    def test_trim(self):
        assert slugify_name("  My Bot  ") == "my-bot"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty slug"):
            slugify_name("@#$")

    def test_already_slug(self):
        assert slugify_name("my-bot") == "my-bot"

    def test_underscores(self):
        assert slugify_name("my_bot_name") == "my-bot-name"

    def test_numbers_preserved(self):
        assert slugify_name("bot-v2-test") == "bot-v2-test"

    def test_leading_trailing_hyphens(self):
        assert slugify_name("---my-bot---") == "my-bot"

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="empty slug"):
            slugify_name("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty slug"):
            slugify_name("   ")

    def test_idempotent(self):
        slug = slugify_name("My Cool Bot")
        assert slugify_name(slug) == slug


# ── deduplicate_name ──────────────────────────────────────────────────

class TestDeduplicateName:
    """Unit tests for deduplicate_name()."""

    @pytest.mark.asyncio
    async def test_no_conflict(self):
        async def exists_fn(name):
            return None

        result = await deduplicate_name("my-bot", exists_fn)
        assert result == "my-bot"

    @pytest.mark.asyncio
    async def test_one_conflict(self):
        taken = {"my-bot"}

        async def exists_fn(name):
            return "database" if name in taken else None

        result = await deduplicate_name("my-bot", exists_fn)
        assert result == "my-bot-2"

    @pytest.mark.asyncio
    async def test_multiple_conflicts(self):
        taken = {"my-bot", "my-bot-2", "my-bot-3"}

        async def exists_fn(name):
            return "database" if name in taken else None

        result = await deduplicate_name("my-bot", exists_fn)
        assert result == "my-bot-4"

    @pytest.mark.asyncio
    async def test_exhaustion(self):
        taken = {"my-bot"} | {f"my-bot-{i}" for i in range(2, 100)}

        async def exists_fn(name):
            return "database" if name in taken else None

        with pytest.raises(ValueError, match="all suffixes up to -99"):
            await deduplicate_name("my-bot", exists_fn)

    @pytest.mark.asyncio
    async def test_returns_first_available(self):
        """If slug-2 is taken but slug-3 is free, returns slug-3."""
        taken = {"my-bot", "my-bot-2"}

        async def exists_fn(name):
            return "registry" if name in taken else None

        result = await deduplicate_name("my-bot", exists_fn)
        assert result == "my-bot-3"
