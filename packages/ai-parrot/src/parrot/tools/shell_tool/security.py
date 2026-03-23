"""ShellTool Security — Command Sanitizer (FEAT-038).

Provides multi-layered security validation for shell commands
before execution, using an allowlist-first approach with configurable
security policies.

Architecture:
    SecurityPolicy (config) → CommandSanitizer (validator) → ShellTool (executor)

Layers:
    0. Basic sanity (empty, length)
    1. Parse & extract base command
    2. Dangerous pattern detection (metacharacters, injection vectors)
    3. Command allow/deny list enforcement by SecurityLevel
    4. Per-command argument restrictions (CommandRule)
    5. Path traversal / sandbox enforcement
    6. Custom denied patterns
"""
from __future__ import annotations

import logging
import os
import re
import shlex
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# =============================================================================
# Enums
# =============================================================================


class SecurityLevel(str, Enum):
    """Security policy levels."""

    RESTRICTIVE = "restrictive"   # Only explicitly allowed commands
    MODERATE = "moderate"         # Allowed commands + safe defaults
    PERMISSIVE = "permissive"     # Everything except explicitly denied


class CommandVerdict(str, Enum):
    """Result of command validation."""

    ALLOWED = "allowed"
    DENIED = "denied"
    NEEDS_REVIEW = "needs_review"  # Treated as DENIED in automated contexts


# =============================================================================
# ValidationResult
# =============================================================================


@dataclass(frozen=True)
class ValidationResult:
    """Immutable result of command validation.

    Attributes:
        verdict: Final decision for the command.
        command: The original command string that was validated.
        reasons: Tuple of human-readable reasons for the verdict.
        sanitized_command: Optional cleaned version of the command (reserved for future use).
        risk_score: Aggregate risk score in range [0.0, 1.0].
            0.0 = completely safe, 1.0 = critical danger.
    """

    verdict: CommandVerdict
    command: str
    reasons: Tuple[str, ...] = ()
    sanitized_command: Optional[str] = None
    risk_score: float = 0.0

    @property
    def is_allowed(self) -> bool:
        """Return True if the command is allowed to execute."""
        return self.verdict == CommandVerdict.ALLOWED

    @property
    def is_denied(self) -> bool:
        """Return True if the command was denied."""
        return self.verdict == CommandVerdict.DENIED

    def __str__(self) -> str:
        """Return a human-readable summary with status emoji."""
        status = "✅" if self.is_allowed else "❌"
        reasons_str = "; ".join(self.reasons) if self.reasons else "OK"
        return f"{status} [{self.verdict.value}] {self.command!r} — {reasons_str}"


# =============================================================================
# CommandRule
# =============================================================================


@dataclass
class CommandRule:
    """Per-command security rule for argument-level restrictions.

    Attributes:
        name: The command this rule applies to (e.g. "curl", "find").
        allowed_args: If set, only these flags/subcommands are permitted.
        denied_args: These flags are always denied regardless of context.
        denied_patterns: Regex patterns applied to the full command string.
            Any match denies the command.
        max_args: Maximum number of arguments (excluding the command itself).
        require_absolute_path: If True, path arguments must be absolute.
        sandbox_paths: If set, path arguments must be under one of these dirs.
            Inherits global sandbox_dir if None.
        allow_pipe: Allow this command to appear in pipe chains.
        allow_redirect: Allow output redirection for this command.
        risk_base: Base risk score contribution (0.0–1.0) added when this
            command is used. Individual violations add on top of this.
    """

    name: str
    allowed_args: Optional[Set[str]] = None
    denied_args: Set[str] = field(default_factory=set)
    denied_patterns: List[str] = field(default_factory=list)
    max_args: Optional[int] = None
    require_absolute_path: bool = False
    sandbox_paths: Optional[List[str]] = None
    allow_pipe: bool = False
    allow_redirect: bool = False
    risk_base: float = 0.0


# =============================================================================
# CommandSecurityError
# =============================================================================


class CommandSecurityError(Exception):
    """Raised when a command fails security validation.

    Attributes:
        result: The ValidationResult that triggered the denial.

    Example:
        try:
            shell_tool.assert_command_safe("rm -rf /")
        except CommandSecurityError as exc:
            print(exc.result.reasons)
            print(exc.result.risk_score)
    """

    def __init__(self, message: str, result: ValidationResult) -> None:
        """Initialise with a message and the validation result.

        Args:
            message: Human-readable description of the denial.
            result: The ValidationResult that caused the error.
        """
        super().__init__(message)
        self.result = result


# =============================================================================
# Default denied commands
# =============================================================================

