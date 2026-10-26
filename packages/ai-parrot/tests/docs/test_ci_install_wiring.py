"""Assert ci.yml wires the FEAT-586 checks (TASK-3588)."""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
INSTALL_DIR = REPO_ROOT / "scripts" / "install"


def test_ci_runs_doc_and_script_checks() -> None:
    """ci.yml references the doc tests, both installer scripts, and a dry run."""
    text = CI.read_text(encoding="utf-8")
    assert "packages/ai-parrot/tests/docs/" in text
    assert "scripts/install/install-parrot.sh" in text
    assert "scripts/install/install-parrot.ps1" in text
    assert "--dry-run" in text


def test_ci_runs_global_dry_runs_and_checksum_gate() -> None:
    """ci.yml dry-runs --global / -Global and verifies SHA256SUMS (FEAT-633)."""
    text = CI.read_text(encoding="utf-8")
    assert "install-parrot.sh --global --dry-run" in text
    assert "install-parrot.ps1 -Global -DryRun" in text
    assert "sha256sum -c SHA256SUMS" in text


def test_sha256sums_match_scripts() -> None:
    """The committed SHA256SUMS covers both installers and matches their current bytes."""
    sums = INSTALL_DIR / "SHA256SUMS"
    assert sums.is_file(), "scripts/install/SHA256SUMS is missing"
    recorded: dict[str, str] = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        recorded[name.lstrip("*")] = digest
    assert set(recorded) == {"install-parrot.sh", "install-parrot.ps1"}
    for name, digest in recorded.items():
        actual = hashlib.sha256((INSTALL_DIR / name).read_bytes()).hexdigest()
        assert actual == digest, (
            f"{name} changed without regenerating SHA256SUMS — run: "
            "cd scripts/install && sha256sum install-parrot.sh install-parrot.ps1 > SHA256SUMS"
        )
