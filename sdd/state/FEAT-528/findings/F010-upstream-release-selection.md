---
id: F010
query_id: Q009
type: web_read
intent: Select the upstream Obscura release, build variant, and platform set
executed_at: 2026-09-05T15:10:00Z
depth: 1
parent_id: F005
---

# F010 — Upstream target is Obscura v0.2.2, Linux, render build

## Summary

`synthesis.json` (commit `e4771cb80`) cited this finding for the release
decision but no finding file was written; revision 2 backfills it from a
direct read of the releases page and installation docs. v0.2.2 was released
on 2026-09-05 and its notes are the first to claim that "generated CDP
clients now work end to end, Playwright form filling and context setup
complete", so it is the minimum acceptable version. Archives ship in four
variants; the `no-render` variants lack the rendering engine and therefore
screenshots and PDF, which `AbstractDriver` requires.

## Citations

- path: `https://github.com/h4ckf0r0day/obscura/releases`
  lines: release list (accessed 2026-09-05, revision 2)
  symbol: `v0.2.2`
  excerpt: |
    v0.2.2 (2026-09-05): "A wide compatibility and robustness pass: generated
    CDP clients now work end to end, Playwright form filling and context
    setup complete." Artifacts: obscura-{x86_64,aarch64}-linux[-no-render][-stealth].tar.gz,
    obscura-aarch64-macos[-no-render][-stealth].tar.gz. No Windows artifact.
    Prior: v0.2.1 (2026-08-23), v0.2.0 (2026-08-08), v0.1.11 (2026-07-26).

- path: `https://docs.obscura.sh/quickstart/installation.md`
  lines: build variants / platform support (accessed 2026-09-05, revision 2)
  symbol: archive variants
  excerpt: |
    Default (render), `-stealth`, `-no-render`, `-no-render-stealth`.
    Linux builds "target Ubuntu 22.04 and require glibc 2.35+". Docker image
    `h4ckf0r0day/obscura` on `distroless/cc`, default port 9222. Each archive
    ships `obscura` and `obscura-worker`.

## Notes

Decision (user, Q&A U1): pin **>= v0.2.2**, Linux, render-capable build
(`stealth` optional). Reject older releases and `no-render` variants.
Windows is out of scope; macOS is untested but not blocked.
