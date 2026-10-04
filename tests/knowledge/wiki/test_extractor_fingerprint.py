"""FEAT-609 M2: a changed extractor re-ingests its language on the next plain build."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.languages import astgrep
from parrot.knowledge.wiki.languages.fingerprint import (
    ExtractorFingerprint,
    changed_languages,
    current_fingerprint,
    load_fingerprint,
    save_fingerprint,
)
from parrot.knowledge.wiki.store import BaseWikiStore

from .languages.conftest import requires_astgrep


@requires_astgrep
def test_fingerprint_changed_languages_tier_flip(monkeypatch) -> None:
    before = current_fingerprint()
    monkeypatch.setattr(astgrep, "is_available", lambda: False)
    after = current_fingerprint()
    changed = changed_languages(before, after)
    assert {"javascript", "php", "rust", "perl"} <= changed
    assert "luau" not in changed and "python" not in changed


def test_fingerprint_none_marks_all_structural() -> None:
    assert changed_languages(None, current_fingerprint()) == {"javascript", "php", "rust", "perl"}


def test_fingerprint_rule_hash_change() -> None:
    fp = current_fingerprint()
    edited = ExtractorFingerprint(languages={**fp.languages, "php": fp.languages["php"] + "x"})
    assert changed_languages(fp, edited) == {"php"}
    edited_py = ExtractorFingerprint(languages={**fp.languages, "python": fp.languages["python"] + "x"})
    assert changed_languages(fp, edited_py) == {"python"}


def test_fingerprint_no_change() -> None:
    fp = current_fingerprint()
    assert changed_languages(fp, fp) == set()


class _Store:
    def __init__(self, value: str | None) -> None:
        self.value = value

    async def get_meta(self, key: str) -> str | None:
        return self.value

    async def set_meta(self, key: str, value: str) -> None:
        self.value = value


class _NoMeta:
    async def get_meta(self, key: str):
        raise NotImplementedError

    async def set_meta(self, key: str, value: str) -> None:
        raise NotImplementedError


async def test_fingerprint_load_corrupt() -> None:
    assert await load_fingerprint(_Store("{not json")) is None  # type: ignore[arg-type]
    assert await load_fingerprint(_Store('{"languages": "oops"}')) is None  # type: ignore[arg-type]
    assert await load_fingerprint(_Store(None)) is None  # type: ignore[arg-type]
    assert await load_fingerprint(_NoMeta()) is None  # type: ignore[arg-type]


async def test_fingerprint_roundtrip_and_no_meta_backend() -> None:
    store = _Store(None)
    fp = current_fingerprint()
    await save_fingerprint(store, fp)  # type: ignore[arg-type]
    assert await load_fingerprint(store) == fp  # type: ignore[arg-type]
    await save_fingerprint(_NoMeta(), fp)  # type: ignore[arg-type]  # swallowed


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _build(runner: CliRunner, repo: Path):
    result = runner.invoke(wiki, ["build", "--path", str(repo), "--no-git"])
    assert result.exit_code == 0, result.output
    return result


def _ingested(output: str) -> int:
    match = re.search(r"(\d+) ingested", output)
    assert match, output
    return int(match.group(1))


def _symbols(runner: CliRunner, repo: Path) -> int:
    result = runner.invoke(wiki, ["status", "--path", str(repo), "--json"])
    return int(json.loads(result.output)["stats"].get("symbols", 0))


@requires_astgrep
def test_build_heals_after_extra_installed(tmp_path, monkeypatch) -> None:
    _write(tmp_path, "a.ts", "export function alpha(): number {\n  return 1\n}\n")
    runner = CliRunner()
    with monkeypatch.context() as patch:
        patch.setattr(astgrep, "is_available", lambda: False)
        astgrep.RuleSet.load.cache_clear()
        _build(runner, tmp_path)
        assert _symbols(runner, tmp_path) == 0
    astgrep.RuleSet.load.cache_clear()
    # ast-grep is "installed" now: a PLAIN build (no --force) must produce symbols.
    healed = _build(runner, tmp_path)
    assert _ingested(healed.output) >= 1
    assert _symbols(runner, tmp_path) >= 1


@requires_astgrep
def test_build_fingerprint_no_churn(tmp_path) -> None:
    _write(tmp_path, "a.ts", "export function alpha(): number {\n  return 1\n}\n")
    _write(tmp_path, "b.py", "def beta():\n    return 1\n")
    runner = CliRunner()
    _build(runner, tmp_path)
    second = _build(runner, tmp_path)
    assert _ingested(second.output) == 0


def test_fingerprint_saved_via_meta_not_file(tmp_path) -> None:
    _write(tmp_path, "b.py", "def beta():\n    return 1\n")
    _build(CliRunner(), tmp_path)
    assert not list(tmp_path.rglob("extractor_fingerprint*.json"))
    from parrot.knowledge.wiki.cli import _open_store
    from parrot.knowledge.wiki.project import load_project_config

    store: BaseWikiStore = _open_store(tmp_path, load_project_config(tmp_path))
    fp = asyncio.run(load_fingerprint(store))
    assert fp is not None and set(fp.languages) >= {"python", "javascript"}


