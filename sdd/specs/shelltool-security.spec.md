# Feature Specification: ShellTool Security — Command Sanitizer

**Feature ID**: FEAT-038
**Date**: 2026-03-09
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x.x

---

## 1. Motivation & Business Requirements

### Problem Statement

The `ShellTool` (`parrot/tools/shell_tool/`) executes arbitrary shell commands on behalf of AI agents. While it has a basic security layer (`BaseAction.FORBIDDEN_PATHS` + `_validate_command` regex), the current implementation has significant gaps:

1. **Destructive commands are not blocked** — `rm -rf /`, `mkfs`, `dd`, `shred`, fork bombs, `shutdown`, `reboot` pass validation because they don't reference forbidden *paths* via the regex.
2. **Path validation is regex-only** — `FORBIDDEN_CMD_PATTERN` can be bypassed via shell expansion (`$HOME`, backticks, `$(cat /etc/passwd)`), environment variables, aliases, or symlinks.
3. **No command allowlist/denylist** — No way to restrict *which* binaries the agent can invoke.
4. **`ls` over sensitive directories** — `ListFiles` action has no path restriction; an agent can `ls /root`, `ls /etc/shadow`.
5. **File operations lack scope restriction** — `WriteFile`, `DeleteFile`, etc. validate paths via `_validate_path()` but `RunCommand` bypasses this entirely since it shells out to `/bin/sh -lc`.
6. **No working directory sandboxing** — Commands can `cd` anywhere and access the entire filesystem.
7. **No output size limiting** — A malicious command could produce gigabytes of output, exhausting memory.
8. **No per-command argument restrictions** — Even "safe" commands can be dangerous with certain flags (e.g., `find -exec`, `curl -o`, `sed -i`, `awk system()`).
9. **No risk scoring** — All violations are binary (allowed/denied); no graduated response or audit trail.

### Goals

- **G1**: Implement a **defense-in-depth** `CommandSanitizer` with a multi-layered validation pipeline.
- **G2**: Implement a **`SecurityPolicy`** dataclass with three preset levels (`RESTRICTIVE`, `MODERATE`, `PERMISSIVE`) and full configurability.
- **G3**: Implement **`CommandRule`** per-command argument restrictions (allowed/denied args, denied patterns, sandbox paths).
- **G4**: Return structured **`ValidationResult`** with verdict (`ALLOWED`/`DENIED`/`NEEDS_REVIEW`), reasons, and risk score.
- **G5**: Block destructive commands, dangerous binaries, shell expansion tricks, and pipe-to-shell patterns.
- **G6**: Enforce **path sandbox** — all path arguments must resolve under a configurable `sandbox_dir`.
- **G7**: Add output size limits to prevent memory exhaustion.
- **G8**: Integrate via **`SecureShellMixin`** for backward-compatible injection into `ShellTool`.
- **G9**: Raise **`CommandSecurityError`** (with `ValidationResult` attached) for denied commands.
- **G10**: Maintain backward compatibility — `ShellTool()` without arguments works with enhanced default policy (MODERATE).

### Non-Goals (explicitly out of scope)

- Full containerized sandbox (use `SandboxTool` with gVisor for that)
- Network-level restrictions (firewall rules, egress filtering)
- Rate limiting (deferred to future enhancement)
- Windows support — Linux/macOS only
- Replacing the existing `SandboxTool`

---

## 2. Architectural Design

### Overview