_DEFAULT_DENIED_COMMANDS: Set[str] = {
    # Destructive / system-altering
    "rm", "rmdir", "shred", "dd",
    "mkfs", "fdisk", "parted", "mount", "umount", "wipefs",
    # Privilege escalation
    "sudo", "su", "doas", "pkexec",
    "chown", "chgrp", "chmod",
    # Network attack surface
    "nc", "ncat", "netcat", "nmap", "socat",
    "telnet", "ssh", "scp", "sftp", "rsync",
    # Interpreters / shells (prevent shell escape)
    "bash", "sh", "zsh", "fish", "csh", "tcsh", "ksh", "dash",
    "perl", "ruby", "lua", "php",
    # System management
    "systemctl", "service", "init",
    "reboot", "shutdown", "halt", "poweroff",
    "kill", "killall", "pkill",
    # Package managers (prevent installing backdoors)
    "apt", "apt-get", "dpkg", "yum", "dnf", "pacman",
    "snap", "flatpak", "brew",
    # Credential / config access
    "passwd", "chpasswd", "useradd", "userdel", "usermod",
    "groupadd", "groupdel", "groupmod",
    "visudo", "crontab", "at",
    # Dangerous data exfiltration / encoding
    "base64", "xxd", "od",
    # Container / VM escape
    "docker", "podman", "lxc", "lxd", "qemu", "qemu-system-x86_64",
    "nsenter", "unshare", "chroot",
    # Filesystem / disk
    "losetup", "cryptsetup", "lvm", "vgcreate", "lvcreate",
    # Dangerous utilities
    "eval", "exec",
    "xargs",
}

# =============================================================================
# Safe default commands for MODERATE policy
# =============================================================================

_MODERATE_SAFE_DEFAULTS: Set[str] = {
    "ls", "cat", "head", "tail", "wc", "grep", "find", "echo",
    "date", "whoami", "pwd", "env", "printenv", "uname",
    "sort", "uniq", "cut", "awk", "sed", "tr", "tee",
    "diff", "md5sum", "sha256sum", "file", "stat",
    "python3", "python", "pip", "node", "npm",
    "git", "curl", "wget",
    "mkdir", "cp", "mv", "touch",
    "which", "type", "true", "false",
    "test", "[",
    "printf", "read",
    "basename", "dirname", "realpath",
    "zip", "unzip", "tar", "gzip", "gunzip",
    "jq", "column",
    "less", "more", "strings",
    "ps", "top", "df", "du", "free",
    "hostname", "id",
}


# =============================================================================
# Default per-command rules
# =============================================================================

def _default_command_rules() -> Dict[str, CommandRule]:
    """Return default per-command security rules for MODERATE/PERMISSIVE policies.

    Returns:
        Mapping of command name to its CommandRule.
    """
    return {
        "curl": CommandRule(
            name="curl",
            denied_args={"-o", "--output", "-O", "--remote-name"},
            denied_patterns=[
                r"file://",       # Local file access via curl
                r"gopher://",     # SSRF vector
                r"dict://",       # SSRF vector
                r"ldap://",       # SSRF vector
            ],
            risk_base=0.3,
        ),
        "wget": CommandRule(
            name="wget",
            denied_patterns=[
                r"file://",
                r"--post-data",
                r"--post-file",
            ],
            risk_base=0.3,
        ),
        "git": CommandRule(
            name="git",
            risk_base=0.1,
        ),
        "find": CommandRule(
            name="find",
            denied_args={"-exec", "-execdir", "-ok", "-okdir", "-delete"},
            risk_base=0.2,
        ),
        "cp": CommandRule(
            name="cp",
            sandbox_paths=None,  # Inherits global sandbox_dir
            risk_base=0.2,
        ),
        "mv": CommandRule(
            name="mv",
            sandbox_paths=None,
            risk_base=0.3,
        ),
        "python3": CommandRule(
            name="python3",
            denied_patterns=[
                r"-c\s+.*(?:import\s+os|import\s+subprocess|shutil\.rmtree|exec\s*\(|eval\s*\()",
            ],
            risk_base=0.4,
        ),
        "python": CommandRule(
            name="python",
            denied_patterns=[
                r"-c\s+.*(?:import\s+os|import\s+subprocess|shutil\.rmtree|exec\s*\(|eval\s*\()",
            ],
            risk_base=0.4,
        ),
        "pip": CommandRule(
            name="pip",
            allowed_args={"install", "list", "show", "freeze", "search", "download", "check"},
            denied_args={"--target", "--prefix", "--root"},
            risk_base=0.3,
        ),
        "sed": CommandRule(
            name="sed",
            denied_args={"-i"},   # In-place editing can be destructive
            risk_base=0.2,
        ),
        "awk": CommandRule(
            name="awk",
            denied_patterns=[r"system\s*\(", r"\bgetline\b"],
            risk_base=0.3,
        ),
        "rm": CommandRule(
            name="rm",
            # Explicit single-flag denylist
            denied_args={"-r", "-R", "--recursive", "-f", "--force"},
            # Catch combined flags containing r, R, or f (e.g. -rf, -fr, -rfi)
            denied_patterns=[r"-[a-zA-Z]*[rRf]"],
            risk_base=0.6,  # Elevated but below denial threshold when args pass
        ),
    }


