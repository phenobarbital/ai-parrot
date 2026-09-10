---
id: F007
query_id: Q011
type: read
intent: Codex dispatcher profiles + command construction (model, sandbox, output-schema)
executed_at: 2026-09-10T01:00:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# F007 — Python-side Codex plumbing exists (FEAT-375) with read-only profile, --model and --output-schema

## Summary

The dev-loop already has a typed Codex integration: `CodexAdversarialReviewProfile` (read-only sandbox, approval never, subagent sdd-secondopinion, model default `gpt-5.5`, 600 s timeout) in `models/codex.py`, and `CodexCodeDispatcher._build_command()` / `_build_adversarial_review_command()` in `dispatchers/codex.py` which pass `--model`, `--sandbox`, `--output-schema <json>`, `-o <last-message>`, `--json`, `--ignore-user-config`. The model is sourced from `conf.DEV_LOOP_ADVERSARIAL_MODEL` (fallback `gpt-5.5`). This proves structured JSON output from Codex is a working pattern in this repo, and shows which CLI flags are trusted. The prose-command path (/sdd-spec) does not need this Python code, but should mirror its flag choices.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py`
  lines: 10-22
  symbol: CodexCodeDispatchProfile
  excerpt: |
    subagent: Literal["sdd-worker", "sdd-secondopinion"] = "sdd-worker"
    model: str = "gpt-5.5"
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"
    approval_policy: Literal["untrusted", "on-request", "never"] = "never"
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/models/codex.py`
  lines: 55-78
  symbol: CodexAdversarialReviewProfile
  excerpt: |
    subagent: Literal["sdd-secondopinion"] = "sdd-secondopinion"
    sandbox: Literal["read-only"] = "read-only"
    approval_policy: Literal["never"] = "never"
    review_scope: Literal["uncommitted", "base", "commit"] = "uncommitted"
    timeout_seconds: int = Field(default=600, ge=60, le=7200)

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py`
  lines: 240-282
  symbol: CodexCodeDispatcher._build_command
  excerpt: |
    cmd = [self.codex_bin, "exec", "--json", "--cd", cwd,
           "--model", profile.model, "--sandbox", profile.sandbox,
           "--ask-for-approval", profile.approval_policy,
           "--output-schema", schema_path, "-o", output_path]
    if profile.ignore_user_config: cmd.append("--ignore-user-config")

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py`
  lines: 298-343
  symbol: CodexCodeDispatcher._build_adversarial_review_command
  excerpt: |
    The installed CLI treats `--cd`, `--sandbox`, and `--model` as options of the
    top-level `exec` command that MUST precede the `review`/`resume` subcommand ...
    `codex exec resume` does not honor `--sandbox` ... pass `-c sandbox_mode="<mode>"`

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 980
  symbol: DEV_LOOP_ADVERSARIAL_MODEL
  excerpt: |
    DEV_LOOP_ADVERSARIAL_MODEL: str = config.get("DEV_LOOP_ADVERSARIAL_MODEL", fallback="gpt-5.5")

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py`
  lines: 273-300
  symbol: CodexAdversarialReviewDispatcher
  excerpt: |
    agent_name = "codex-adversarial"
    self._model = model or conf.DEV_LOOP_ADVERSARIAL_MODEL
    def build_review_profile(self) -> CodexAdversarialReviewProfile:
