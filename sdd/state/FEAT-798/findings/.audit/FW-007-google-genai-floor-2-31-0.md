---
id: FW-007
query_id: Q007
type: wiki_page
intent: "Task record of the last google-genai floor alignment — current declared floor and the introspection procedure to reuse for the next bump."
executed_at: 2026-11-04T01:39:28Z
duration_ms: 3000
parent_id: null
depth: 0
---

# FW-007 — Declared floor is google-genai>=2.31.0 in both pyprojects (TASK-4371, 2026-10-15); procedure is install → introspect → declare → uv lock → frozen sync

## Summary

Wiki page `file:sdd/tasks/completed/TASK-4371-google-genai-floor.md` (Completion Note read from the file; page truncated). On 2026-10-15 the sdd-worker introspected google-genai 2.31.0 in an isolated venv ("ALL OK"), declared `>=2.31.0` in `ai-parrot-client-google/pyproject.toml` and the `google` extra of `ai-parrot-embeddings/pyproject.toml`, and ran `uv lock --upgrade-package google-genai` (2.28.0 → 2.31.0). The policy comment block in the client pyproject (lines 17-27 at the time) requires that only an exercised version be declared. The shared venv was still on 2.24.0 and the operator was told to `uv sync` after merge. PyPI latest at that date was 2.31.0; the SDK surfaces introspected were `genai.Client`, `types.ThinkingConfig`, `types.ComputerUse`, `aio.caches.create`, `aio.live.music.connect`, `aio.aclose`, `google.genai.errors`. Whether a newer google-genai exists today (2026-11-04) is not answerable from the repo.

## Citations

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

- "Upgrade google-genai" in the request therefore means: check PyPI for a version newer than 2.31.0, and if one exists re-run the same M3 procedure; if none exists the SDK half of the request is already satisfied and only `uv sync` of the shared venv may be pending.
- [cross-lane: type=grep, intent=confirm the current floor string in both pyprojects and the resolved version in uv.lock; check whether test_reel_sdk_contract.py still hardcodes 2.23.0]
- [cross-lane: type=git_log, intent=date of the last google-genai lock bump since PR #1685]
