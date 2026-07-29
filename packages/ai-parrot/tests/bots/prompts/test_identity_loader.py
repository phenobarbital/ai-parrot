"""Unit tests for load_identity / IdentityFields / read_text_cached (FEAT-321)."""
import os

import pytest

from parrot.bots.prompts.agent_context import read_text_cached
from parrot.bots.prompts.identity import IdentityFields, load_identity


@pytest.fixture
def identity_dir(tmp_path):
    for f, text in {
        "role": "a test analyst",
        "goal": "answer questions",
        "capabilities": "- do X\n- do Y",
        "backstory": "context here",
        "rationale": "be concise",
    }.items():
        (tmp_path / f"{f}.md").write_text(text, encoding="utf-8")
    return tmp_path


class TestLoadIdentity:
    def test_reads_all_fields(self, identity_dir):
        fields = load_identity(identity_dir)
        assert fields.role == "a test analyst"
        assert fields.capabilities == "- do X\n- do Y"
        assert len(fields.as_kwargs()) == 5

    def test_missing_file_is_none(self, identity_dir):
        (identity_dir / "goal.md").unlink()
        assert load_identity(identity_dir).goal is None

    def test_empty_file_is_none(self, identity_dir):
        (identity_dir / "role.md").write_text("   \n", encoding="utf-8")
        fields = load_identity(identity_dir)
        assert fields.role is None
        assert "role" not in fields.as_kwargs()

    def test_missing_directory(self, tmp_path):
        assert load_identity(tmp_path / "nope").as_kwargs() == {}

    def test_no_dollar_escaping_by_default(self, identity_dir):
        (identity_dir / "backstory.md").write_text(
            "Today is $current_date", encoding="utf-8"
        )
        assert load_identity(identity_dir).backstory == "Today is $current_date"

    def test_escape_placeholders_flag(self, identity_dir):
        (identity_dir / "backstory.md").write_text("costs $10", encoding="utf-8")
        assert "$$" in load_identity(identity_dir, escape_placeholders=True).backstory


class TestIdentityFieldsModel:
    def test_defaults_to_none(self):
        fields = IdentityFields()
        assert fields.as_kwargs() == {}

    def test_as_kwargs_filters_empty(self):
        fields = IdentityFields(role="x", goal=None)
        assert fields.as_kwargs() == {"role": "x"}


class TestReadTextCached:
    def test_mtime_invalidation(self, tmp_path):
        f = tmp_path / "x.md"
        f.write_text("v1", encoding="utf-8")
        assert read_text_cached(f) == "v1"
        f.write_text("v2", encoding="utf-8")
        os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 2))
        assert read_text_cached(f) == "v2"

    def test_missing_file_empty(self, tmp_path):
        assert read_text_cached(tmp_path / "nope.md") == ""