# =============================================================================
# SecurityPolicy
# =============================================================================


@dataclass
class SecurityPolicy:
    """Configurable security policy for ShellTool command execution.

    Three preset factory methods are available covering the most common
    use cases. For fine-grained control, instantiate directly and set
    individual fields.

    Attributes:
        level: The broad security level governing default allow/deny behaviour.
        allowed_commands: Commands explicitly permitted. In RESTRICTIVE mode
            only these commands may run. In MODERATE mode these are merged
            with the safe defaults.
        denied_commands: Commands explicitly denied regardless of level.
        command_rules: Per-command argument restrictions keyed by command name.
        sandbox_dir: If set, all path arguments must resolve under this directory.
        max_command_length: Maximum number of characters in a single command.
        max_output_bytes: Maximum stdout bytes collected before truncation.
        max_stderr_bytes: Maximum stderr bytes collected before truncation.
        allow_shell_operators: Allow pipe (|) and output redirect (>, >>).
        allow_chaining: Allow command chaining (;, &&, ||).
        allow_env_expansion: Allow environment variable expansion ($VAR, ${VAR}).
        allow_command_substitution: Allow $(...) and backtick substitution.
        allow_glob: Allow glob patterns (*, ?, [...]).
        denied_patterns: Extra regex patterns applied to every command string.
        audit_log: Log all validation decisions at WARNING level when denied.

    Example:
        >>> policy = SecurityPolicy.restrictive(
        ...     allowed_commands={"git", "python3", "ls"},
        ...     sandbox_dir="/home/agent/workspace",
        ... )
        >>> sanitizer = CommandSanitizer(policy)
        >>> result = sanitizer.validate("rm -rf /")
        >>> result.is_denied
        True
    """

    level: SecurityLevel = SecurityLevel.MODERATE

    # Command access control
    allowed_commands: Set[str] = field(default_factory=set)
    denied_commands: Set[str] = field(default_factory=lambda: _DEFAULT_DENIED_COMMANDS.copy())
    command_rules: Dict[str, CommandRule] = field(default_factory=_default_command_rules)

    # Sandbox
    sandbox_dir: Optional[str] = None

    # Resource limits
    max_command_length: int = 4096
    max_output_bytes: int = 1_048_576    # 1 MB
    max_stderr_bytes: int = 262_144      # 256 KB

    # Shell feature toggles
    allow_shell_operators: bool = False   # pipes and redirects
    allow_chaining: bool = False          # ;, &&, ||
    allow_env_expansion: bool = False     # $VAR, ${VAR}
    allow_command_substitution: bool = False  # $(...), `...`
    allow_glob: bool = True

    # Custom denied patterns (regex strings)
    denied_patterns: List[str] = field(default_factory=list)

    # Audit
    audit_log: bool = True

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def restrictive(
        cls,
        allowed_commands: Optional[Set[str]] = None,
        sandbox_dir: Optional[str] = None,
        command_rules: Optional[Dict[str, CommandRule]] = None,
    ) -> SecurityPolicy:
        """Create a restrictive policy — only explicitly allowed commands run.

        This is the recommended default for AI agent tools where the set of
        permitted operations is known in advance.

        Args:
            allowed_commands: Exact set of commands the agent may execute.
            sandbox_dir: All path arguments must resolve under this directory.
            command_rules: Per-command argument rules (defaults to empty dict
                in restrictive mode to avoid unexpected complexity).

        Returns:
            A SecurityPolicy configured for maximum restriction.
        """
        return cls(
            level=SecurityLevel.RESTRICTIVE,
            allowed_commands=allowed_commands or set(),
            denied_commands=set(),        # Denylist is irrelevant; allowlist wins
            command_rules=command_rules or {},
            sandbox_dir=sandbox_dir,
            max_command_length=2048,
            allow_shell_operators=False,
            allow_chaining=False,
            allow_env_expansion=False,
            allow_command_substitution=False,
            allow_glob=False,
            denied_patterns=[],
            audit_log=True,
        )

    @classmethod
    def moderate(
        cls,
        allowed_commands: Optional[Set[str]] = None,
        sandbox_dir: Optional[str] = None,
    ) -> SecurityPolicy:
        """Create a moderate policy — safe defaults plus user-specified commands.

        Pipes are permitted but chaining (;, &&, ||) and variable/command
        expansion are blocked. Per-command argument rules apply.

        Args:
            allowed_commands: Additional commands to permit on top of the
                built-in safe defaults. Merged with ``_MODERATE_SAFE_DEFAULTS``.
            sandbox_dir: All path arguments must resolve under this directory.

        Returns:
            A SecurityPolicy configured for moderate restriction.
        """
        merged = _MODERATE_SAFE_DEFAULTS.copy()
        if allowed_commands:
            merged.update(allowed_commands)
        return cls(
            level=SecurityLevel.MODERATE,
            allowed_commands=merged,
            denied_commands=_DEFAULT_DENIED_COMMANDS.copy(),
            command_rules=_default_command_rules(),
            sandbox_dir=sandbox_dir,
            max_command_length=4096,
            allow_shell_operators=True,          # pipes allowed
            allow_chaining=False,
            allow_env_expansion=False,
            allow_command_substitution=False,
            allow_glob=True,
            denied_patterns=[],
            audit_log=True,
        )

    @classmethod
    def permissive(
        cls,
        denied_commands: Optional[Set[str]] = None,
        sandbox_dir: Optional[str] = None,
    ) -> SecurityPolicy:
        """Create a permissive policy — everything allowed except denied commands.

        Chaining and environment variable expansion are permitted. Command
        substitution remains blocked. Use only in trusted environments.

        Args:
            denied_commands: Commands to deny. Defaults to
                ``_DEFAULT_DENIED_COMMANDS``.
            sandbox_dir: All path arguments must resolve under this directory.

        Returns:
            A SecurityPolicy configured for minimal restriction.
        """
        # Build the effective denied set; if the caller passes a custom set,
        # use it as-is. Otherwise start from the defaults and remove "rm" so
        # that single-file deletion is permitted (guarded by CommandRule below).
        if denied_commands is not None:
            effective_denied = denied_commands
        else:
            effective_denied = _DEFAULT_DENIED_COMMANDS.copy()
            effective_denied.discard("rm")

        # Extend command rules with the rm rule so permissive mode still
        # enforces restrictions on recursive/force flags.
        rules = _default_command_rules()  # rm CommandRule is already included

        return cls(
            level=SecurityLevel.PERMISSIVE,
            allowed_commands=set(),
            denied_commands=effective_denied,
            command_rules=rules,
            sandbox_dir=sandbox_dir,
            max_command_length=8192,
            allow_shell_operators=True,
            allow_chaining=True,
            allow_env_expansion=True,
            allow_command_substitution=False,   # Still dangerous even in permissive
            allow_glob=True,
            denied_patterns=[],
            audit_log=True,
        )