The architecture follows a clean separation: **SecurityPolicy** (configuration) → **CommandSanitizer** (validator) → **ShellTool** (executor). The sanitizer runs a 6-layer validation pipeline before any command reaches the subprocess.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ShellTool                                    │
│  (extends SecureShellMixin + AbstractTool)                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  _execute() ──► assert_command_safe(cmd)                             │
│                         │                                            │
│                         ▼                                            │
│              ┌──────────────────────┐                                │
│              │  CommandSanitizer    │                                │
│              │                      │                                │
│              │  validate(cmd) ──────┼──► ValidationResult            │
│              │   Layer 0: Sanity    │     .verdict  (ALLOWED/DENIED/ │
│              │   Layer 1: Parse     │                NEEDS_REVIEW)   │
│              │   Layer 2: Patterns  │     .reasons  (tuple[str,...]) │
│              │   Layer 3: Allow/Deny│     .risk_score (0.0 → 1.0)   │
│              │   Layer 4: Arg Rules │     .command                   │
│              │   Layer 5: Sandbox   │                                │
│              │   Layer 6: Custom    │                                │
│              └──────────┬───────────┘                                │
│                         │                                            │
│                         ▼                                            │
│              ┌──────────────────────┐                                │
│              │   SecurityPolicy     │                                │
│              │   (dataclass)        │                                │
│              │                      │                                │
│              │   .level             │  RESTRICTIVE / MODERATE /      │
│              │   .allowed_commands  │  PERMISSIVE                    │
│              │   .denied_commands   │                                │
│              │   .command_rules     │  Dict[str, CommandRule]        │
│              │   .sandbox_dir       │                                │
│              │   .allow_*           │  shell operators, chaining,    │
│              │   .denied_patterns   │  env expansion, etc.           │
│              └──────────────────────┘                                │
└─────────────────────────────────────────────────────────────────────┘
```

### Integration Points

- **`BaseAction`** — Remove inline `FORBIDDEN_PATHS` / `_validate_command()` / `_validate_path()`. Delegate to `CommandSanitizer` via the mixin.
- **`ShellTool`** — Extend `SecureShellMixin`. Call `assert_command_safe()` in `_execute()` before dispatching to actions.
- **`RunCommand`** — Validated at `ShellTool` level before action construction.
- **`ListFiles`** — Path arguments validated via sandbox layer.
- **All file actions** (`WriteFile`, `DeleteFile`, `CopyFile`, `MoveFile`) — Path validated via sandbox layer.

### Data Models

#### SecurityLevel (Enum)

```python
class SecurityLevel(str, Enum):
    RESTRICTIVE = "restrictive"   # Only explicitly allowed commands
    MODERATE = "moderate"         # Allowed commands + safe defaults
    PERMISSIVE = "permissive"     # Everything except explicitly denied
