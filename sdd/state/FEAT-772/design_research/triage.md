# Design research triage — FEAT-772 passkey-support

Model: gpt-5.6-luna (codex-cli 0.164.0) · brief: brief.md · output: suggestions.json · run: run.json
Path checks: 27 unique affected paths, all contained in the repo root and existing (`spec_tools check-path` + `test -e`).
Re-verified claims: uv.lock:9689-9690 → navigator-auth 0.28.7, no `webauthn` entry (S1 true); vite.config.ts:84 → `changeOrigin: true` (S10 true).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Pin and lock the passkey-capable navigator-auth version (risk) | CONFIRM | uv.lock behind the venv; M8 regenerates the lock | §3 M8, AC10, §7, Worktree Strategy |
| S2 | Separate public passkey calls from the generic 401 interceptor (risk) | CONFIRM | bare axios for public ceremony calls, apiClient for Bearer calls | §2, AC04, M2 |
| S3 | Specify the challenge state machine (architecture) | CONFIRM | cached usernameless challenge = conditional only; click aborts + refetches scoped | §3 M4, §7 |
| S4 | Model endpoint statuses/payloads explicitly (api) | CONFIRM | encodeURIComponent ids, 204 no body, trimmed labels, {reason} | §3 M2, §6 |
| S5 | Cross-RP management + last-login protection visible (risk) | CONFIRM | rp_id shown, refresh after mutations, 409 authoritative | §3 M5, AC05 |
| S6 | Exclude PasskeyAuth from ProviderButtons (testing) | CONFIRM | already planned; discovery test | §3 M4, AC09 |
| S7 | Separate explicit vs conditional capability checks (architecture) | CONFIRM (substance) | independent helpers + test matrix; vitest-setup.ts/package.json untouched by decision | §3 M1/M4, §4 |
| S8 | Contract test for the inline ceremony (risk) | CONFIRM (partial) | marker-level pytest only; no browser in CI | §3 M9, §4 |
| S9 | Test the route across SPA and aiohttp (testing) | CONFIRM | /account/security + /accounts lookalike in both test suites | §3 M6/M7, AC08 |
| S10 | Verify Origin through the Vite proxy (testing) | CONFIRM (manual) | changeOrigin rewrites Host only; documented manual check + both dev origins | §4, §3 M8 |
| S11 | One session-envelope persistence path (api) | CONFIRM | _storeLoginEnvelope shared | §3 M3 |
| S12 | Document startup/infra prerequisites (risk) | CONFIRM | extra, Redis, AUTH_SECRET_KEY, RP JSON, ConfigError modes | §3 M8, AC11 |

Summary: 12 confirmed · 0 rejected · 0 escalated.
