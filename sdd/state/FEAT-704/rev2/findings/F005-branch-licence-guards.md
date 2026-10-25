---
id: F005
query_id: Q005
type: read
intent: "Read the branch's licence notice, TID251 ban and packaging test around sidemantic"
executed_at: 2026-10-25T10:24:00Z
duration_ms: 3000
parent_id: null
depth: 0
---

# F005 — Branch ships an AGPL notice, a TID251 import ban and a packaging test for sidemantic

## Summary

The satellite README (branch) has a "License notice: sidemantic is AGPL-3.0" section spelling out the network clause and citing the 2026-10-19 sign-off. `ruff.toml` (branch) adds `"sidemantic".msg` to the TID251 banned-api table with a per-file ignore for `packages/ai-parrot-semantic/**`; `tests/test_packaging.py::test_sidemantic_import_ban` asserts the ban fires outside the satellite and not inside. On `dev` there is no `sidemantic` string anywhere under `packages/`, `docs/` or `ruff.toml`, and the package is not installed in the venv.

## Citations

- path: `packages/ai-parrot-semantic/README.md`
  lines: 10-19
  symbol: `## License notice: sidemantic is AGPL-3.0` (branch)
  excerpt: |
    This package is MIT-licensed, but it depends on `sidemantic==0.12.0`, which is **AGPL-3.0**.
    Section 13 of the AGPL (the "network clause") applies when software is offered to users over a network [...]
    Legal sign-off: Jesus Lara, 2026-10-19 (FEAT-704 spec §8 Q1).

- path: `ruff.toml`
  lines: 136, 151-152
  symbol: `[lint.flake8-tidy-imports.banned-api]` (branch)
  excerpt: |
    "sidemantic".msg          = "AGPL-3.0 dependency confined to ai-parrot-semantic; import it only under packages/ai-parrot-semantic/."
    # FEAT-704: the AGPL sidemantic dependency may be imported only inside its satellite.
    "packages/ai-parrot-semantic/**" = ["TID251"]

- path: `packages/ai-parrot-semantic/tests/test_packaging.py`
  lines: 28-39
  symbol: `test_sidemantic_import_ban` (branch)
  excerpt: |
    def test_sidemantic_import_ban():
        """TID251 flags `import sidemantic` outside the satellite only."""

## Notes

`grep -rl sidemantic packages docs ruff.toml` on `dev` → no matches; `pip show sidemantic` → not installed. On `dev` `packages/ai-parrot-semantic/` does not exist.