```

#### CommandVerdict (Enum)

```python
class CommandVerdict(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    NEEDS_REVIEW = "needs_review"  # For audit/confirmation workflows
```

#### ValidationResult (frozen dataclass)

```python
@dataclass(frozen=True)
class ValidationResult:
    verdict: CommandVerdict
    command: str
    reasons: Tuple[str, ...] = ()
    sanitized_command: Optional[str] = None
    risk_score: float = 0.0  # 0.0 = safe, 1.0 = critical danger
```

- `is_allowed` / `is_denied` — convenience properties
- Risk thresholds: `>= 0.7` → DENIED, `>= 0.4` → NEEDS_REVIEW, `< 0.4` → ALLOWED

#### CommandRule (dataclass)

Per-command argument restrictions:

```python
@dataclass
class CommandRule:
    name: str
    allowed_args: Optional[Set[str]] = None       # Allowlist for flags/subcommands
    denied_args: Set[str] = field(default_factory=set)
    denied_patterns: List[str] = field(default_factory=list)  # Regex on full command
    max_args: Optional[int] = None
    require_absolute_path: bool = False
    sandbox_paths: Optional[List[str]] = None     # Per-command sandbox override
    allow_pipe: bool = False
    allow_redirect: bool = False
    risk_base: float = 0.0                        # Base risk score
```

Default rules for common commands:

| Command | Denied Args | Denied Patterns | Risk Base |
|---|---|---|---|
| `curl` | `-o`, `--output`, `-O` | `file://`, `gopher://`, `dict://` | 0.3 |
| `wget` | — | `file://`, `--post-data`, `--post-file` | 0.3 |
| `find` | `-exec`, `-execdir`, `-ok`, `-delete` | — | 0.2 |
| `python`/`python3` | — | `-c.*(?:import os\|subprocess\|exec\|eval)` | 0.4 |
| `pip` | `--target`, `--prefix`, `--root` | — | 0.3 |
| `sed` | `-i` | — | 0.2 |
| `awk` | — | `system\s*\(`, `getline` | 0.3 |
| `git` | — | — | 0.1 |
| `cp`, `mv` | — | — | 0.2/0.3 |

#### SecurityPolicy (dataclass)

```python
@dataclass
class SecurityPolicy:
    level: SecurityLevel = SecurityLevel.MODERATE

    # Command access control
    allowed_commands: Set[str] = field(default_factory=set)
    denied_commands: Set[str] = field(default_factory=set)
    command_rules: Dict[str, CommandRule] = field(default_factory=dict)

    # Sandbox
    sandbox_dir: Optional[str] = None

    # Limits
    max_command_length: int = 4096
    max_output_bytes: int = 1_048_576    # 1 MB
    max_stderr_bytes: int = 262_144      # 256 KB

    # Shell feature toggles
    allow_shell_operators: bool = False   # pipes, redirects
    allow_chaining: bool = False          # ;, &&, ||
    allow_env_expansion: bool = False     # $VAR, ${VAR}
    allow_command_substitution: bool = False  # $(...), `...`
    allow_glob: bool = True

    # Custom deny patterns (regex)
    denied_patterns: List[str] = field(default_factory=list)

    # Audit
    audit_log: bool = True
```

**Factory methods with preset configurations:**

| Method | Level | Allowed Commands | Shell Operators | Chaining | Env Expansion | Cmd Substitution | Max Length |
|---|---|---|---|---|---|---|---|
| `SecurityPolicy.restrictive()` | RESTRICTIVE | User-provided only | No | No | No | No | 2048 |
| `SecurityPolicy.moderate()` | MODERATE | User + safe defaults* | Yes (pipes) | No | No | No | 4096 |
| `SecurityPolicy.permissive()` | PERMISSIVE | All except denied | Yes | Yes | Yes | No | 8192 |

*Safe defaults for MODERATE:
```
ls, cat, head, tail, wc, grep, find, echo, date, whoami, pwd, env,
printenv, uname, sort, uniq, cut, awk, sed, tr, tee, diff, md5sum,
sha256sum, file, stat, python3, python, pip, node, npm, git, curl,
wget, mkdir, cp, mv, touch
```

**Default denied commands** (all levels):
```
rm, rmdir, shred, dd, mkfs, fdisk, parted, mount, umount,
sudo, su, doas, pkexec, chown, chgrp, chmod,
nc, ncat, netcat, nmap, socat, telnet, ssh, scp, sftp, rsync,
bash, sh, zsh, fish, csh, tcsh, ksh, perl, ruby, lua, php,
systemctl, service, init, reboot, shutdown, halt, poweroff,
kill, killall, pkill,
apt, apt-get, dpkg, yum, dnf, snap, flatpak, brew,
passwd, chpasswd, useradd, userdel, usermod, visudo, crontab, at,
base64, xxd, od,
docker, podman, lxc, qemu, nsenter, unshare, chroot
```

### Validation Pipeline (6 Layers)

```
Command Input
    │
    ▼
Layer 0: Basic Sanity
    ├── Empty → ALLOWED
    ├── Length > max_command_length → DENIED (risk 0.8)
    │
    ▼
Layer 1: Parse & Extract
    ├── shlex.split() → tokens
    ├── Extract base_cmd = os.path.basename(tokens[0])
    ├── Parse error → DENIED (risk 0.7)
    │
    ▼
Layer 2: Dangerous Pattern Detection
    ├── Command substitution $(...), `...`
    ├── Process substitution <(...), >(...)
    ├── Chaining ;, &&, ||
    ├── Pipes |
    ├── Redirects >, >>
    ├── Env expansion $VAR, ${VAR}
    ├── Path traversal ../
    ├── Sensitive files /etc/passwd, /etc/shadow
    ├── Kernel/device access /proc/, /sys/, /dev/
    ├── eval, exec, source builtins
    ├── xargs (arbitrary command execution)
    ├── Device node creation
    │   (each pattern has own risk score; policy toggles filter allowed patterns)
    │
    ▼
Layer 3: Command Access Control
    ├── RESTRICTIVE: not in allowed_commands → DENIED (0.9)
    ├── MODERATE: in denied_commands → DENIED (0.9)
    │             not in allowed_commands → DENIED (0.7)
    ├── PERMISSIVE: in denied_commands → DENIED (0.9)
    │
    ▼
Layer 4: Per-Command Argument Rules
    ├── Check CommandRule.denied_args
    ├── Check CommandRule.denied_patterns
    ├── Check CommandRule.max_args
    │
    ▼
Layer 5: Path Sandbox Enforcement
    ├── For each path-like token in args:
    │   ├── Resolve relative to sandbox_dir
    │   ├── Verify resolved path is under sandbox_dir
    │   └── Outside sandbox → risk 0.8
    │
    ▼
Layer 6: Custom Denied Patterns
    ├── Apply SecurityPolicy.denied_patterns regexes
    │
    ▼
Final Verdict
    ├── risk >= 0.7 → DENIED
    ├── risk >= 0.4 → NEEDS_REVIEW
    └── risk <  0.4 → ALLOWED
```

### Integration Mixin

```python
class SecureShellMixin:
    _sanitizer: Optional[CommandSanitizer] = None

    def set_security_policy(self, policy: SecurityPolicy) -> None:
        self._sanitizer = CommandSanitizer(policy)

    def validate_command(self, command: str) -> ValidationResult:
        if self._sanitizer is None:
            return ValidationResult(verdict=CommandVerdict.ALLOWED, command=command)
        return self._sanitizer.validate(command)

    def assert_command_safe(self, command: str) -> None:
        result = self.validate_command(command)
        if result.is_denied or result.verdict == CommandVerdict.NEEDS_REVIEW:
            raise CommandSecurityError(f"Command denied: {command!r}", result=result)
```

### CommandSecurityError

```python
class CommandSecurityError(Exception):
    def __init__(self, message: str, result: ValidationResult):
        super().__init__(message)
        self.result = result
```

---

## 3. Implementation

### File Structure

```
parrot/tools/shell_tool/
├── __init__.py          # MODIFY — export new classes
├── models.py            # MODIFY — remove FORBIDDEN_PATHS, inject CommandSanitizer
├── security.py          # CREATE — SecurityPolicy, CommandSanitizer, CommandRule,
│                        #          ValidationResult, SecureShellMixin, etc.
├── actions.py           # MODIFY — delegate validation, add output truncation
├── tool.py              # MODIFY — extend SecureShellMixin, accept security_policy
└── engine.py            # (no changes)
```

### Code Changes

| File | Action | Description |
|---|---|---|
| `parrot/tools/shell_tool/security.py` | CREATE | All security classes: `SecurityLevel`, `CommandVerdict`, `ValidationResult`, `CommandRule`, `SecurityPolicy`, `CommandSanitizer`, `SecureShellMixin`, `CommandSecurityError`, default deny lists, default command rules, dangerous pattern registry |
| `parrot/tools/shell_tool/models.py` | MODIFY | Remove `BaseAction.FORBIDDEN_PATHS`, `FORBIDDEN_CMD_PATTERN`, `_validate_path()`, `_validate_command()`. Add `CommandSanitizer` as optional constructor param on `BaseAction`. |
| `parrot/tools/shell_tool/actions.py` | MODIFY | `RunCommand._run_impl()` calls sanitizer before subprocess. `ListFiles._run_impl()` validates path via sandbox layer. Output truncation in `_run_subprocess()`. |
| `parrot/tools/shell_tool/tool.py` | MODIFY | `ShellTool` extends `SecureShellMixin`. Constructor accepts `security_policy: Optional[SecurityPolicy]`. Defaults to `SecurityPolicy.moderate()`. Calls `assert_command_safe()` in `_execute()`. |
| `parrot/tools/shell_tool/__init__.py` | MODIFY | Export `SecurityPolicy`, `SecurityLevel`, `CommandSanitizer`, `ValidationResult`, `CommandVerdict`, `CommandRule`, `CommandSecurityError`, `SecureShellMixin` |

### Output Truncation

In `BaseAction._run_subprocess()`, after collecting stdout/stderr buffers, truncate if policy limits are set:

```python
if sanitizer and len(stdout_bytes) > sanitizer.policy.max_output_bytes:
    stdout_bytes = stdout_bytes[:sanitizer.policy.max_output_bytes]
    stdout_bytes += b"\n[OUTPUT TRUNCATED: exceeded limit]"
```

### Example Usage

```python
# Default (MODERATE) — recommended for most agents
tool = ShellTool()  # auto-creates SecurityPolicy.moderate()

# Restrictive — only explicitly allowed commands
policy = SecurityPolicy.restrictive(
    allowed_commands={"git", "python3", "ls", "cat", "grep", "echo"},
    sandbox_dir="/home/agent/workspace",
)
tool = ShellTool(security_policy=policy)

# Moderate with custom sandbox
policy = SecurityPolicy.moderate(
    sandbox_dir="/home/agent/workspace",
)
tool = ShellTool(security_policy=policy)

# Permissive — trusted environment (use with caution)
policy = SecurityPolicy.permissive(
    sandbox_dir="/home/agent/workspace",
)
tool = ShellTool(security_policy=policy)

# Direct sanitizer usage (without ShellTool)
sanitizer = CommandSanitizer(SecurityPolicy.moderate())
result = sanitizer.validate("rm -rf /")
print(result)  # ❌ [denied] 'rm -rf /' — command 'rm' is explicitly denied
print(result.risk_score)  # 0.9

result = sanitizer.validate("git status")
print(result)  # ✅ [allowed] 'git status' — OK

# Batch validation
results = sanitizer.validate_batch(["ls -la", "rm -rf /", "echo hello"])
for r in results:
    print(r)
```

---

## 4. Testing

### Unit Tests — SecurityPolicy & Presets

| Test | Description |
|---|---|
| `test_restrictive_preset_defaults` | Verify restrictive preset field values |
| `test_moderate_preset_defaults` | Verify moderate preset includes safe defaults |
| `test_permissive_preset_defaults` | Verify permissive preset allows chaining/env |
| `test_moderate_safe_defaults_contains_expected` | `git`, `python3`, `ls`, etc. in allowed |
| `test_custom_allowed_commands_merged` | Custom commands merged with safe defaults |
| `test_default_denied_commands_comprehensive` | All expected dangerous commands in denylist |

### Unit Tests — CommandSanitizer Validation

| Test | Description |
|---|---|
| `test_deny_rm_rf` | `rm -rf /` → DENIED |
| `test_deny_rm_recursive` | `rm -r /tmp/x` → DENIED |
| `test_deny_dd` | `dd if=/dev/zero of=/dev/sda` → DENIED |
| `test_deny_mkfs` | `mkfs.ext4 /dev/sda` → DENIED |
| `test_deny_fork_bomb` | `:(){:\|:&};:` → DENIED |
| `test_deny_shutdown` | `shutdown -h now` → DENIED |
| `test_deny_sudo` | `sudo anything` → DENIED |
| `test_deny_eval` | `eval "rm -rf /"` → DENIED |
| `test_deny_command_substitution` | `cat $(echo /etc/passwd)` → DENIED |
| `test_deny_backtick_expansion` | `` cat `echo /etc/passwd` `` → DENIED |
| `test_deny_process_substitution` | `diff <(cat /etc/passwd) <(cat /etc/shadow)` → DENIED |
| `test_deny_sensitive_paths` | `/etc/passwd`, `/etc/shadow` in command → DENIED |
| `test_deny_kernel_fs_access` | `/proc/`, `/sys/`, `/dev/` → DENIED |
| `test_deny_pipe_to_shell` | `cat file \| bash` → DENIED (via denied_commands) |
| `test_allow_safe_git` | `git status` → ALLOWED |
| `test_allow_safe_python` | `python3 --version` → ALLOWED |
| `test_allow_safe_echo` | `echo hello world` → ALLOWED |
| `test_allow_safe_ls` | `ls -la` → ALLOWED |
| `test_command_length_limit` | 5000-char command → DENIED |
| `test_malformed_command_denied` | Unterminated quotes → DENIED |
| `test_empty_command_allowed` | Empty string → ALLOWED |

### Unit Tests — CommandRule Argument Restrictions

| Test | Description |
|---|---|
| `test_curl_deny_output_flag` | `curl -o /tmp/file url` → DENIED |
| `test_curl_deny_file_protocol` | `curl file:///etc/passwd` → DENIED |
| `test_find_deny_exec_flag` | `find . -exec rm {} \;` → DENIED |
| `test_find_deny_delete_flag` | `find . -name "*.tmp" -delete` → DENIED |
| `test_sed_deny_inplace` | `sed -i 's/a/b/' file` → DENIED |
| `test_awk_deny_system_call` | `awk '{system("rm file")}'` → DENIED |
| `test_python_deny_dangerous_c_flag` | `python3 -c "import os; os.system('rm -rf /')"` → DENIED |
| `test_pip_deny_target_flag` | `pip install --target /usr pkg` → DENIED |

### Unit Tests — Path Sandbox

| Test | Description |
|---|---|
| `test_sandbox_allows_paths_inside` | Path under sandbox_dir → ALLOWED |
| `test_sandbox_denies_paths_outside` | Absolute path outside sandbox → DENIED |
| `test_sandbox_denies_traversal` | `../../etc/passwd` → DENIED |
| `test_sandbox_ignores_urls` | `https://example.com` not treated as path |
| `test_sandbox_skips_flags` | `-o`, `--verbose` not treated as paths |

### Unit Tests — SecurityLevel Behavior

| Test | Description |
|---|---|
| `test_restrictive_denies_unlisted` | Unlisted command → DENIED |
| `test_restrictive_allows_listed` | Listed command → ALLOWED |
| `test_moderate_denies_denied_cmd` | Denied command → DENIED |
| `test_moderate_denies_unlisted_cmd` | Unlisted command → DENIED (0.7) |
| `test_moderate_allows_safe_default` | Safe default command → ALLOWED |
| `test_permissive_allows_unlisted` | Unlisted command → ALLOWED |
| `test_permissive_denies_denied_cmd` | Denied command → DENIED |

### Unit Tests — ValidationResult

| Test | Description |
|---|---|
| `test_result_is_frozen` | Cannot mutate ValidationResult fields |
| `test_result_str_format` | `__str__` shows status emoji + verdict |
| `test_result_risk_score_range` | Risk score always 0.0 to 1.0 |
| `test_batch_validation` | `validate_batch()` returns list of results |

### Unit Tests — Integration with ShellTool

| Test | Description |
|---|---|
| `test_shell_tool_default_moderate_policy` | Default ShellTool uses MODERATE |
| `test_shell_tool_rejects_rm_rf` | `rm -rf /` raises `CommandSecurityError` |
| `test_shell_tool_allows_echo` | `echo hello` executes normally |
| `test_shell_tool_plan_validates_each_step` | Plan mode validates per-step |
| `test_shell_tool_custom_policy` | Custom policy overrides defaults |
| `test_shell_tool_no_policy_backward_compat` | `SecureShellMixin` with no sanitizer allows all |
| `test_command_security_error_has_result` | Exception `.result` is a `ValidationResult` |
| `test_output_truncation_at_limit` | Output > max_output_bytes truncated |

### Unit Tests — Backward Compatibility

| Test | Description |
|---|---|
| `test_old_forbidden_paths_still_blocked` | All old `FORBIDDEN_PATHS` entries blocked |
| `test_old_forbidden_cmd_pattern_covered` | Regex patterns from old code still caught |

---

## 5. Metrics & Success Criteria

### Acceptance Criteria

- [ ] `SecurityPolicy` dataclass with `RESTRICTIVE`/`MODERATE`/`PERMISSIVE` factory methods
- [ ] `CommandSanitizer` with 6-layer `validate(cmd)` → `ValidationResult` pipeline
- [ ] `CommandRule` per-command argument restrictions with default rules for 10+ commands
- [ ] `ValidationResult` with `verdict`, `reasons`, `risk_score`, `is_allowed`/`is_denied`
- [ ] `CommandVerdict` enum: `ALLOWED`, `DENIED`, `NEEDS_REVIEW`
- [ ] `SecureShellMixin` with `set_security_policy()`, `validate_command()`, `assert_command_safe()`
- [ ] `CommandSecurityError` exception with `.result: ValidationResult`
- [ ] Default denied commands: 50+ dangerous binaries across 10 categories
- [ ] Default dangerous patterns: 20+ regex patterns with individual risk scores
- [ ] Shell expansion (`$(...)`, backticks) blocked by default in RESTRICTIVE and MODERATE
- [ ] Pipe/redirect controlled via `allow_shell_operators` toggle
- [ ] Chaining (`;`, `&&`, `||`) controlled via `allow_chaining` toggle
- [ ] Path sandbox enforcement via `sandbox_dir`
- [ ] Output truncation at configurable `max_output_bytes`/`max_stderr_bytes`
- [ ] `BaseAction.FORBIDDEN_PATHS` and `_validate_command()` removed, replaced by sanitizer
- [ ] `ShellTool` extends `SecureShellMixin`, defaults to `SecurityPolicy.moderate()`
- [ ] Backward compatible — existing `ShellTool()` gets MODERATE policy (superset of old behavior)
- [ ] 50+ unit tests covering all layers, all security levels, all command rules
- [ ] No ruff lint errors

### Security Guarantees

| Threat | Layer | Mitigation |
|---|---|---|
| `rm -rf /` | L3 (deny) | `rm` in default denied_commands |
| `cat /etc/shadow` | L2 (pattern) | Sensitive file pattern (risk 0.95) |
| `ls /root` | L2 (pattern) | Kernel/device fs pattern |
| `$(cat /etc/passwd)` | L2 (pattern) | Command substitution pattern (risk 0.9) |
| `eval "dangerous"` | L2+L3 | eval pattern (L2) + eval in denylist (L3) |
| `sudo rm -rf /` | L3 (deny) | `sudo` in denied_commands |
| `curl file:///etc/passwd` | L4 (rule) | curl denied_patterns blocks `file://` |
| `find . -exec rm {} \;` | L4 (rule) | find denied_args blocks `-exec` |
| `python3 -c "import os; os.system(...)"` | L4 (rule) | python denied_patterns |
| `awk '{system("rm")}'` | L4 (rule) | awk denied_patterns blocks `system(` |
| Path traversal `../../etc` | L5 (sandbox) | Resolved path outside sandbox_dir |
| Fork bomb `:(){:\|:&};:` | L2 (pattern) | Chaining pattern (risk 0.7) |
| Memory exhaustion via output | Runtime | Output truncation at max_output_bytes |
| Command injection via length | L0 (sanity) | max_command_length enforced |

---

## 6. Open Questions

1. **Should `NEEDS_REVIEW` be treated as DENIED in automated contexts?** The reference implementation treats it as DENIED in `assert_command_safe()`. This is the safe default. Consider making it configurable for interactive agents that can prompt the user: yes, treated as DENIED-
2. **Should `rm` (non-recursive, single file) be allowed in PERMISSIVE mode?** Currently blocked in all modes. Could add a `CommandRule` for `rm` that only allows it without `-r`/`-f`/`-R` flags: if we can check that "rm" is not removing an entire directory or files in system directories, allowed in permissive mode.
3. **Should we validate pipe chains per-segment?** In MODERATE mode, pipes are allowed (`allow_shell_operators=True`) but we should validate each segment's base command against the allow/deny lists. The current design does this via pattern detection but doesn't split on `|` for per-segment command checking: yes, for "pipes", we need to evaluate each segment of pipe command.

---

## 7. Migration Notes

- `BaseAction.FORBIDDEN_PATHS`, `BaseAction.FORBIDDEN_CMD_PATTERN`, `BaseAction._validate_path()`, and `BaseAction._validate_command()` will be removed.
- `ShellTool` gains `SecureShellMixin` and defaults to `SecurityPolicy.moderate()`.
- The default MODERATE policy is **strictly more restrictive** than the old `FORBIDDEN_PATHS` regex — it adds command denylists, pattern detection, and argument rules on top.
- If any agent relies on commands now blocked by default (e.g., `chmod`, `ssh`, `docker`), their configuration must pass a custom `SecurityPolicy` to `ShellTool`.
- The `SecureShellMixin` with `_sanitizer = None` allows all commands (backward compat for code that creates `ShellTool` and explicitly sets no policy).
