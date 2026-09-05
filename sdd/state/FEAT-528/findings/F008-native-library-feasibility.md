---
id: F008
query_id: Q005/Q007
type: web_read
intent: Determine whether Obscura's Rust library can be embedded through PyO3
executed_at: 2026-09-05T14:00:00Z
depth: 1
parent_id: F004
---

# F008 — Native PyO3 embedding is technically exposed but operationally expensive

## Summary

The upstream `obscura` crate publicly re-exports `Browser`, `BrowserConfig`, `Page`, cookies, and interception types, with an async Rust API and optional `render` feature. The upstream library guide says it is a git dependency rather than a crates.io release because V8 is built from source; it also requires the same compiler/toolchain resources as the full source build. A PyO3 wrapper would therefore need to bridge Tokio and browser/page ownership across Python calls, account for V8 concurrency constraints, and carry a large native build and platform compatibility burden.

## Citations

- path: `https://github.com/h4ckf0r0day/obscura/blob/main/crates/obscura/Cargo.toml`
  lines: 247-289 (accessed 2026-09-05)
  symbol: `obscura` crate features and dependencies
  excerpt: |
    The crate is version 0.1.0, defaults to `api`, and defines `render` as
    `api` plus `obscura-browser/render`; it depends on workspace browser/net
    crates and Tokio.

- path: `https://github.com/h4ckf0r0day/obscura/blob/main/crates/obscura/src/lib.rs`
  lines: 261-315 (accessed 2026-09-05)
  symbol: public Rust API
  excerpt: |
    The crate publicly exports Browser, BrowserConfig, Cookie, CookieStore,
    Error, Page, interception types, and request/response callback types.

- path: `https://github.com/h4ckf0r0day/obscura/wiki/Use-as-a-Rust-library`
  lines: 137-147, 150-186 (accessed 2026-09-05)
  symbol: embedded API and build model
  excerpt: |
    The guide shows Browser::builder().build(), browser.new_page().await,
    page.goto().await, page.evaluate(), selector operations, and cookie file
    persistence. It explicitly says the first build compiles V8 from source
    and recommends pinning a git tag.

- path: `https://github.com/h4ckf0r0day/obscura/wiki/Testing-and-debugging`
  lines: 140-177 (accessed 2026-09-05)
  symbol: V8 concurrency and CDP parity testing notes
  excerpt: |
    Upstream documents in-process CDP parity tests and warns that concurrent
    page use must respect a V8 lock; it also documents context and navigation
    synchronization concerns.

- path: `packages/navrules/pyproject.toml`
  lines: 1-4, 40-44
  symbol: existing PyO3/Maturin packaging precedent
  excerpt: |
    ai-parrot's navrules package uses maturin with a Rust manifest and a PyO3
    extension-module feature.

## Notes

Native embedding should be a spike with a pinned Obscura tag, build-size/time measurements, one Browser/Page wrapper, and explicit event-loop/thread safety tests. It should not be a prerequisite for the CDP integration, which uses Obscura's supported Python/Playwright interoperability path.
