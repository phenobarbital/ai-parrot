# Tool optimizations for Claude Code and Codex (FEAT-543)

Three locally installed MCP capabilities that replace token-expensive,
predictable work: deterministic Git workflows, bounded source reading, and
delegated implementation of work whose design is already decided.

They are ordinary AI-Parrot tools (`AbstractToolkit` subclasses) exposed
through the existing local stdio MCP machinery. Each is an independent,
opt-in configuration section — none is a globally enabled built-in.

## Overview

| Toolkit | Tools | Model calls |
|---|---|---|
| `LocalGitToolkit` | `git_recent`, `git_fetch`, `git_preflight`, `git_prepare_files`, `git_pull`, `git_push` | none |
| `BoundedSourceToolkit` | `source_info`, `source_read` | none |
| `TargetedWriterToolkit` | `writer_generate`, `writer_apply` | one configured client |

### Non-goals

- Not an autonomous coding agent: the writer never explores the repository
  and never chooses a design.
- Not a guarantee that every shell read is intercepted — see
  [Host guards](#host-guards).
- No automatic commits, force pushes, resets, stashes or history rewriting.
- No claimed token-saving percentage. See [Release checklist](#release-checklist).

## Installation

Copy the example configuration and adjust `repo_root`:

```bash
cp examples/tool-optimizations-mcp.yaml .parrot/mcp-toolkits.yaml
parrot mcp-local --list
```

Serve one toolkit:

```bash
parrot mcp-local local-git --config .parrot/mcp-toolkits.yaml
```

Install the opt-in read guards (off by default):

```bash
parrot claude install --tool-guards
parrot codex install --tool-guards
parrot claude status --json      # includes a `tool_guards` block
```

Uninstall removes only the entries these commands created:

```bash
parrot claude uninstall
```

## Tool reference

### Git

| Tool | Arguments | Notes |
|---|---|---|
| `git_recent` | `ref="HEAD"`, `limit=3` (1–50) | Bounded structured history. |
| `git_fetch` | `remote="origin"`, `branch="dev"`, `recent=3` | Explicit refspec, no `+`; reports the fetched commit and freshness. |
| `git_preflight` | — | Runs every check independently and reports each one. |
| `git_prepare_files` | `paths: list[str]` | Stages exactly these files via an isolated index. Requires `confirm`. |
| `git_pull` | `remote="origin"`, `branch=None` | Fast-forward only. Requires `confirm`. |
| `git_push` | `remote="origin"`, `branch=None` | Never forced, never creates a commit, never publishes tags. Pushes the **currently checked-out** branch to the resolved remote branch; the result reports both as `branch` and `remote_branch`. Requires `confirm`. |

Mutating tools carry a required `confirm` boolean over MCP. That flag is
the host's record that a human approved the operation — it is not
authorization a model can grant itself.

#### Git refusal codes

`bare_repository`, `not_a_repository`, `root_mismatch`, `git_too_old`,
`invalid_ref`, `unknown_ref`, `unknown_remote`, `invalid_branch`,
`fetch_failed`, `fetch_rejected`, `fetch_timeout`, `tracking_ref_stale`,
`preflight_failed`, `unmerged_index`, `unrelated_staged`,
`partially_staged`, `index_unsupported`, `index_changed`, `index_locked`,
`staged_mismatch`, `whitespace_errors`, `path_not_found`,
`submodule_rejected`, `symlink_rejected`, `secret_file`,
`path_outside_root`, `directory_rejected`, `glob_rejected`,
`pathspec_magic`, `duplicate_path`, `detached_head`, `unborn_head`,
`staged_changes`, `dirty_worktree`, `missing_upstream`,
`upstream_remote_mismatch`, `branch_mismatch`, `diverged`,
`untracked_conflict`, `fast_forward_failed`, `push_rejected`,
`push_timeout`, `worktree_busy`.

**`git_push` publishes the branch you are on.** When a branch tracks a
differently-named upstream (`feature` -> `origin/dev`), the source ref is
always the current branch and the destination is the resolved remote branch.
The result reports `branch` (local) and `remote_branch` (remote) separately,
so what was published is never ambiguous.

**`git_prepare_files` never unstages anything.** If unrelated paths are
already staged it refuses with `unrelated_staged` rather than resetting the
index. Staging happens in a private copy of the index and is published only
after every check passes and Git's own `index.lock` is acquired; a refusal
leaves the index byte-identical.

### Bounded reader

A file is *large* when it exceeds **350 lines or 64,000 bytes** (either
threshold, both configurable). A large file cannot be read without an
explicit inclusive 1-based range.

```text
source_info(path)                       -> size, sha256, is_large, range_required
source_read(path, start_line, end_line, expected_sha256=None)
```

Continue through a file with the returned cursor:

```text
1. info = source_info("big.py")
2. chunk = source_read("big.py", 1, 350, expected_sha256=info.sha256)
3. while chunk.next_line: chunk = source_read("big.py", chunk.next_line,
                                              chunk.next_line + 349,
                                              expected_sha256=info.sha256)
```

`expected_sha256` makes continuation safe: if the file changed underneath
you, the read is refused with `stale_revision` instead of returning a
mixture of two revisions.

Reader error codes: `not_found`, `not_a_file`, `symlink_rejected`,
`secret_file`, `path_outside_root`, `binary_file`, `invalid_encoding`,
`range_required`, `range_too_large`, `range_out_of_bounds`,
`line_too_large`, `stale_revision`, `concurrent_modification`,
`hash_timeout`.

Only complete lines are ever returned. A single line that cannot fit the
byte budget is reported as `line_too_large` with its number — never
silently cut.

### Delegation workflow

A TASK file is eligible when it contains exactly one `## Delegation
Contract` section holding one `json` block that validates as a
`DelegationPacket`, and every implementation block it references exists in
the same file, is placeholder-free, and matches the recorded revisions.

```text
writer_generate(task_path)   -> artifact_id, patch_path, patch_sha256, usage, repairs
  read the patch with source_read, review EVERY hunk
writer_apply(artifact_id, reviewed_sha256)
  then run the acceptance tests yourself
```

Rules that matter:

- An incomplete or stale contract costs **zero** model calls.
- The delegate gets only the packet, its approved reference slices and its
  decided implementation blocks — never whole repository files, never host
  conversation history, and no tools.
- At most **one** repair attempt, and none at all for a substituted model
  or an unexpected tool call.
- Generation never modifies a target file.
- `writer_apply` re-checks the reviewed hash, the packet identity, the
  contract, staged targets and every target revision before writing
  anything. It never stages, commits or pushes, and it requires a git
  repository (it must be able to see the staged file list).

Contract error codes: `task_not_found`, `task_outside_root`,
`no_delegation_section`, `duplicate_delegation_section`, `no_packet_block`,
`duplicate_packet_block`, `invalid_packet_json`, `invalid_packet`,
`duplicate_block_id`, `missing_block`, `placeholder_code`,
`scope_path_invalid`, `target_exists_for_create`,
`target_missing_for_modify`, `stale_target`, `stale_reference`,
`reference_range_invalid`, `underspecified_create`,
`invalid_validation_command`, `context_budget_exceeded`,
`packet_too_large`.

Patch/apply codes: `not_a_patch`, `absolute_path`, `path_escape`,
`path_outside_scope`, `duplicate_target`, `deletion_rejected`,
`rename_rejected`, `mode_change_rejected`, `binary_rejected`,
`submodule_rejected`, `malformed_hunk`, `context_mismatch`,
`create_needs_dev_null`, `patch_too_large`, `artifact_tampered`,
`artifact_not_found`, `invalid_artifact_id`, `review_hash_mismatch`,
`packet_mismatch`, `staged_target`, `target_changed`, `create_collision`,
`after_hash_mismatch`, `recovery_pending`, `recovery_required`,
`model_substituted`, `unexpected_tool_call`, `deadline_exceeded`,
`no_client`.

#### Recovery

Multi-file filesystem mutation is **not globally atomic**. Applying writes
each file through an adjacent temporary file and records a journal of
before/after hashes.

- On failure, only files still matching exactly what this operation wrote
  are restored; the journal state becomes `rolled_back`.
- A file a concurrent editor has changed is **never overwritten**. It is
  marked unrecoverable, the operation returns `recovery_required`, and the
  journal is retained at
  `artifacts/tool-optimizations/<artifact-id>/journal.json`.
- A later apply of the same artifact returns `recovery_pending` until a
  human resolves it.
- Re-applying a fully applied artifact returns `already_applied` and writes
  nothing.

## Client configuration

Only the writer needs a model. Configure it through the existing
`LLMFactory`:

```yaml
targeted-writer:
  class: parrot_tools.tool_optimizations.writer.TargetedWriterToolkit
  llm: bedrock-converse:qwen3-coder-480b-a35b
  llm_kwargs:
    fallback_model: null      # REQUIRED
    max_retries: 1
    read_timeout: 120
  kwargs:
    repo_root: .
    expected_model_ids: ["qwen.qwen3-coder-480b-a35b-v1:0"]
```

- **`fallback_model: null` is required.** `BedrockConverseClient` declares
  `_fallback_model = "claude-haiku-4-5"` and applies it via `setdefault`,
  so without the explicit null the provider may answer with a different
  model. The writer's constructor **refuses** a client that still permits a
  fallback.
- Bedrock reports the *translated* model id
  (`qwen3-coder-480b-a35b` → `qwen.qwen3-coder-480b-a35b-v1:0`), so list
  the reported id in `expected_model_ids` for the identity check.
- Credentials come from the standard AWS chain. No secret ever belongs in
  this file.
- `llm_kwargs` is trusted server configuration, never an LLM-callable
  argument.

## Host guards

An opt-in `PreToolUse` hook that denies unbounded reads of large files and
replies with the exact bounded-reader call to make instead. It uses the
same thresholds as the reader, read from `.parrot/tool-guards.json`.

**The guard is a convenience, not an enforcement boundary.** The reader's
own limits hold whether or not the hook is installed, and the hook makes no
decision at all for anything outside the documented subset.

### Tested host versions

| Host | Version tested | Notes |
|---|---|---|
| Claude Code | 2.1.267 | Denial keyword `deny`. |
| Codex CLI | 0.154.0 | Denial keyword `block` — its `PreToolUseDecisionWire` enum is `approve\|block\|allow` and it rejects `deny` as an unsupported decision. |

Coverage was verified against **those versions only**. Re-test after a host
upgrade; a host that silently changes its decision enum will fail open.

### Coverage matrix

<!-- coverage-matrix:begin -->

| Form | Covered | Note |
|---|---|---|
| `Claude Read (file_path)` | yes | Structured tool input; honours a limit <= max_lines. |
| `cat FILE` | yes | Literal operand; denied when the file is large. |
| `head -n N FILE / head -N FILE` | yes | Allowed when N <= max_lines. |
| `tail -c N FILE` | yes | Allowed when N <= large_file_bytes. |
| `bare head FILE / tail FILE` | yes | Defaults to 10 lines, so bounded. |
| `less FILE / more FILE` | yes | Treated as a whole-file read. |
| `cat FILE | head -20` | yes | The reading segment decides; a pipe is not safe. |
| `cat FILE; other` | no | Compound statement — outside the parsed subset. |
| `cat $(echo FILE)` | no | Command substitution is never evaluated. |
| `cat *.py` | no | Glob expansion is the shell's, not ours. |
| `cat < FILE` | no | Redirection is outside the subset. |
| `sed -n '1,500p' FILE` | no | sed is not an intercepted program. |
| `awk 'NR<500' FILE` | no | awk is not an intercepted program. |
| `python -c "open('FILE').read()"` | no | Arbitrary interpreters are not parsed. |
| `xargs cat` | no | Operands arrive on stdin, not in the argv we can see. |
| `heredoc (<<EOF)` | no | Outside the subset. |
| `Codex write_stdin` | no | Documented host gap: it does not re-run PreToolUse. |
| `Codex hosted tools` | no | Not hookable by the host. |
| `Grep / Glob` | no | Out of scope; the guard matcher is Read|Bash. |
| `WebFetch` | no | Not a local file read. |
| `Interactive shell session input` | no | Not mediated by PreToolUse. |

<!-- coverage-matrix:end -->

Everything marked `no` keeps normal host behaviour. Notable documented
bypasses: compound statements, command substitution, globs, redirection,
`sed`/`awk`/arbitrary interpreters, `xargs`, heredocs, Codex `write_stdin`
(which does not re-run `PreToolUse`), hosted tools, and interactive shell
input.

## Measurement protocol

```bash
python -m benchmarks.tool_optimizations --scenario all --runs 1          # offline, free
python -m benchmarks.tool_optimizations --scenario all --runs 5 --live   # spends money
```

Primary tokens, delegate tokens and total tokens are reported separately;
median and p95 latency are both reported; correctness is measured by
executing the real acceptance test. Cost is `unknown` until
`benchmarks/tool_optimizations/prices.yaml` is filled in with sourced
prices. See `benchmarks/tool_optimizations/README.md`.

The optimized arm is charged `tool_schema_overhead` — the tokens the MCP tool
definitions occupy in the primary model's context, measured from the real
`tools/list` output. It is charged to the primary model, once per run (a floor:
schemas are re-sent every turn), and the baseline arm is charged zero because
the host's built-in tools cancel across arms. It is material:
`LocalGitToolkit` alone is roughly 1,880 tokens.

**Deriving a savings figure.** Compute it over `total_tokens`, never over
`primary_tokens` — delegation moves work, and moved work is not saved work.
Note also that the harness's primary-side counts are `estimate:chars_div_4`,
not provider measurements; for a defensible published number, A/B the same
task in a real host session with and without these servers configured and use
the host's own reported usage.

## Limitations and security notes

- Multi-file application is not globally atomic; see [Recovery](#recovery).
- The worktree lock is advisory (`fcntl.flock`). External Git processes do
  not honour it, which is why Git's own locks and revision checks are still
  used. The lock file is never deleted — flock is released by the kernel on
  process death, so a stale lock is impossible.
- Artifacts are stored under `artifacts/tool-optimizations/<id>/` with
  `0o700` directories and `0o600` files, and are opaque data — never
  executable commands. `artifacts/` is gitignored.
- Only approved packet slices are sent to the provider; whole repository
  files are never included in a prompt.
- `validation_commands` in a packet are data, never an execution path. No
  command from a model response is ever run.
- Secret files are refused by the same deny-list the read-only repo toolkit
  uses; `*.example` / `*.sample` / `*.template` / `*.dist` remain readable.

## Release checklist

- [ ] `pytest packages/ai-parrot-tools/tests/tool_optimizations` green.
- [ ] `pytest tests/mcp` shows no regressions against the base branch.
- [ ] `ruff check` and `black --check` clean.
- [ ] An offline benchmark report is attached, and a `--live` report if the
      deployment has provider access.
- [ ] `prices.yaml` filled in if cost figures are required.
- [ ] **Codex guard installation verified end to end.** The installer
      currently writes a Claude-shaped `.codex/hooks.json`, while
      codex-cli 0.154.0 exposes `eventName` / `timeoutSec` fields. See
      `artifacts/logs/host-smoke.json`.
- [ ] Host versions re-confirmed against the deployment's installed hosts.

**Numeric token, cost and latency targets are an owner decision** (spec
§8). This feature ships with correctness parity enforced by the benchmark
harness and reports the numbers it measured. No percentage saving is
claimed anywhere in this repository.

## Acceptance criteria traceability

| AC | Covered by |
|---|---|
| AC1 | `integration/test_stdio_protocol.py` |
| AC2 | `test_git.py`, `integration/test_git_lifecycle.py` |
| AC3 | `test_git.py` (`unrelated_staged`, `partially_staged`, index-byte assertions) |
| AC4 | `test_git.py` (pull/push), `integration/test_git_lifecycle.py` |
| AC5 | `test_reader.py` (thresholds, budget), `test_policy.py` (`fit_to_budget`) |
| AC6 | `test_reader.py` (bounded allocation, continuation, stale revision) |
| AC7 | `test_contracts.py`, `test_writer.py` (`fake.calls == []`) |
| AC8 | `tests/mcp/test_toolkit_config.py`, `tests/mcp/test_toolkit_server.py`, `integration/test_client_configuration.py` |
| AC9 | `test_writer.py`, `test_apply.py`, `test_patches.py` |
| AC10 | `test_apply.py` (rollback, recovery, idempotency), `integration/test_cross_process.py` |
| AC11 | `test_writer.py` (one repair, deadline, usage recording) |
| AC12 | `test_sdd_contracts.py` |
| AC13 | `test_hooks.py`, `test_installation.py`, `integration/test_host_smoke.py` |
| AC14 | `artifacts/logs/TASK-3091-regression.log`, ruff/black checks |
| AC15 | `docs/tool-optimizations.md`, `benchmarks/tool_optimizations/`, `test_benchmark_harness.py` |

## Related

- [Local MCP toolkits](mcp-local-toolkits.md) — the configuration and
  serving machinery this feature plugs into.
- `sdd/specs/tool-optimizations.spec.md` — the authoritative specification.
