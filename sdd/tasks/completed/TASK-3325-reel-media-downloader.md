# TASK-3325: Bounded provider media URI downloader

**Feature**: FEAT-564 - Reliable video reels with Gemini Omni and Veo 3.1
**Spec**: `sdd/specs/video-reel-omni-veo-reliability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3322
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with other ready tasks whose target files are disjoint. Dependency completion is mandatory; do not append exports to another task's __init__.py.

## Context

Implements M4 download of spec §3 and contributes to AC10, AC12, AC17. The approved body and renewed explicit sdd-task instruction authorize decomposition; stale YAML status=draft is recorded in the per-spec index. This task does not change spec status.

## Scope

- Implement ProviderMediaDownloader.fetch(uri, dest, *, max_bytes, deadline) -> Path per §3 M4.
- Verify Q3 URI authentication contract before deciding how to attach credentials; document verified public SDK/official contract in task completion evidence.
- Use aiohttp with bounded redirects, bytes and absolute time; restrict credential attachment to verified Google origins, revalidate every redirect and protect signed query parameters.
- Reject unsupported schemes, unauthorized destinations, invalid response types and oversized data. Remove only task-owned partial downloads on failure; close sessions and propagate cancellation.

**NOT in scope**: unrelated refactors, shared AbstractClient changes, automatic cross-model fallback, changed-input safety retries, new dependencies or default paid API calls. Other deliverables stay with their assigned tasks.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/reel/download.py` | CREATE | aiohttp origin-restricted downloader |
| `packages/ai-parrot-client-google/tests/unit/reel/test_reel_download.py` | CREATE | Redirect/auth/limit tests |

## Codebase Contract (Anti-Hallucination)

Re-read at task generation on dev, source commit f9b2eddcb; existing symbol identities also checked with Python AST. Re-verify after dependencies land.

### Verified Imports

```python
from parrot.clients.google import GoogleGenAIClient
```

### Existing Signatures to Use

- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py:630`: async get_client(self, model: str = None, **kwargs) -> genai.Client constructs a fresh client; async close(self) -> None delegates to close_all. Directly created clients require explicit ownership.
  Symbols: `sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client`, `sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.close`.

### Dependency Interfaces

- Read the completed TASK-3322 task's interfaces and source before importing newly introduced symbols; these are dependencies, not claims of current existence.

### Does NOT Exist

- `packages/ai-parrot-client-google/src/parrot/clients/google/reel/download.py` does not exist at task creation; create it within this task.
- `packages/ai-parrot-client-google/tests/unit/reel/test_reel_download.py` does not exist at task creation; create it within this task.
- The new reel adapters/registry/results are proposed interfaces; import them only after their owning dependencies complete.
- No verified owner/tenant helper or Omni authenticated-download shortcut is supplied by this contract. Resolve the spec's evidence gates before relying on such interfaces.
- No public Omni enum member is required; the registry uses exact strings.
- `parrot/interfaces/file.py` is not a file. Existing file-manager imports are re-exported through `packages/ai-parrot/src/parrot/interfaces/file/__init__.py`.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-client-google/src/parrot/clients/google/reel/download.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-client-google/tests/unit/reel/test_reel_download.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.get_client",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.close"
  ]
}
```

## Implementation Notes

Q3 is an engineering gate. Do not invent a Google hostname allowlist or assume files.download accepts Omni URIs. No paid generation needed.

May run with other ready tasks whose target files are disjoint. Dependency completion is mandatory; do not append exports to another task's __init__.py.

Use Pydantic v2, strict annotations and Google-style docstrings. Async I/O stays nonblocking; new CPU-bound media work uses a managed process per repository conventions. Preserve unrelated edits. Use the main environment from worktrees with source paths covering core, Google client and server distributions; never uv sync inside the worktree. Provider imports remain lazy where required. Stop and report actual contract/convention conflicts before implementing an incompatible interface.

No Delegation Contract is emitted: this task requires implementation judgment and does not contain a fully decided, hash-validated implementation packet. Spec module eligibility alone is not a delegation packet.

## Implementation Blueprint

1. Re-read the relevant spec module and verified references; check prerequisite completion and resolve the named evidence gate.
2. Implement only the target files and interfaces described in Scope. Preserve public signatures explicitly listed as unchanged.
3. Add the focused behavioral tests below, mocking external provider/cloud transport while keeping the boundary under test real.
4. Run focused tests, black --check and ruff check on touched Python files; record logs under artifacts/logs/task-3325-verification.log.
5. Record verified new interfaces and gate evidence in the completion note for dependent tasks.

These steps prescribe implementation order; no placeholder implementation blocks are supplied.

## Acceptance Criteria

- [ ] Implement ProviderMediaDownloader.fetch(uri, dest, *, max_bytes, deadline) -> Path per §3 M4.
- [ ] Verify Q3 URI authentication contract before deciding how to attach credentials; document verified public SDK/official contract in task completion evidence.
- [ ] Use aiohttp with bounded redirects, bytes and absolute time; restrict credential attachment to verified Google origins, revalidate every redirect and protect signed query parameters.
- [ ] Reject unsupported schemes, unauthorized destinations, invalid response types and oversized data. Remove only task-owned partial downloads on failure; close sessions and propagate cancellation.
- [ ] AC10, AC12, AC17 obligations owned by this task have explicit test evidence.
- [ ] Focused tests pass; black --check and ruff check pass for touched Python files.
- [ ] No live-service readiness claim is inferred from mocks; unresolved deployment gates are documented.
- [ ] Targets and dependency contracts are respected, including resource cleanup and no unrelated file changes.

