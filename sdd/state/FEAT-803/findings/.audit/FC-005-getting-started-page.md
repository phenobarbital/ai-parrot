# FC-005: Getting Started page exists

## Query
Check `docs/getting-started.md`

## Result
`docs/getting-started.md` exists and is a thorough installation guide (referenced by INSTALL.md). It covers:
- Prerequisites per OS (Ubuntu 24.04+, macOS 14+)
- Python version requirement (3.11-3.13, not 3.14)
- Every command is explained with blast radius and non-piped alternatives
- Uses `uv` as package manager

However, it's NOT in the mkdocs nav — `INSTALL.md` points to it via a link but the nav shows only `INSTALL.md` under "Getting Started".

## Citations
- docs/getting-started.md:1-50 — canonical install guide with OS-specific blocks
- mkdocs.yml:116-119 — nav shows INSTALL.md, config.md, tools_quick.md only

## Notes
The informative site should surface this getting-started page prominently — it's well-written and newcomer-friendly. Currently hidden behind a link from INSTALL.md. Could become the primary "Get Started" page.
