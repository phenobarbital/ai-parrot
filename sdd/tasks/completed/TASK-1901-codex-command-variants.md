# TASK-1901: Codex `exec review` / `resume` command variants

**Feature**: FEAT-375 — Codex CLI Adversarial Second-Opinion Agent
**Spec**: `sdd/specs/codex-cli-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1899
**Assigned-to**: unassigned

---

## Context

Module 3 of FEAT-375 (spec §3, goals G5+G6). `CodexCodeDispatcher._build_command`
today emits only one shape: `codex exec --json …`. The adversarial profile
needs `codex exec review` scopes (uncommitted default, `--base <ref>`,
`--commit <sha>`) and `codex exec resume --last` continuations — table-driven
and unit-tested, because the CLI surface is external and may drift.

---

## Scope

- MODIFY `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py`:
  - Extend `_build_command()` (lines 1119-1151): when the profile is a
    `CodexAdversarialReviewProfile`:
    - `review_scope == "uncommitted"` → `codex exec review --json …` (no scope flag)
    - `review_scope == "base"` → append `--base <profile.review_base>`
    - `review_scope == "commit"` → append `--commit <profile.review_commit>`
    - `resume_last is True` → `codex exec resume --last …` and **omit
      `--sandbox`** (the `resume` subcommand rejects it); pass
      `-c sandbox_mode="read-only"` instead.
    - Keep `--cd`, `--model`, `--output-schema`, `-o`, `--ignore-user-config`
      behavior identical for all shapes.
  - Keep the shape table in one place (module-level dict or small helper) so
    tests can enumerate it.
  - **Implementation-time verification** (spec §8 open question): run
    `codex exec review --help` against the installed CLI. If `review` does not
    support `--json`/`--output-schema`, implement the specified fallback:
    build `codex exec --json` and embed the diff in the prompt (obtain diff
    via `git diff` / `git diff <base>...` / `git show <sha>` in cwd) — the
    caller-visible contract (structured verdict from the `-o` file) must be
    identical either way. Record which path was taken in the Completion Note.
- Validation: raise `ValueError` at profile-use time if `review_scope=="base"`
  with empty `review_base`, or `"commit"` with empty `review_commit`.
- Unit tests for every command shape (see Test Specification).

**NOT in scope**: the dispatchers that use these profiles (TASK-1902), QANode
(TASK-1903), any change to `dispatch()` control flow, event streaming, or the
worktree guard.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py` | MODIFY | `_build_command` shape table + validation |
| `packages/ai-parrot/tests/flows/dev_loop/test_codex_command_variants.py` | CREATE | unit tests per shape |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-26 on `dev` @ `ec6e0432a`.

### Verified Imports
```python
from parrot.flows.dev_loop.dispatcher import CodexCodeDispatcher       # dispatcher.py:936
from parrot.flows.dev_loop.models import CodexCodeDispatchProfile      # models.py:540
from parrot.flows.dev_loop.models import CodexAdversarialReviewProfile # created by TASK-1899 — verify it landed
```

### Existing Signatures to Use
```python
# dispatcher.py:1119-1151 — current single shape (baseline that MUST keep working)
def _build_command(self, *, profile: CodexCodeDispatchProfile, cwd: str,
                   schema_path: str, output_path: str, prompt: str) -> List[str]:
    cmd = [self.codex_bin, "exec", "--json", "--cd", cwd,
           "--model", profile.model, "--sandbox", profile.sandbox,
           "--ask-for-approval", profile.approval_policy,
           "--output-schema", schema_path, "-o", output_path]
    if profile.ignore_user_config: cmd.append("--ignore-user-config")   # 1146-1147
    if profile.ignore_rules: cmd.append("--ignore-rules")               # 1148-1149
    cmd.append(prompt)                                                  # 1150

# dispatcher.py:951-958
def __init__(self, *, max_concurrent: int, redis_url: str,
             stream_ttl_seconds: int, codex_bin: str = "codex") -> None

# dispatcher.py:968-978 — dispatch() calls _build_command at :1008-1014; do not change its signature
```

### Does NOT Exist
- ~~any `exec review` / `resume` call site in the codebase~~ — grep-verified absent; this task creates the shapes.
- ~~`--skip-git-repo-check` usage~~ — not used, not needed (cwd is always a git worktree).
- ~~`--sandbox` on `codex exec resume`~~ — the subcommand REJECTS it; use `-c sandbox_mode="read-only"`.
- ~~`CodexCodeDispatcher.build_review_command()`~~ — no such public method; extend the private `_build_command`.

---

## Implementation Notes

### Pattern to Follow
Keep `_build_command` a pure function of `(profile, paths, prompt)` — no I/O —
so shape tests need no subprocess. `isinstance(profile, CodexAdversarialReviewProfile)`
selects the variant; plain `CodexCodeDispatchProfile` keeps the byte-identical
legacy shape (assert in tests).

### Key Constraints
- The legacy shape must remain byte-identical for non-adversarial profiles —
  FEAT-270/323 tests depend on it.
