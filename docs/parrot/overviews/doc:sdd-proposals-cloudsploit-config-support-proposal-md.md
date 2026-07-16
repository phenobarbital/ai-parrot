---
type: Wiki Overview
title: FEAT-160 — CloudSploit toolkit — `--config CONFIG` file support for `run_scan`
id: doc:sdd-proposals-cloudsploit-config-support-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Verbatim user request preserved at `sdd/state/FEAT-160/source.md`.
relates_to:
- concept: mod:parrot.conf
  rel: mentions
---

---
id: FEAT-160
title: CloudSploit toolkit — --config CONFIG file support for run_scan
slug: cloudsploit-config-support
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-11
  summary_oneline: Add `--config CONFIG` (JS credentials file) support to CloudSploitToolkit.run_scan
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-160/
created: 2026-05-11
updated: 2026-05-11
---

# FEAT-160 — CloudSploit toolkit — `--config CONFIG` file support for `run_scan`

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-160/`](../state/FEAT-160/)

---

## 0. Origin

Verbatim user request preserved at `sdd/state/FEAT-160/source.md`.

> CloudSploit configuration. Github repository:
> https://github.com/aquasecurity/cloudsploit
>
> Current configuration of CloudSploit requires passing directly all
> credentials, region, etc, add support for config: `--config CONFIG`
> with `config` user expect to configure which configuration been applied
> to run_scan, add into Input args of run_scan the configuration file, if
> no configuration file is provided then use default credentials, else use
> the configuration file.

**Initial signals**:
- Verbs: "add support" → additive feature
- Named entities: CloudSploit, `--config`, `run_scan`
- Components / labels: cloudsploit toolkit, executor, CLI args builder
- Acceptance criteria provided: yes (implicit) — fall back to default creds when arg absent

---

## 1. Synthesis Summary

CloudSploit's `index.js` accepts `--config CONFIG` to point at a JavaScript
credentials file as an alternative to env-var credential injection. The
AI-Parrot toolkit at `parrot_tools/cloudsploit/` builds its argv via
`CloudSploitExecutor._build_cli_args` and never emits this flag — agents
have no way to substitute a config file for the per-call env-var
credentials. The fix adds a `config: Optional[str]` argument to
`CloudSploitToolkit.run_scan` (and `run_compliance_scan`), a matching
`config_file: Optional[str]` field on `CloudSploitConfig`, plumbs the value
through `executor.run_scan → _run_with_outputs → _build_cli_args`, and —
under Docker — read-only-mounts the host file under
`/cloudsploit/config/<basename>` so the in-container path resolves. Falls
through to the existing env-var path when neither call-arg nor model field
is set.

---

## 2. Codebase Findings

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py` | `CloudSploitConfig` | 81-161 | add `config_file: Optional[str] = None` (mirrors `gcp_credentials_path`) | F004 |
| 2 | `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py` | `_build_cli_args` | 109-151 | accept `config_path` kw-arg; prepend `--config=<container_path>` when set | F002 |
| 3 | `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py` | `_build_docker_command` | 59-83 | widen `volume_mount` from a single tuple to a list (config dir + output dir) | F003 |
| 4 | `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py` | `_run_with_outputs`, `run_scan`, `run_compliance_scan` | 233-360 | thread a `config` parameter; orchestrate read-only mount when present | F001, F003 |
| 5 | `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py` | `run_scan`, `run_compliance_scan` | 43-122 | add `config: Optional[str] = None` arg, falling back to `self.config.config_file` | F001 |
| 6 | `packages/ai-parrot-tools/tests/cloudsploit/test_executor.py` | (new test class) | n/a | argv + mount assertions for the new code paths | F006 |

### 2.2 Constraints Discovered

- **`--config` semantics are upstream-defined.** The file is a **JavaScript
  module** (not JSON), e.g. a copy of `config_example.js` with provider
  sections (`aws: {...}`, `azure: {...}`). When supplied, env-var
  credentials become inert.
  *Implication*: we pass the path through verbatim; no parsing or
  validation of file contents.
  *Evidence*: F005

- **In-container path discipline under Docker.** Only the in-container
  path is a legal `--config` value; the host path is invalid inside
  `aquasec/trivy`-style runs. The host directory containing the config
  file must be bind-mounted.
  *Implication*: `_run_with_outputs` must derive `(host_dir, container_dir)`
  from the user-supplied host path and feed both the mount and the rewritten
  `--config` value into the argv builder.
  *Evidence*: F003, F005

