"""Tests for the Matrix dev stack compose/bootstrap — FEAT-463 TASK-2486."""

import pathlib
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
def test_compose_config_valid():
    out = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.matrix.yml", "--profile", "bridges", "config"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    services = set(yaml.safe_load(out)["services"])
    assert services == {
        "postgres",
        "synapse",
        "element-web",
        "well-known",
        "mautrix-signal",
        "mautrix-slack",
        "mautrix-discord",
    }


def test_compose_has_no_dropped_bridges():
    text = (ROOT / "docker-compose.matrix.yml").read_text()
    for banned in ("postmoogle", "mautrix/meta", "instagram", "jabber", "slidge", "xmpp"):
        assert banned not in text.lower()


def test_registration_main_outputs_yaml():
    # Force the worktree's own `ai-parrot-integrations` source onto
    # PYTHONPATH: the installed (main-repo) editable package would
    # otherwise shadow this worktree's `registration.py` in a fresh
    # subprocess, since only *pytest*'s own root conftest.py prepends
    # worktree source paths for the current process.
    env = {
        "PATH": "",
        "PYTHONPATH": str(ROOT / "packages" / "ai-parrot-integrations" / "src"),
        "MATRIX_AS_URL": "http://host.docker.internal:8449",
        "MATRIX_SERVER_NAME": "parrot.local",
    }
    out = subprocess.run(
        [sys.executable, "-m", "parrot.integrations.matrix.registration"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout
    reg = yaml.safe_load(out)
    assert reg["url"] == "http://host.docker.internal:8449"
    assert "as_token" in reg
    assert "hs_token" in reg


def test_bootstrap_dry_run():
    r = subprocess.run(
        ["bash", "scripts/matrix/bootstrap.sh", "--dry-run"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "register_new_matrix_user" in r.stdout