- Table-driven: severity of CLI drift is contained to one table + tests.
- `resume` shape still writes structured output via `-o`.

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/test_code_review.py` — fake-binary + command assertions pattern

---

## Acceptance Criteria

- [ ] Legacy shape byte-identical for `CodexCodeDispatchProfile` (regression test)
- [ ] `uncommitted`/`base`/`commit` shapes correct, incl. required-arg validation
- [ ] `resume_last=True` shape contains `resume --last`, NO `--sandbox`, and `-c sandbox_mode="read-only"`
- [ ] CLI capability verified (`codex exec review --help`) and fallback path implemented if needed; choice recorded in Completion Note
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_codex_command_variants.py -v` passes
- [ ] Existing dev_loop suite green; `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_codex_command_variants.py
import pytest
from parrot.flows.dev_loop.dispatcher import CodexCodeDispatcher
from parrot.flows.dev_loop.models import (
    CodexAdversarialReviewProfile, CodexCodeDispatchProfile,
)

@pytest.fixture
def dispatcher():
    return CodexCodeDispatcher(max_concurrent=1, redis_url="redis://x", stream_ttl_seconds=60)

def _cmd(dispatcher, profile):
    return dispatcher._build_command(profile=profile, cwd="/wt", schema_path="/s.json",
                                     output_path="/o.json", prompt="P")

def test_legacy_shape_unchanged(dispatcher):
    cmd = _cmd(dispatcher, CodexCodeDispatchProfile())
    assert cmd[:3] == ["codex", "exec", "--json"] and "review" not in cmd

def test_review_uncommitted_default(dispatcher):
    cmd = _cmd(dispatcher, CodexAdversarialReviewProfile())
    assert "--sandbox" in cmd and "read-only" in cmd  # read-only enforced

def test_review_base_and_commit(dispatcher):
    b = _cmd(dispatcher, CodexAdversarialReviewProfile(review_scope="base", review_base="dev"))
    assert "--base" in b and "dev" in b
    c = _cmd(dispatcher, CodexAdversarialReviewProfile(review_scope="commit", review_commit="abc123"))
    assert "--commit" in c and "abc123" in c

def test_scope_requires_target(dispatcher):
    with pytest.raises(ValueError):
        _cmd(dispatcher, CodexAdversarialReviewProfile(review_scope="base"))

def test_resume_no_sandbox_flag(dispatcher):
    cmd = _cmd(dispatcher, CodexAdversarialReviewProfile(resume_last=True))
    assert "resume" in cmd and "--last" in cmd
    assert "--sandbox" not in cmd
    assert any(a.startswith('sandbox_mode=') or 'sandbox_mode="read-only"' in a for a in cmd)
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 3, §7 gotchas)
2. **Check dependencies** — TASK-1899 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/codex-cli-agent.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

**CLI verification (installed `codex-cli 0.145.0`):** ran `codex exec
review --help` and `codex exec resume --help` against the real installed
binary.

- `--json`, `--output-schema <FILE>`, `-o <FILE>`, `--ignore-user-config`,
  `--ignore-rules` ARE supported by both `review` and `resume`. **No
  fallback needed** — shipped the primary path (`codex exec review`/`codex
  exec resume` with structured output), not the `exec --json` +
  embedded-diff fallback.
- Additional CLI-surface finding beyond what the spec anticipated: `--cd`,
  `--sandbox`, `--model` are options of the top-level `exec` command and
  MUST be placed BEFORE the `review`/`resume` subcommand token — passing
  them after (as subcommand args) is a hard parse error
  (`error: unexpected argument '--sandbox' found`). Implemented
  `_build_adversarial_review_command` accordingly (global opts first, then
  the subcommand, then subcommand-level opts).
- There is no `--ask-for-approval`/`-a` flag anywhere under `codex exec`
  in this installed CLI version (only under the top-level interactive
  `codex` command) — confirmed via full `--help` dump. The new
  review/resume shapes therefore never emit `--ask-for-approval` (nothing
  to emit it as); this is asserted by
  `test_adversarial_profile_never_emits_ask_for_approval`. **Note**: this
  also means the EXISTING legacy `_build_command()` branch (unchanged by
  this task, using `--ask-for-approval` for bare `codex exec`) would
  likely fail against this same installed CLI version — a pre-existing
  CLI-drift risk already flagged by the spec's "Known Risks" section,
  strictly out of scope for Module 3 (legacy shape is required to stay
  byte-identical) and not touched here.
- Followed the task's explicit (and test-enforced) instruction that
  `resume` omits `--sandbox` and uses `-c sandbox_mode="<mode>"` instead —
  this matches the documented `CLAUDE.md` gotcha even though `--sandbox`
  positioned before the subcommand parses without error; the gotcha is
  about resume's *effective* sandbox at the session-continuation level,
  not clap parsing, so the config-override form was kept exactly as
  specified.
- `_REVIEW_SCOPE_FLAGS` is the table (class attribute) mapping
  `review_scope` → CLI flag, per the "table-driven" requirement; unit
  tests exercise every entry plus the required-target validation.

Verification: `pytest packages/ai-parrot/tests/flows/dev_loop/ -q` →
625 passed, 1 pre-existing failure (`test_models_module_is_pure`, same
known ordering-pollution issue noted in TASK-1899/1900), 5 skipped.
`ruff check` clean on both touched files.

No divergence from the task spec; no files touched outside the declared
list; legacy `_build_command` shape untouched and covered by a regression
test (`test_legacy_shape_unchanged`).