# =============================================================================
# Dangerous shell patterns registry
# =============================================================================

# Each entry: (regex_pattern, human_description, risk_score)
_DANGEROUS_PATTERNS: List[Tuple[str, str, float]] = [
    # Command substitution
    (r"\$\(", "command substitution $(…)", 0.9),
    (r"`[^`]+`", "backtick command substitution", 0.9),
    # Process substitution
    (r"<\(", "process substitution <(…)", 0.8),
    (r">\(", "process substitution >(…)", 0.8),
    # Command chaining
    (r";\s*\S", "command chaining with ;", 0.7),
    (r"\|\|", "OR chaining ||", 0.6),
    (r"&&", "AND chaining &&", 0.6),
    # Pipes and redirects
    (r"\|(?!\|)", "pipe operator |", 0.3),
    (r">\s*>?", "output redirection >/ >>", 0.5),
    # Environment expansion
    (r"\$\{[^}]+\}", "variable expansion ${…}", 0.5),
    (r"\$[A-Za-z_][A-Za-z0-9_]*", "environment variable $VAR", 0.4),
    # Path traversal
    (r"\.\./", "path traversal ../", 0.7),
    # Sensitive system files
    (r"/etc/(?:passwd|shadow|sudoers|gshadow|master\.passwd)", "sensitive system files", 0.95),
    # Kernel / device filesystem access
    (r"/proc/", "kernel filesystem /proc/", 0.8),
    (r"/sys/", "kernel filesystem /sys/", 0.8),
    (r"/dev/(?!null|zero|urandom|random)", "device filesystem /dev/", 0.8),
    # Dangerous builtins
    (r"\beval\s", "eval builtin", 0.9),
    (r"\bexec\s", "exec builtin", 0.9),
    (r"\bsource\s|(?:^|;|&&|\|\|)\s*\.\s+\S", "source/dot command", 0.8),
    # Arbitrary execution helpers
    (r"\bxargs\s", "xargs (can execute arbitrary commands)", 0.7),
    # Device node creation
    (r"(?:mk|mknod)\s+.*/dev/", "device node creation", 0.95),
    # Escape sequences that could obfuscate commands
    (r"\\x[0-9a-fA-F]{2}", "hex escape sequences", 0.6),
]


