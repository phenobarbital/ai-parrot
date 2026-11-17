---
id: FC-007
query_id: Q016
type: grep
intent: "Current google-genai pins across every workspace pyproject (floor to raise) and the lock-resolved version."
executed_at: 2026-11-04T01:42:07Z
duration_ms: 400
parent_id: null
depth: 0
---

# FC-007 — google-genai floor is >=2.31.0 in both consuming packages; uv.lock resolves exactly 2.31.0

## Summary

Only two distributions declare `google-genai`: `ai-parrot-client-google` (`>=2.31.0`) and `ai-parrot-embeddings` (`>=2.31.0`), aligned by FEAT-688 / TASK-4371. Core `ai-parrot` dropped its pin in FEAT-523 (comment at line 517). The root `pyproject.toml:131` carries a comment that `google-cloud-aiplatform>=1.153` is needed for `google-genai>=2.6`. `uv.lock` resolves `google-genai == 2.31.0`, i.e. the lock sits exactly at the floor; whether a newer SDK exists upstream cannot be answered from the repo.

**Merged from FW-007 (wiki lane):** Wiki page `file:sdd/tasks/completed/TASK-4371-google-genai-floor.md` (Completion Note read from the file; page truncated). On 2026-10-15 the sdd-worker introspected google-genai 2.31.0 in an isolated venv ("ALL OK"), declared `>=2.31.0` in `ai-parrot-client-google/pyproject.toml` and the `google` extra of `ai-parrot-embeddings/pyproject.toml`, and ran `uv lock --upgrade-package google-genai` (2.28.0 → 2.31.0). The policy comment block in the client pyproject (lines 17-27 at the time) requires that only an exercised version be declared. The shared venv was still on 2.24.0 and the operator was told to `uv sync` after merge. PyPI latest at that date was 2.31.0; the SDK surfaces introspected were `genai.Client`, `types.ThinkingConfig`, `types.ComputerUse`, `aio.caches.create`, `aio.live.music.connect`, `aio.aclose`, `google.genai.errors`. Whether a newer google-genai exists today (2026-11-04) is not answerable from the repo.

## Citations

- path: `packages/ai-parrot-client-google/pyproject.toml`
  lines: 34-34
  symbol: (dependencies)
  excerpt: |
    "google-genai>=2.31.0",

- path: `packages/ai-parrot-embeddings/pyproject.toml`
  lines: 49-55
  symbol: (dependencies)
  excerpt: |
    # google-genai SDK (`from google import genai`). google-cloud-aiplatform is
    ...
    "google-genai>=2.31.0",

- path: `packages/ai-parrot/pyproject.toml`
  lines: 517-517
  symbol: (comment)
  excerpt: |
    # FEAT-523: google-genai removed — it was a stray pin core never imported

- path: `pyproject.toml`
  lines: 131-131
  symbol: (comment)
  excerpt: |
    # google-cloud-aiplatform>=1.153 (needed for google-genai>=2.6) requires

- path: `uv.lock`
  lines: 6704-6705
  symbol: (package google-genai)
  excerpt: |
    name = "google-genai"
    version = "2.31.0"

<!-- merged from FW-007 -->
- path: `sdd/tasks/completed/TASK-4371-google-genai-floor.md`
  lines: 220-226
  symbol: Completion Note
  excerpt: |
    Introspected google-genai 2.31.0 in an isolated venv (ALL OK); floor `>=2.31.0` declared in both pyprojects,
    rationale comment added, `uv lock --upgrade-package google-genai` moved 2.28.0 -> 2.31.0.
    Operator must `uv sync` in the main checkout after merge so the installed SDK (2.24.0) matches the floor.

- path: `packages/ai-parrot-client-google/pyproject.toml`
  lines: 17-27 (pre-task anchors)
  symbol: google-genai floor + policy comment
  excerpt: |
    # FEAT-564 TASK-3335: floor raised from 2.18.1 to 2.23.0 — the lowest
    # was actually run against is declared as the floor.
    "google-genai>=2.23.0",            # → now >=2.31.0

- path: `packages/ai-parrot-embeddings/pyproject.toml`
  lines: 55 (pre-task anchor)
  symbol: google extra floor
  excerpt: |
    "google-genai>=2.18.1",            # → now >=2.31.0

- path: `sdd/tasks/completed/TASK-4371-google-genai-floor.md`
  lines: 129-151
  symbol: Implementation Blueprint step 1 (introspection one-liner)
  excerpt: |
    D=$(mktemp -d) && uv venv -q "$D/v" && uv pip install -q --python "$D/v/bin/python" "google-genai==2.31.0" \
    && "$D/v/bin/python" -I - <<'PY' ... PY
    If it does not print `ALL OK`, repeat with `2.28.0` and use that version below.

- path: `packages/ai-parrot-client-google/tests/unit/reel/test_reel_sdk_contract.py`
  lines: n/a
  symbol: `TestInstalledSdkFloor.test_installed_version_meets_declared_floor`
  excerpt: |
    The installed SDK meets the declared >=2.23.0 floor.  (docstring may be stale vs 2.31.0)

## Notes

- `pip show google-genai` in the shared venv printed nothing (pip not resolvable or package absent from the shell's view) — installed version in the dev venv is unverified from this lane.
- `[cross-lane: type=git_log, intent=when did the 2.31.0 floor land and what was the previous floor (TASK-4371 commit)]`

[merged-from: FW-007] - "Upgrade google-genai" in the request therefore means: check PyPI for a version newer than 2.31.0, and if one exists re-run the same M3 procedure; if none exists the SDK half of the request is already satisfied and only `uv sync` of the shared venv may be pending.
- [cross-lane: type=grep, intent=confirm the current floor string in both pyprojects and the resolved version in uv.lock; check whether test_reel_sdk_contract.py still hardcodes 2.23.0]
- [cross-lane: type=git_log, intent=date of the last google-genai lock bump since PR #1685]