- **Read-only mount required.** Credentials files are sensitive; the
  container has no business mutating them.
  *Implication*: emit `-v <host_dir>:/cloudsploit/config:ro`.
  *Evidence*: F005

- **Existing volume-mount slot is single-tuple.** The internal
  `volume_mount: Optional[tuple[str, str]]` parameter on
  `_build_docker_command` / `execute` accepts exactly one mount. Mounting
  BOTH the temp output dir AND the config dir requires widening the type
  to `list[tuple[str, str, ...]]` (or accepting a second optional parameter).
  *Implication*: minor internal API change; only one in-tree caller
  (`_run_with_outputs`).
  *Evidence*: F003

- **Default behaviour must not regress.** When `config` is None on the
  call AND `CloudSploitConfig.config_file` is None, no `--config` argv
  appears, no new mount appears, and env-var credentials still flow.
  *Implication*: every new code path is gated on truthiness of the
  resolved config path.
  *Evidence*: F001, F002

### 2.3 Recent History (Relevant)

CloudSploit toolkit was recently migrated from `packages/ai-parrot/` to
`packages/ai-parrot-tools/`. The templates were lost in the move and
rebuilt in the same session as this proposal (see FEAT-160 sibling work
on scan_report.html / comparison_report.html). No recent functional
changes to `executor.py` outside the migration.
*Evidence*: F001

---

## 3. Probable Scope

### What's New

- **`config: Optional[str] = None` parameter** on
  `CloudSploitToolkit.run_scan` and `run_compliance_scan` — agent-tool-visible.
- **`config_file: Optional[str] = None` field** on `CloudSploitConfig` —
  instance-wide default.
- **Read-only Docker bind-mount** under `/cloudsploit/config/` for the
  parent directory of the supplied config file.
- **In-container path rewriting** so the `--config=` argv value points at
  `/cloudsploit/config/<basename>`, not the host path.

### What Changes

- **`models.py::CloudSploitConfig`** — append `config_file` field.
  *Evidence*: F004
- **`executor.py::_build_cli_args`** — accept a `config_path` kw and, if
  set, prepend `--config=<config_path>` to args.
  *Evidence*: F002
- **`executor.py::_build_docker_command`** — widen `volume_mount` to
  `Optional[list[tuple[str, str, str | None]]]` where the third optional
  element is a mode flag (`"ro"`). Tolerate the legacy single-tuple form
  for safety, or migrate the single in-tree caller atomically.
  *Evidence*: F003
- **`executor.py::_run_with_outputs`** — accept `config: Optional[str]`;
  when set, validate the path exists, derive `host_dir = dirname(config)`,
  set `container_dir = "/cloudsploit/config"`, append the read-only mount
  alongside the output-dir mount, and pass
  `config_path=f"/cloudsploit/config/{basename}"` (Docker) or `config`
  unchanged (direct-CLI mode) to `_build_cli_args`.
  *Evidence*: F001, F003
- **`executor.py::run_scan` / `run_compliance_scan`** — accept and
  forward `config`.
  *Evidence*: F001
- **`toolkit.py::run_scan` / `run_compliance_scan`** — accept `config`;
  resolve effective value as
  `effective = config if config is not None else self.config.config_file`;
  log a DEBUG message when the per-call value overrides the model default
  (both non-None and different); forward to executor.
  *Evidence*: F001

### What's Untouched (Non-Goals)

- **No JS-file parsing or validation.** We pass the path through; if
  CloudSploit rejects it, the failure surfaces in the existing
  exit-code-1 handling.
- **No autogeneration of `config.js` from `CloudSploitConfig` AWS/GCP
  fields.** The two credential-delivery paths remain orthogonal.
- **No secret-manager integration** (Vault, AWS Secrets Manager, etc.).
  The argument is a filesystem path only.
- **No multi-config-file support.** One file per call.
- **No retroactive cleanup** of the existing single-tuple `volume_mount`
  callsite beyond what's needed for the new mount.

### Patterns to Follow

- **Optional[str] path fields with parrot.conf defaults** —
  `gcp_credentials_path` is the closest precedent on
  `CloudSploitConfig`.
  *Evidence*: F004