# =============================================================================
# CommandSanitizer
# =============================================================================

_logger = logging.getLogger(__name__)


class CommandSanitizer:
    """Multi-layered command sanitizer for ShellTool integration.

    Runs a 6-layer validation pipeline to check a command string against the
    configured ``SecurityPolicy`` before it reaches the subprocess.

    Architecture:
        SecurityPolicy (config) → CommandSanitizer (validator) → ShellTool (executor)

    Layers:
        0. Basic sanity (empty, length)
        1. Parse & extract base command (shlex)
        2. Dangerous pattern detection (metacharacters, injection vectors)
        3. Command allow/deny list enforcement by SecurityLevel
        4. Per-command argument restrictions (CommandRule)
        5. Path traversal / sandbox enforcement
        6. Custom denied patterns

    Example:
        >>> policy = SecurityPolicy.moderate(sandbox_dir="/home/agent/workspace")
        >>> sanitizer = CommandSanitizer(policy)
        >>> result = sanitizer.validate("rm -rf /")
        >>> result.is_denied
        True
        >>> result = sanitizer.validate("git status")
        >>> result.is_allowed
        True
    """

    def __init__(self, policy: SecurityPolicy) -> None:
        """Initialise the sanitizer, pre-compiling all regex patterns.

        Args:
            policy: The security policy governing validation behaviour.
        """
        self.policy = policy
        # Pre-compile dangerous patterns for performance
        self._compiled_patterns: List[Tuple[re.Pattern, str, float]] = [
            (re.compile(pat), desc, score)
            for pat, desc, score in _DANGEROUS_PATTERNS
        ]
        # Pre-compile custom denied patterns
        self._compiled_denied: List[re.Pattern] = [
            re.compile(pat) for pat in self.policy.denied_patterns
        ]
        # Pre-resolve sandbox dir once
        self._sandbox_resolved: Optional[Path] = None
        if self.policy.sandbox_dir:
            self._sandbox_resolved = Path(self.policy.sandbox_dir).resolve()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, command: str) -> ValidationResult:
        """Validate a command string through all 6 security layers.

        Args:
            command: The raw command string to validate.

        Returns:
            A ``ValidationResult`` with the verdict, reasons, and risk score.
        """
        reasons: List[str] = []
        risk_score: float = 0.0
        raw = command.strip()

        # ------------------------------------------------------------------
        # Layer 0: Basic sanity
        # ------------------------------------------------------------------
        if not raw:
            return ValidationResult(
                verdict=CommandVerdict.ALLOWED,
                command=raw,
                reasons=("empty command",),
                risk_score=0.0,
            )

        if len(raw) > self.policy.max_command_length:
            return self._deny(
                raw,
                [f"command exceeds max length ({len(raw)} > {self.policy.max_command_length})"],
                0.8,
            )

        # ------------------------------------------------------------------
        # Layer 1: Parse & extract base command
        # ------------------------------------------------------------------
        try:
            tokens = shlex.split(raw)
        except ValueError as exc:
            return self._deny(
                raw,
                [f"malformed command (shlex parse error: {exc})"],
                0.7,
            )

        if not tokens:
            return ValidationResult(
                verdict=CommandVerdict.ALLOWED,
                command=raw,
                risk_score=0.0,
            )

        base_cmd = self._extract_base_command(tokens[0])

        # ------------------------------------------------------------------
        # Layer 2: Dangerous pattern detection
        # ------------------------------------------------------------------
        pattern_reasons, pattern_risk = self._check_patterns(raw)
        for reason in pattern_reasons:
            if not self._is_pattern_allowed(reason):
                reasons.append(reason)
                risk_score = max(risk_score, pattern_risk)

        # ------------------------------------------------------------------
        # Layer 3: Command access control
        # ------------------------------------------------------------------
        cmd_reasons, cmd_risk = self._check_command_access(base_cmd)
        if cmd_reasons:
            reasons.extend(cmd_reasons)
            risk_score = max(risk_score, cmd_risk)
            # Hard deny: known-dangerous command — no need to check further
            if cmd_risk >= 0.9:
                result = self._deny(raw, reasons, risk_score)
                self._audit(result)
                return result

        # Pipe-chain per-segment validation (Open Q3 resolution)
        if self.policy.allow_shell_operators and "|" in raw:
            pipe_reasons, pipe_risk = self._check_pipe_segments(raw)
            if pipe_reasons:
                reasons.extend(pipe_reasons)
                risk_score = max(risk_score, pipe_risk)

        # ------------------------------------------------------------------
        # Layer 4: Per-command argument rules
        # ------------------------------------------------------------------
        rule = self.policy.command_rules.get(base_cmd)
        if rule:
            arg_reasons, arg_risk = self._check_command_rule(rule, tokens[1:], raw)
            if arg_reasons:
                reasons.extend(arg_reasons)
                risk_score = max(risk_score, arg_risk)

        # ------------------------------------------------------------------
        # Layer 5: Path sandbox enforcement
        # ------------------------------------------------------------------
        if self._sandbox_resolved:
            path_reasons, path_risk = self._check_path_sandbox(tokens)
            if path_reasons:
                reasons.extend(path_reasons)
                risk_score = max(risk_score, path_risk)

        # ------------------------------------------------------------------
        # Layer 6: Custom denied patterns
        # ------------------------------------------------------------------
        for idx, compiled in enumerate(self._compiled_denied):
            if compiled.search(raw):
                reasons.append(f"matches custom denied pattern #{idx}")
                risk_score = max(risk_score, 0.8)

        # ------------------------------------------------------------------
        # Final verdict
        # ------------------------------------------------------------------
        if risk_score >= 0.7:
            result = self._deny(raw, reasons, risk_score)
        elif risk_score >= 0.4:
            result = ValidationResult(
                verdict=CommandVerdict.NEEDS_REVIEW,
                command=raw,
                reasons=tuple(reasons),
                risk_score=risk_score,
            )
        else:
            result = ValidationResult(
                verdict=CommandVerdict.ALLOWED,
                command=raw,
                reasons=tuple(reasons),
                risk_score=risk_score,
            )

        self._audit(result)
        return result

    def validate_batch(self, commands: List[str]) -> List[ValidationResult]:
        """Validate multiple commands, returning one result per command.

        Args:
            commands: List of raw command strings to validate.

        Returns:
            List of ``ValidationResult`` in the same order as ``commands``.
        """
        return [self.validate(cmd) for cmd in commands]

    # ------------------------------------------------------------------
    # Internal validation layers
    # ------------------------------------------------------------------

    def _extract_base_command(self, token: str) -> str:
        """Extract the base command name from a token, stripping leading path.

        Args:
            token: The first shell token (may be an absolute path like
                ``/usr/bin/ls``).

        Returns:
            The basename, e.g. ``"ls"``.
        """
        return os.path.basename(token)

    def _check_patterns(self, command: str) -> Tuple[List[str], float]:
        """Layer 2: match command against pre-compiled dangerous patterns.

        Args:
            command: The raw command string.

        Returns:
            Tuple of (list of triggered reason strings, max risk score seen).
        """
        reasons: List[str] = []
        max_risk = 0.0
        for compiled, desc, risk in self._compiled_patterns:
            if compiled.search(command):
                reasons.append(f"dangerous pattern: {desc}")
                max_risk = max(max_risk, risk)
        return reasons, max_risk

    def _is_pattern_allowed(self, reason: str) -> bool:
        """Check whether a triggered pattern is permitted by the current policy.

        Args:
            reason: The human-readable reason string from pattern detection.

        Returns:
            True if the policy explicitly allows this pattern type.
        """
        p = self.policy
        if "pipe operator" in reason and p.allow_shell_operators:
            return True
        if "output redirection" in reason and p.allow_shell_operators:
            return True
        if "chaining" in reason and p.allow_chaining:
            return True
        if ("OR chaining" in reason or "AND chaining" in reason) and p.allow_chaining:
            return True
        if "environment variable" in reason and p.allow_env_expansion:
            return True
        if "variable expansion" in reason and p.allow_env_expansion:
            return True
        if "command substitution" in reason and p.allow_command_substitution:
            return True
        if "backtick" in reason and p.allow_command_substitution:
            return True
        return False

    def _check_command_access(self, base_cmd: str) -> Tuple[List[str], float]:
        """Layer 3: enforce command allow/deny list based on SecurityLevel.

        Args:
            base_cmd: The base command name (already basename-stripped).

        Returns:
            Tuple of (list of reason strings, risk score).
        """
        reasons: List[str] = []
        risk = 0.0
        level = self.policy.level

        if level == SecurityLevel.RESTRICTIVE:
            if base_cmd not in self.policy.allowed_commands:
                reasons.append(f"command '{base_cmd}' not in allowlist")
                risk = 0.9
        elif level == SecurityLevel.MODERATE:
            if base_cmd in self.policy.denied_commands:
                reasons.append(f"command '{base_cmd}' is explicitly denied")
                risk = 0.9
            elif base_cmd not in self.policy.allowed_commands:
                reasons.append(f"command '{base_cmd}' not in allowlist (moderate mode)")
                risk = 0.7
        elif level == SecurityLevel.PERMISSIVE:
            if base_cmd in self.policy.denied_commands:
                reasons.append(f"command '{base_cmd}' is explicitly denied")
                risk = 0.9

        return reasons, risk

    def _check_pipe_segments(self, command: str) -> Tuple[List[str], float]:
        """Validate each segment of a pipe chain against the command access list.

        Called only when ``allow_shell_operators=True`` (MODERATE / PERMISSIVE).
        Splits on ``|`` and validates the base command of each segment.

        Args:
            command: The full raw command string containing ``|``.

        Returns:
            Tuple of (reason strings, max risk score) for any denied segments.
        """
        reasons: List[str] = []
        max_risk = 0.0
        for segment in command.split("|"):
            segment = segment.strip()
            if not segment:
                continue
            try:
                seg_tokens = shlex.split(segment)
            except ValueError:
                continue
            if not seg_tokens:
                continue
            seg_cmd = self._extract_base_command(seg_tokens[0])
            seg_reasons, seg_risk = self._check_command_access(seg_cmd)
            if seg_reasons:
                reasons.extend(seg_reasons)
                max_risk = max(max_risk, seg_risk)
        return reasons, max_risk

    def _check_command_rule(
        self,
        rule: CommandRule,
        args: List[str],
        raw_command: str,
    ) -> Tuple[List[str], float]:
        """Layer 4: enforce per-command argument restrictions from a CommandRule.

        Args:
            rule: The ``CommandRule`` for the current command.
            args: Argument tokens (everything after the command name).
            raw_command: The full raw command string (for pattern matching).

        Returns:
            Tuple of (reason strings, risk score).
        """
        reasons: List[str] = []
        risk = rule.risk_base

        # Max args check
        if rule.max_args is not None and len(args) > rule.max_args:
            reasons.append(
                f"too many arguments for '{rule.name}' "
                f"({len(args)} > {rule.max_args})"
            )
            risk = max(risk, 0.5)

        # Argument denylist
        for arg in args:
            clean_arg = arg.split("=")[0] if "=" in arg else arg
            if clean_arg in rule.denied_args:
                reasons.append(
                    f"denied argument '{clean_arg}' for '{rule.name}'"
                )
                risk = max(risk, 0.8)

        # Per-command denied patterns (applied to full raw command)
        for pattern in rule.denied_patterns:
            if re.search(pattern, raw_command):
                reasons.append(
                    f"matches denied pattern for '{rule.name}': {pattern}"
                )
                risk = max(risk, 0.7)

        return reasons, risk

    def _check_path_sandbox(self, tokens: List[str]) -> Tuple[List[str], float]:
        """Layer 5: verify all path-like arguments resolve inside sandbox_dir.

        Args:
            tokens: All shell tokens (index 0 is the command; 1+ are arguments).

        Returns:
            Tuple of (reason strings, max risk score) for out-of-sandbox paths.
        """
        if not self._sandbox_resolved:
            return [], 0.0

        reasons: List[str] = []
        risk = 0.0

        for token in tokens[1:]:   # Skip the command itself
            if token.startswith("-"):
                continue  # Skip flags
            if "://" in token:
                continue  # Skip URLs
            if token in (".", ".."):
                continue  # Relative refs — validated at execution time

            # Only check tokens that look like filesystem paths
            if "/" not in token and not token.startswith(".."):
                continue

            try:
                if not Path(token).is_absolute():
                    resolved = (self._sandbox_resolved / token).resolve()
                else:
                    resolved = Path(token).resolve()
                resolved.relative_to(self._sandbox_resolved)
            except ValueError:
                reasons.append(
                    f"path '{token}' resolves outside sandbox "
                    f"'{self._sandbox_resolved}'"
                )
                risk = max(risk, 0.8)
            except (OSError, RuntimeError):
                reasons.append(f"cannot resolve path '{token}'")
                risk = max(risk, 0.5)

        return reasons, risk

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _deny(
        command: str,
        reasons: List[str],
        risk: float,
    ) -> ValidationResult:
        """Construct a DENIED ValidationResult.

        Args:
            command: The command that was denied.
            reasons: List of human-readable denial reasons.
            risk: Aggregate risk score.

        Returns:
            A frozen ``ValidationResult`` with verdict ``DENIED``.
        """
        return ValidationResult(
            verdict=CommandVerdict.DENIED,
            command=command,
            reasons=tuple(reasons),
            risk_score=risk,
        )

    def validate_path(self, path: str) -> ValidationResult:
        """Validate a filesystem path against sandbox and dangerous path patterns.

        Lightweight check for file-oriented actions (``WriteFile``, ``ReadFile``,
        etc.) that receive a path string rather than a full command string.

        Checks applied:
            1. Dangerous path patterns (sensitive files, kernel fs, traversal).
            2. Sandbox enforcement (if ``sandbox_dir`` is configured).

        Args:
            path: The filesystem path to validate.

        Returns:
            A ``ValidationResult`` with the verdict and any triggered reasons.
        """
        reasons: List[str] = []
        risk = 0.0
        path_kws = {"sensitive", "kernel", "path traversal", "device"}

        for compiled, desc, pat_risk in self._compiled_patterns:
            if any(kw in desc for kw in path_kws) and compiled.search(path):
                reasons.append(f"dangerous path pattern: {desc}")
                risk = max(risk, pat_risk)

        if self._sandbox_resolved:
            sandbox_reasons, sandbox_risk = self._check_path_sandbox(
                ["__path_check__", path]
            )
            reasons.extend(sandbox_reasons)
            risk = max(risk, sandbox_risk)

        if risk >= 0.7:
            result = self._deny(path, reasons, risk)
        elif risk >= 0.4:
            result = ValidationResult(
                verdict=CommandVerdict.NEEDS_REVIEW,
                command=path,
                reasons=tuple(reasons),
                risk_score=risk,
            )
        else:
            result = ValidationResult(
                verdict=CommandVerdict.ALLOWED,
                command=path,
                risk_score=risk,
            )
        self._audit(result)
        return result

    def _audit(self, result: ValidationResult) -> None:
        """Emit an audit log entry if the policy has audit_log enabled.

        Args:
            result: The validation result to audit.
        """
        if self.policy.audit_log and not result.is_allowed:
            _logger.warning(
                "CommandSanitizer [%s] %r — %s",
                result.verdict.value,
                result.command,
                "; ".join(result.reasons) if result.reasons else "no reasons",
            )


