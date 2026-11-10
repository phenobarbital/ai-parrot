# TASK-5464: install-parrot fix group (pinned uv hash, PS probe, --install-cli, py launcher, breadcrumb)

**Feature**: FEAT-873 install-install-parrot-fixes
**Spec**: `sdd/specs/install-install-parrot-fixes.spec.md`
**Status**: done
**Discovered-from**: `issue:6e31d9355edc`, `issue:2e35462be4bb`, `issue:73295db52ee4`, `issue:a786fec203e1`, `issue:3b2432011ac9`

## Scope
Implement spec §2 in `scripts/install/install-parrot.sh`, `scripts/install/install-parrot.ps1`,
`scripts/install/SHA256SUMS`, and adapt `packages/ai-parrot/tests/docs/test_install_posix.py` /
`test_install_powershell.py`. NOT in scope: changing the uv version or install layout.

## Validation Commands
`pytest packages/ai-parrot/tests/docs/test_install_posix.py packages/ai-parrot/tests/docs/test_install_powershell.py packages/ai-parrot/tests/docs/test_ci_install_wiring.py -q`

## Completion Note
Implemented in 28d1023888. Resolves issue:6e31d9355edc, issue:2e35462be4bb, issue:73295db52ee4,
issue:a786fec203e1, issue:3b2432011ac9. uv 0.11.28 per-asset SHA-256 pinned (sh: 4 targets, ps1: 2 Windows
zips) from astral-sh/uv release `.sha256` files at authoring time; `PARROT_UV_SHA256` overrides. Validation:
67 passed, 6 skipped (the pwsh-dependent tests skip: no pwsh on this host, so the PS 5.1 probe and py-launcher
paths are text-asserted only, not executed). A uv version bump must now update the pins.
