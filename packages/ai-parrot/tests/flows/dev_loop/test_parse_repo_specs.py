"""Tests: parse_repo_specs (FEAT-253 TASK-002).

Verifies that ``DEV_LOOP_REPOS`` entries — slug, SSH URL, HTTPS URL, and
JSON object strings — are parsed correctly into :class:`RepoSpec` objects.
"""

import pytest

from parrot.flows.dev_loop.config import parse_repo_specs
from parrot.flows.dev_loop.models import RepoSpec


def test_parse_repo_specs_slug() -> None:
    """owner/name slug -> alias=name, url=slug."""
    [s] = parse_repo_specs(["phenobarbital/ai-parrot"])
    assert s.alias == "ai-parrot"
    assert s.url == "phenobarbital/ai-parrot"


def test_parse_repo_specs_ssh_url() -> None:
    """SSH URL -> alias=name (without .git), url preserved."""
    [s] = parse_repo_specs(["git@github.com:phenobarbital/ai-parrot.git"])
    assert s.alias == "ai-parrot"
    assert s.url == "git@github.com:phenobarbital/ai-parrot.git"


def test_parse_repo_specs_https_url() -> None:
    """HTTPS URL with .git -> alias=name (without .git)."""
    [s] = parse_repo_specs(["https://github.com/phenobarbital/ai-parrot.git"])
    assert s.alias == "ai-parrot"


def test_parse_repo_specs_https_url_no_git_suffix() -> None:
    """HTTPS URL without .git -> alias=name."""
    [s] = parse_repo_specs(["https://github.com/phenobarbital/ai-parrot"])
    assert s.alias == "ai-parrot"


def test_parse_repo_specs_json() -> None:
    """JSON object string round-trips all RepoSpec fields."""
    [s] = parse_repo_specs(
        ['{"alias":"x","url":"o/n","branch":"dev","private":true}']
    )
    assert s.alias == "x"
    assert s.url == "o/n"
    assert s.branch == "dev"
    assert s.private is True


def test_parse_repo_specs_skips_blanks() -> None:
    """Blank and whitespace-only entries are silently skipped."""
    result = parse_repo_specs(["", "  ", "o/n"])
    assert result == [RepoSpec(alias="n", url="o/n")]


def test_parse_repo_specs_empty_list() -> None:
    """Empty list produces an empty result."""
    assert parse_repo_specs([]) == []


def test_parse_repo_specs_none() -> None:
    """None input is treated as empty list."""
    assert parse_repo_specs(None) == []  # type: ignore[arg-type]


def test_parse_repo_specs_defaults() -> None:
    """Slug entry uses default branch=main and private=False."""
    [s] = parse_repo_specs(["owner/repo"])
    assert s.branch == "main"
    assert s.private is False


def test_parse_repo_specs_multiple() -> None:
    """Multiple entries produce multiple RepoSpecs in order."""
    specs = parse_repo_specs(["a/b", "c/d"])
    assert len(specs) == 2
    assert specs[0].alias == "b"
    assert specs[1].alias == "d"


def test_parse_repo_specs_import_from_package() -> None:
    """parse_repo_specs can be imported directly from parrot.flows.dev_loop."""
    from parrot.flows.dev_loop import parse_repo_specs as _f  # noqa: PLC0415

    assert callable(_f)
    [s] = _f(["owner/name"])
    assert s.alias == "name"