# =============================================================================
# SecureShellMixin
# =============================================================================


class SecureShellMixin:
    """Mixin that adds security validation to ShellTool via composition.

    Provides three public methods:

    - ``set_security_policy(policy)`` — attach a ``SecurityPolicy``; creates
      a ``CommandSanitizer`` internally.
    - ``validate_command(command)`` — return a ``ValidationResult``.
    - ``assert_command_safe(command)`` — raise ``CommandSecurityError`` if the
      command is denied or requires review.

    Backward-compatible design: if no policy has been set (``_sanitizer`` is
    ``None``), ``validate_command`` returns ALLOWED for every command, matching
    the old no-security behaviour.

    Example:
        >>> class MyShell(SecureShellMixin):
        ...     pass
        >>> shell = MyShell()
        >>> shell.set_security_policy(SecurityPolicy.moderate())
        >>> shell.assert_command_safe("rm -rf /")  # raises CommandSecurityError
    """

    _sanitizer: Optional[CommandSanitizer] = None

    def set_security_policy(self, policy: SecurityPolicy) -> None:
        """Attach a security policy, replacing any previously set policy.

        Args:
            policy: The ``SecurityPolicy`` to enforce on subsequent calls.
        """
        self._sanitizer = CommandSanitizer(policy)

    def validate_command(self, command: str) -> ValidationResult:
        """Validate a command string against the active security policy.

        If no policy has been set, every command is ALLOWED (backward compat).

        Args:
            command: The raw command string to validate.

        Returns:
            A ``ValidationResult`` with the verdict, reasons, and risk score.
        """
        if self._sanitizer is None:
            return ValidationResult(
                verdict=CommandVerdict.ALLOWED,
                command=command,
                risk_score=0.0,
            )
        return self._sanitizer.validate(command)

    def assert_command_safe(self, command: str) -> None:
        """Validate and raise if the command is denied or needs review.

        ``NEEDS_REVIEW`` is treated as ``DENIED`` in automated contexts
        (per Open Q1 resolution in FEAT-038 spec).

        Args:
            command: The raw command string to validate.

        Raises:
            CommandSecurityError: If the command verdict is DENIED or
                NEEDS_REVIEW.
        """
        result = self.validate_command(command)
        if result.is_denied:
            raise CommandSecurityError(
                f"Command denied: {command!r}",
                result=result,
            )
        if result.verdict == CommandVerdict.NEEDS_REVIEW:
            raise CommandSecurityError(
                f"Command requires review (treated as denied): {command!r}",
                result=result,
            )
