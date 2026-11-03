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


def test_install_matrix_fails_closed_and_avoids_expression_injection() -> None:
    """A wheel pattern with unmatched wheels must fail (no PyPI fallback); inputs travel via env, not run:."""
    import re

    import yaml

    wf = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "install-matrix.yml").read_text(encoding="utf-8"))
    step = next(s for s in wf["jobs"]["smoke"]["steps"] if s.get("name") == "Smoke")
    run = step["run"]
    assert "${{" not in run, "expressions must be passed through env:, never interpolated into the script"
    assert {"IN_SPEC", "IN_PYTHON", "IN_WHEEL_PATTERN"} <= set(step["env"])
    assert re.search(r'\[ -z "\$CORE" \] \|\| \[ -z "\$TOOLS" \]', run) and "exit 1" in run
    assert 'if [ -n "$IN_WHEEL_PATTERN" ]; then' in run


def test_installer_scripts_are_pinned_to_lf() -> None:
    """A Windows autocrlf checkout must not turn the hashed/executed installers into CRLF."""
    import subprocess

    for name in ("install-parrot.sh", "install-parrot.ps1", "SHA256SUMS"):
        out = subprocess.run(
            ["git", "check-attr", "eol", f"scripts/install/{name}"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        ).stdout
        assert out.strip().endswith("eol: lf"), out


def test_only_the_official_smoke_leg_blocks_a_release() -> None:
    """Owner decision 2026-10-29: Linux x86_64 is the only official platform; other legs run but never fail the job."""
    import yaml

    wf = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "install-matrix.yml").read_text(encoding="utf-8"))
    smoke = wf["jobs"]["smoke"]
    official = [e["os"] for e in smoke["strategy"]["matrix"]["include"] if e.get("official")]
    assert official == ["ubuntu-latest"]
    assert smoke["continue-on-error"] == "${{ matrix.official != true }}"