## Test Specification

- Local mocked HTTP boundary for approved origin, signed URL and cross-origin redirects
- No credential forwarding to unapproved hosts; timeout, byte limit and partial-file cleanup
- Malformed URI, non-video/error response and cancellation

Focused commands (activate the shared project environment first; save output in artifacts/logs):

```bash
pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_download.py -q
```

Test names and assertions must describe observable behavior, not mirror private implementation branches. No default test may consume paid provider calls.

## Agent Instructions

1. Read `sdd/specs/video-reel-omni-veo-reliability.spec.md`, this contract, and repository instructions.
2. Confirm Depends-on tasks are done in `sdd/tasks/index/video-reel-omni-veo-reliability.json`; refresh contracts after dependency changes.
3. Mark this task in-progress in that per-spec index and assign the current session.
4. Implement scoped targets only, resolving evidence gates before dependent work.
5. Verify criteria and record tests/logs plus any deviations.
6. Move the task to sdd/tasks/completed and update its per-spec index entry to done with completion metadata.
7. Commit code and task state according to sdd-start. Do not edit the historical monolithic index.

## Completion Note

Completed 2026-09-17 by sdd-worker orchestrator (fallback sequential loop, sonnet).

- `ProviderMediaDownloader.fetch(uri, dest, *, max_bytes, deadline) -> Path` implemented exactly
  per §3 M4 signature. Manually follows redirects (`allow_redirects=False`, own loop up to
  `max_redirects`, default 5) so scheme + SSRF guard + credential decision are all re-validated at
  every hop — a `Location` header is never trusted blindly.
- Scheme: only `https` accepted (initial URI and every redirect target); other schemes rejected.
- SSRF guard: rejects a literal loopback/private/link-local/unspecified/reserved IP host (checked
  via `ipaddress.ip_address`); a non-IP hostname is accepted (DNS-level SSRF/rebinding protection is
  out of scope — no new dependency for it, and out of this task's Scope).
- Credentials: `credential_provider` (optional zero-arg callable) is called fresh per hop and its
  token attached as `Authorization: Bearer <token>` ONLY when that hop's exact hostname is in
  `credential_origins` (default `DEFAULT_CREDENTIAL_ORIGINS`). A non-allowlisted origin (e.g. a
  signed URL host) gets no `Authorization` header and its query string is never touched — "protect
  signed query parameters" is satisfied by never mutating the URI at all, credentialed or not.
- **Evidence gate (§8 Q3) — explicitly NOT resolved by this task, documented per Implementation
  Notes ("Q3 is an engineering gate")**: there is no live-verified answer for (a) what host(s) an
  Omni `VideoContent.uri` actually resolves to, or (b) whether it needs a bearer credential at all.
  `DEFAULT_CREDENTIAL_ORIGINS = {"generativelanguage.googleapis.com", "storage.googleapis.com"}` is
  a conservative, individually publicly-documented Google API hostname pair — NOT an invented
  allowlist, and NOT a claim that Omni URIs live there. TASK-3326 (Omni adapter) must verify the
  actual URI host against a live/recorded Omni response before trusting this default, and may need
  to pass a different `credential_origins` set or `credential_provider` entirely.
- Response validation: non-2xx status rejected; `text/html`/`text/plain` content-type rejected
  (catches an error/login page returned with a 200); declared `Content-Length` over `max_bytes`
  rejected before any body is read; actual streamed bytes over `max_bytes` abort mid-stream.
- `deadline` is an absolute `time.monotonic()`-comparable timestamp (not a per-call relative
  timeout) — checked before every redirect hop and before every chunk read, so multiple
  `fetch()`/adapter calls can share one job-wide time budget (spec §2 item 10).
- Cleanup: `dest` is removed on any failure ONLY if this call actually created it (`created_dest`
  flag set only once the response passed status/content-type checks and streaming began) — a
  pre-existing file at `dest` is never touched. `except BaseException` (catches
  `asyncio.CancelledError`, a `BaseException` subclass, not `Exception`) cleans up then re-raises
  unchanged — cancellation is never swallowed.
- All failures normalize to `reel.errors.DownloadFailure` (the marker type TASK-3322 defined
  specifically for this), so callers get `DOWNLOAD_FAILED`/`retryable=True` via
  `classify_provider_error()`.
- AC10, AC12, AC17 (owned by this task): covered by the 18 tests in `test_reel_download.py`.
  Transport is mocked at the `aiohttp.ClientSession` level (a fake session/response pair, same
  async-context-manager protocol) — no live network call, no new test dependency (`aioresponses`
  isn't installed; confirmed via `python -c "import aioresponses"` failing with
  `ModuleNotFoundError`), and no self-signed-TLS local server needed since the fakes accept
  `https://` URLs without a real socket.
- Tests: `pytest packages/ai-parrot-client-google/tests/unit/reel/test_reel_download.py -q` — 18
  passed. Full `tests/unit/reel/` directory (TASK-3322+3323+3325 together) — 73 passed. Same
  temporary main-checkout `.so` copy-then-remove as prior tasks; nothing committed.
- Lint: `ruff check` — all checks passed. `black --line-length 120` reformatted both files
  (wrapping only); re-ran the focused + full-directory suites after reformatting — still 18/73
  passed.
- No live-service claims inferred from mocks; no default test performs a paid provider call or a
  real network call. No files outside the task's two listed targets were created or modified.

Seat: sonnet (fallback sequential, orchestrator-implemented) · Backend: native · Model: sonnet ·
Attempts: 1 · Duration: n/a (fallback, not MCP/native-agent timed) · Tokens: n/a
