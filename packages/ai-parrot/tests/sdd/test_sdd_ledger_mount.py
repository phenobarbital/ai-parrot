"""C30 item 4: `parrot sdd ledger` is a second spelling of `wikitoolkit ledger` - same commands, lazily loaded."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.cli import cli


def test_sdd_help_does_not_import_wiki_cli() -> None:
    """AC-2: listing `parrot sdd` never imports the 4,000-line wiki CLI (fresh interpreter, no cached import)."""
    code = (
        "import sys; from click.testing import CliRunner; from parrot.cli import cli; "
        "r = CliRunner().invoke(cli, ['sdd', '--help']); "
        "assert r.exit_code == 0, r.output; "
        "assert 'ledger' in r.output; "
        "assert 'parrot.knowledge.wiki.cli' not in sys.modules"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_ledger_commands_match_wikitoolkit() -> None:
    from parrot.knowledge.wiki.cli import ledger
    from parrot.sdd.cli import sdd

    ctx = cli.make_context("parrot", ["sdd", "ledger"])
    assert sdd.get_command(ctx, "ledger").list_commands(ctx) == ledger.list_commands(ctx)
    result = CliRunner().invoke(cli, ["sdd", "ledger", "--help"])
    assert result.exit_code == 0, result.output
    assert "open" in result.output and "outbox" in result.output


def test_ledger_list_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-3: both spellings print the same document on the same ledger."""
    from parrot.knowledge.wiki.cli import wiki

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    opened = runner.invoke(
        cli,
        ["sdd", "ledger", "open", "--discovered-from", "spec:FEAT-1", "--title", "demo", "--body", "round trip"],
    )
    assert opened.exit_code == 0, opened.output
    via_sdd = runner.invoke(cli, ["sdd", "ledger", "list", "--json"])
    via_wiki = runner.invoke(wiki, ["ledger", "list", "--json"])
    assert via_sdd.exit_code == 0 and via_wiki.exit_code == 0, (via_sdd.output, via_wiki.output)
    assert via_sdd.output == via_wiki.output and "demo" in via_sdd.output