- **Argv-builder tests inspect output directly, no Docker spin-up** —
  matches the existing `test_executor.py` patterns (govcloud, gcp,
  use_docker=False).
  *Evidence*: F006
- **Logging via `self.logger`, never `print`** — per repo convention in
  `CLAUDE.md` and existing executor code.
- **Credential masking already in `_mask_command`** — the new config-path
  argv element contains no secret (path only), so no extra masking rule
  is needed, but keep the rendering path through `_mask_command` for
  consistency.

### Integration Risks

- **Breaking change on `_build_docker_command.volume_mount` signature.**
  Internal API only (no public callers outside `_run_with_outputs`), so
  the migration is a single-file edit; still worth a deprecation note.
  *Mitigation*: accept both shapes in the transition or migrate the one
  caller atomically. *Evidence*: F003
- **`config` arg name collision with the unrelated `--compliance`/`config`
  scan-type in Trivy executor.** Different module — no actual collision —
  but worth calling out to anyone reading both toolkits side-by-side.
- **File-not-found semantics.** If the user supplies a path that doesn't
  exist, fail fast in `_run_with_outputs` with a clear error rather than
  letting CloudSploit fail opaquely after Docker spins up.
  *Mitigation*: `Path(config).is_file()` pre-flight, raise
  `FileNotFoundError` with the supplied path.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `--config` is the correct CLI flag, accepts a path to a JS module | F005 | high | upstream README usage block + dedicated §"CloudSploit Config File" |
| C2 | Current toolkit / executor never emit `--config` | F001, F002 | high | direct read of both call sites |
| C3 | `_build_docker_command` is the only place mounts are wired | F003 | high | grep confirms single helper; `_run_with_outputs` is its only caller |
| C4 | Read-only mount is appropriate for credentials | F005 | high | standard security practice + upstream treats file as input only |
| C5 | `gcp_credentials_path` is the existing precedent for path-field plumbing | F004 | high | direct read of CloudSploitConfig |
| C6 | Existing tests can be extended without Docker | F006 | high | test fixtures inspect `_build_cli_args` / `_build_docker_command` directly |
| C7 | Single-tuple `volume_mount` is the only blocker on the Docker side | F003 | high | direct read of helper signature |
| C8 | Per-call arg should win over model default | (decision) | high | resolved in §5 (user choice) |
| C9 | In-container mount path is `/cloudsploit/config/<basename>` | (decision) | high | resolved in §5 (user choice) |

Distribution: **9** high, **0** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **In-container mount path convention?**
  *Resolved*: `/cloudsploit/config/<basename>` (mirrors `_DOCKER_OUTPUT_MOUNT = "/cloudsploit/output"`).
  *Resolves claims*: C9

- [x] **Precedence when both `run_scan(config=...)` and `CloudSploitConfig.config_file` are set?**
  *Resolved*: Call-arg wins, log a DEBUG message when an override happens.
  *Resolves claims*: C8

### Unresolved (defer to spec / implementation)

_None._ Localization is high-confidence; constraints are documented; both
API-shape choices are resolved.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-160`** — *Rationale*: localization is high-confidence
across 5 files in one module, all constraints are sourced from upstream
docs or read directly, and the two API-shape choices were resolved during
proposal Q&A. The spec author can decompose this into 4-5 small tasks
without further investigation.

### Alternatives

- **`/sdd-task FEAT-160`** — if you accept the scope as-is and want to
  skip a spec, this is a contained 1-file-per-task feature (config-model,
  executor argv, executor mount-plumbing, toolkit surface, tests).
- **`/sdd-brainstorm FEAT-160`** — *not recommended*. There are no
  architectural forks to explore.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| Source (raw) | `sdd/state/FEAT-160/source.md` |
| Findings | `sdd/state/FEAT-160/findings/F001-*.md` … `F006-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-160/synthesis.json` |

**Budget consumed** (default profile):
- Files read: 4 / 40
- Grep calls: 3 / 25
- Git calls: 0 / 10
- Web fetches: 1 (upstream README)
- Truncated: **no**

**Mode determination**: explicitly classified as `enrichment` —
the request is additive (no bug to diagnose), and the codebase has clear
extension points.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Operator | Jesus Lara |
