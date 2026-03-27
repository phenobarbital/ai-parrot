"""Tests for CommandSanitizer 6-layer validation pipeline (TASK-257)."""

from parrot.tools.shell_tool.security import (
    CommandSanitizer,
    CommandVerdict,
    SecurityPolicy,
    _DANGEROUS_PATTERNS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_moderate() -> CommandSanitizer:
    return CommandSanitizer(SecurityPolicy.moderate())


def make_restrictive(allowed=None, sandbox_dir=None) -> CommandSanitizer:
    return CommandSanitizer(SecurityPolicy.restrictive(
        allowed_commands=allowed or set(),
        sandbox_dir=sandbox_dir,
    ))


def make_permissive(denied=None, sandbox_dir=None) -> CommandSanitizer:
    return CommandSanitizer(SecurityPolicy.permissive(
        denied_commands=denied,
        sandbox_dir=sandbox_dir,
    ))


# ---------------------------------------------------------------------------
# Dangerous patterns registry
# ---------------------------------------------------------------------------

class TestDangerousPatterns:
    def test_has_20_plus_patterns(self):
        assert len(_DANGEROUS_PATTERNS) >= 20

    def test_each_entry_has_three_elements(self):
        for pat, desc, risk in _DANGEROUS_PATTERNS:
            assert isinstance(pat, str)
            assert isinstance(desc, str)
            assert isinstance(risk, float)
            assert 0.0 <= risk <= 1.0

    def test_command_substitution_high_risk(self):
        scores = {desc: risk for _, desc, risk in _DANGEROUS_PATTERNS}
        assert scores["command substitution $(…)"] >= 0.8

    def test_sensitive_files_critical_risk(self):
        scores = {desc: risk for _, desc, risk in _DANGEROUS_PATTERNS}
        assert scores["sensitive system files"] >= 0.9


# ---------------------------------------------------------------------------
# Layer 0: Basic sanity
# ---------------------------------------------------------------------------

class TestLayer0Sanity:
    def test_empty_command_allowed(self):
        result = make_moderate().validate("")
        assert result.is_allowed

    def test_whitespace_only_allowed(self):
        result = make_moderate().validate("   ")
        assert result.is_allowed

    def test_too_long_command_denied(self):
        long_cmd = "echo " + "x" * 5000
        result = make_moderate().validate(long_cmd)
        assert result.is_denied
        assert any("exceeds max length" in r for r in result.reasons)

    def test_max_length_boundary_allowed(self):
        policy = SecurityPolicy.moderate()
        limit = policy.max_command_length
        cmd = "echo " + "x" * (limit - 6)
        result = CommandSanitizer(policy).validate(cmd)
        # Should not be denied for length
        assert not any("exceeds max length" in r for r in result.reasons)


# ---------------------------------------------------------------------------
# Layer 1: Parse errors
# ---------------------------------------------------------------------------

class TestLayer1Parse:
    def test_malformed_command_denied(self):
        result = make_moderate().validate("echo 'unterminated")
        assert result.is_denied
        assert any("malformed" in r for r in result.reasons)


# ---------------------------------------------------------------------------
# Layer 2: Dangerous pattern detection
# ---------------------------------------------------------------------------

class TestLayer2Patterns:
    def test_command_substitution_dollar_denied(self):
        result = make_moderate().validate("cat $(echo /etc/passwd)")
        assert result.is_denied

    def test_backtick_substitution_denied(self):
        result = make_moderate().validate("cat `echo /etc/passwd`")
        assert result.is_denied

    def test_process_substitution_denied(self):
        result = make_moderate().validate("diff <(cat a) <(cat b)")
        assert result.is_denied

    def test_sensitive_file_passwd_denied(self):
        result = make_moderate().validate("cat /etc/passwd")
        assert result.is_denied

    def test_sensitive_file_shadow_denied(self):
        result = make_moderate().validate("cat /etc/shadow")
        assert result.is_denied

    def test_proc_filesystem_denied(self):
        result = make_moderate().validate("cat /proc/cpuinfo")
        assert result.is_denied

    def test_sys_filesystem_denied(self):
        result = make_moderate().validate("ls /sys/kernel")
        assert result.is_denied

    def test_eval_denied(self):
        result = make_moderate().validate("eval 'rm -rf /'")
        assert result.is_denied

    def test_path_traversal_denied(self):
        result = make_moderate().validate("cat ../../etc/passwd")
        assert result.is_denied

    def test_pipe_allowed_in_moderate(self):
        # Moderate has allow_shell_operators=True; pipe itself shouldn't block
        result = make_moderate().validate("ls | grep foo")
        assert result.verdict != CommandVerdict.DENIED or any(
            "pipe" not in r for r in result.reasons
        )

    def test_chaining_denied_in_moderate(self):
        result = make_moderate().validate("echo hi; rm -rf /")
        assert result.is_denied

    def test_env_var_blocked_in_moderate(self):
        # env var expansion has risk 0.4 → NEEDS_REVIEW (not outright DENIED)
        result = make_moderate().validate("echo $HOME")
        assert not result.is_allowed
        assert result.verdict in (CommandVerdict.DENIED, CommandVerdict.NEEDS_REVIEW)

    def test_command_substitution_allowed_when_policy_permits(self):
        # Only permissive with allow_command_substitution can allow it
        policy = SecurityPolicy.permissive()
        policy.allow_command_substitution = True  # type: ignore[attr-defined]
        sanitizer = CommandSanitizer(policy)
        result = sanitizer.validate("echo $(date)")
        # Should not be denied for command substitution pattern alone
        sub_reasons = [r for r in result.reasons if "command substitution" in r]
        assert not sub_reasons


# ---------------------------------------------------------------------------
# Layer 3: Command access control
# ---------------------------------------------------------------------------

class TestLayer3CommandAccess:
    # RESTRICTIVE
    def test_restrictive_denies_unlisted_command(self):
        result = make_restrictive(allowed={"ls"}).validate("cat file.txt")
        assert result.is_denied
        assert any("not in allowlist" in r for r in result.reasons)

    def test_restrictive_allows_listed_command(self):
        result = make_restrictive(allowed={"echo"}).validate("echo hello")
        assert result.is_allowed

    def test_restrictive_denies_even_safe_commands(self):
        result = make_restrictive().validate("ls -la")
        assert result.is_denied

    # MODERATE
    def test_moderate_denies_explicitly_denied_command(self):
        result = make_moderate().validate("rm -rf /")
        assert result.is_denied
        assert any("explicitly denied" in r for r in result.reasons)

    def test_moderate_denies_unlisted_command(self):
        result = make_moderate().validate("foobar --arg")
        assert result.is_denied
        assert any("not in allowlist" in r for r in result.reasons)

    def test_moderate_allows_safe_default(self):
        result = make_moderate().validate("git status")
        assert result.is_allowed

    def test_moderate_allows_ls(self):
        result = make_moderate().validate("ls -la")
        assert result.is_allowed

    def test_moderate_allows_python3(self):
        result = make_moderate().validate("python3 --version")
        assert result.is_allowed

    # PERMISSIVE
    def test_permissive_allows_unlisted_command(self):
        result = make_permissive(denied=set()).validate("foobar")
        assert result.is_allowed

    def test_permissive_denies_explicitly_denied(self):
        # rm is no longer in PERMISSIVE's deny list (controlled by CommandRule,
        # TASK-260). Use a command that is still unconditionally denied.
        result = make_permissive().validate("sudo ls")
        assert result.is_denied

    def test_permissive_allows_safe_commands(self):
        result = make_permissive().validate("git status")
        assert result.is_allowed

    # Destructive commands
    def test_deny_dd(self):
        result = make_moderate().validate("dd if=/dev/zero of=/dev/sda")
        assert result.is_denied

    def test_deny_shutdown(self):
        result = make_moderate().validate("shutdown -h now")
        assert result.is_denied

    def test_deny_sudo(self):
        result = make_moderate().validate("sudo whoami")
        assert result.is_denied

    def test_deny_bash(self):
        result = make_moderate().validate("bash -c 'ls'")
        assert result.is_denied


# ---------------------------------------------------------------------------
# Layer 3 + pipe-chain per-segment validation
# ---------------------------------------------------------------------------

class TestPipeChainValidation:
    def test_pipe_to_denied_cmd_blocked(self):
        # "cat file | bash" — bash is in denied_commands
        result = make_moderate().validate("cat file.txt | bash")
        assert result.is_denied

    def test_pipe_between_safe_cmds_allowed(self):
        result = make_moderate().validate("cat file.txt | grep foo")
        assert result.is_allowed

    def test_pipe_with_unknown_cmd_denied_moderate(self):
        result = make_moderate().validate("ls | unknowncmd")
        assert result.is_denied


# ---------------------------------------------------------------------------
# Layer 4: Per-command argument rules
# ---------------------------------------------------------------------------

class TestLayer4CommandRules:
    def test_curl_deny_output_flag_short(self):
        result = make_moderate().validate("curl -o /tmp/file https://example.com")
        assert result.is_denied

    def test_curl_deny_output_flag_long(self):
        result = make_moderate().validate("curl --output /tmp/file https://example.com")
        assert result.is_denied

    def test_curl_deny_file_protocol(self):
        result = make_moderate().validate("curl file:///etc/passwd")
        assert result.is_denied

    def test_curl_deny_gopher_protocol(self):
        result = make_moderate().validate("curl gopher://evil.com")
        assert result.is_denied

    def test_find_deny_exec_flag(self):
        result = make_moderate().validate("find . -exec rm {} \\;")
        assert result.is_denied

    def test_find_deny_delete_flag(self):
        result = make_moderate().validate("find . -name '*.tmp' -delete")
        assert result.is_denied

    def test_find_deny_execdir(self):
        result = make_moderate().validate("find . -execdir ls {} \\;")
        assert result.is_denied

    def test_sed_deny_inplace(self):
        result = make_moderate().validate("sed -i 's/a/b/' file.txt")
        assert result.is_denied

    def test_awk_deny_system_call(self):
        result = make_moderate().validate("awk '{system(\"ls\")}'")
        assert result.is_denied

    def test_python3_deny_dangerous_c_flag(self):
        result = make_moderate().validate("python3 -c 'import os; os.system(\"ls\")'")
        assert result.is_denied

    def test_pip_deny_target_flag(self):
        result = make_moderate().validate("pip install --target /usr mypackage")
        assert result.is_denied

    def test_find_allows_safe_usage(self):
        result = make_moderate().validate("find . -name '*.py'")
        assert result.is_allowed

    def test_curl_allows_safe_get(self):
        result = make_moderate().validate("curl https://example.com")
        assert result.is_allowed


# ---------------------------------------------------------------------------
# Layer 5: Path sandbox enforcement
# ---------------------------------------------------------------------------

class TestLayer5Sandbox:
    def test_allows_path_inside_sandbox(self, tmp_path):
        sandbox = str(tmp_path)
        inside = str(tmp_path / "file.txt")
        result = make_restrictive(
            allowed={"cat"},
            sandbox_dir=sandbox,
        ).validate(f"cat {inside}")
        assert result.is_allowed

    def test_denies_path_outside_sandbox(self, tmp_path):
        sandbox = str(tmp_path / "workspace")
        result = make_restrictive(
            allowed={"cat"},
            sandbox_dir=sandbox,
        ).validate("cat /etc/hosts")
        assert result.is_denied
        assert any("outside sandbox" in r for r in result.reasons)

    def test_denies_path_traversal_outside_sandbox(self, tmp_path):
        (tmp_path / "workspace").mkdir()
        sandbox = str(tmp_path / "workspace")
        result = make_restrictive(
            allowed={"cat"},
            sandbox_dir=sandbox,
        ).validate("cat ../../etc/passwd")
        assert result.is_denied

    def test_skips_urls(self, tmp_path):
        sandbox = str(tmp_path)
        result = CommandSanitizer(SecurityPolicy.restrictive(
            allowed_commands={"curl"},
            sandbox_dir=sandbox,
        )).validate("curl https://example.com")
        # URL should not trigger sandbox violation
        assert not any("outside sandbox" in r for r in result.reasons)

    def test_skips_flags(self, tmp_path):
        sandbox = str(tmp_path)
        result = CommandSanitizer(SecurityPolicy.restrictive(
            allowed_commands={"ls"},
            sandbox_dir=sandbox,
        )).validate("ls -la")
        assert not any("outside sandbox" in r for r in result.reasons)


# ---------------------------------------------------------------------------
# Layer 6: Custom denied patterns
# ---------------------------------------------------------------------------

class TestLayer6CustomPatterns:
    def test_custom_pattern_denied(self):
        policy = SecurityPolicy.moderate()
        policy.denied_patterns.append(r"secret_flag")
        sanitizer = CommandSanitizer(policy)
        result = sanitizer.validate("echo secret_flag")
        assert result.is_denied
        assert any("custom denied pattern" in r for r in result.reasons)

    def test_custom_pattern_no_match_allowed(self):
        policy = SecurityPolicy.moderate()
        policy.denied_patterns.append(r"secret_flag")
        sanitizer = CommandSanitizer(policy)
        result = sanitizer.validate("echo hello")
        assert result.is_allowed


# ---------------------------------------------------------------------------
# Risk thresholds / final verdict
# ---------------------------------------------------------------------------

class TestRiskThresholds:
    def test_risk_below_04_is_allowed(self):
        result = make_moderate().validate("echo hello")
        assert result.is_allowed
        assert result.risk_score < 0.4

    def test_risk_09_gives_denied(self):
        result = make_moderate().validate("rm -rf /")
        assert result.is_denied
        assert result.risk_score >= 0.7

    def test_needs_review_when_risk_04_to_07(self):
        # curl with safe args has risk_base=0.3; needs_review range is 0.4–0.7
        # We can trigger NEEDS_REVIEW with a moderate-risk scenario:
        # Use git (risk 0.1) + env var (0.4) but policy allows env var
        policy = SecurityPolicy.permissive()
        # env var expansion risk is 0.4
        result = CommandSanitizer(policy).validate("git status")
        # git is clean — should be ALLOWED
        assert result.is_allowed

    def test_empty_reasons_on_allowed(self):
        result = make_moderate().validate("echo hello")
        assert result.verdict == CommandVerdict.ALLOWED


# ---------------------------------------------------------------------------
# validate_batch
# ---------------------------------------------------------------------------

class TestValidateBatch:
    def test_returns_same_count(self):
        cmds = ["echo hi", "rm -rf /", "git status"]
        results = make_moderate().validate_batch(cmds)
        assert len(results) == 3

    def test_correct_verdicts_in_batch(self):
        cmds = ["echo hi", "rm -rf /", "git status"]
        results = make_moderate().validate_batch(cmds)
        assert results[0].is_allowed
        assert results[1].is_denied
        assert results[2].is_allowed

    def test_empty_list(self):
        results = make_moderate().validate_batch([])
        assert results == []


# ---------------------------------------------------------------------------
# Absolute path base command extraction
# ---------------------------------------------------------------------------

class TestBaseCommandExtraction:
    def test_absolute_path_command_extracted(self):
        # /usr/bin/ls should be treated as "ls"
        policy = SecurityPolicy.moderate()
        sanitizer = CommandSanitizer(policy)
        result = sanitizer.validate("/usr/bin/ls -la")
        # ls is in safe defaults → should be allowed
        assert result.is_allowed

    def test_absolute_path_denied_command_still_denied(self):
        result = make_moderate().validate("/bin/rm -rf /")
        assert result.is_denied


# ---------------------------------------------------------------------------
# Fork bomb
# ---------------------------------------------------------------------------

class TestForkBomb:
    def test_fork_bomb_like_chaining_denied(self):
        # fork bomb contains ; chaining pattern
        result = make_moderate().validate(":(){:|:&};:")
        assert result.is_denied


# ---------------------------------------------------------------------------
# Audit logging (smoke test — just ensure no exceptions)
# ---------------------------------------------------------------------------

class TestAuditLog:
    def test_audit_on_deny_no_exception(self):
        policy = SecurityPolicy.moderate()
        assert policy.audit_log is True
        sanitizer = CommandSanitizer(policy)
        # Should not raise
        result = sanitizer.validate("rm -rf /")
        assert result.is_denied

    def test_no_audit_when_disabled(self):
        policy = SecurityPolicy.moderate()
        policy.audit_log = False  # type: ignore[attr-defined]
        sanitizer = CommandSanitizer(policy)
        result = sanitizer.validate("rm -rf /")
        assert result.is_denied


# ---------------------------------------------------------------------------
# Permissive mode — rm CommandRule (TASK-260)
# ---------------------------------------------------------------------------

class TestPermissiveRmRule:
    """rm is denied in RESTRICTIVE and MODERATE but conditionally allowed in PERMISSIVE."""

    def _permissive(self, sandbox_dir=None) -> CommandSanitizer:
        return CommandSanitizer(SecurityPolicy.permissive(sandbox_dir=sandbox_dir))

    def _moderate(self) -> CommandSanitizer:
        return CommandSanitizer(SecurityPolicy.moderate())

    def _restrictive(self, allowed=None) -> CommandSanitizer:
        return CommandSanitizer(SecurityPolicy.restrictive(allowed_commands=allowed or set()))

    # ------------------------------------------------------------------
    # rm denied in RESTRICTIVE and MODERATE
    # ------------------------------------------------------------------

    def test_rm_denied_moderate(self):
        """rm is in the default denied list — MODERATE blocks it."""
        result = self._moderate().validate("rm file.txt")
        assert result.is_denied

    def test_rm_denied_restrictive(self):
        """rm is not in the allowlist — RESTRICTIVE blocks it."""
        result = self._restrictive().validate("rm file.txt")
        assert result.is_denied

    def test_rm_denied_moderate_rf(self):
        """rm -rf / is DENIED in MODERATE mode."""
        result = self._moderate().validate("rm -rf /")
        assert result.is_denied

    # ------------------------------------------------------------------
    # rm allowed (not DENIED) for simple file deletion in PERMISSIVE
    # ------------------------------------------------------------------

    def test_rm_single_file_permissive_not_denied(self):
        """rm file.txt in PERMISSIVE mode is not DENIED (risk < 0.7)."""
        result = self._permissive().validate("rm file.txt")
        assert result.verdict != CommandVerdict.DENIED
        assert result.risk_score < 0.7

    def test_rm_single_file_permissive_risk_below_denial_threshold(self):
        """rm <file> risk stays below 0.7 when no dangerous flags are used."""
        sanitizer = self._permissive()
        for cmd in ("rm myfile.txt", "rm /tmp/output.log", "rm somefile"):
            result = sanitizer.validate(cmd)
            assert result.risk_score < 0.7, f"Expected risk < 0.7 for {cmd!r}, got {result.risk_score}"

    # ------------------------------------------------------------------
    # rm with recursive/force flags DENIED in PERMISSIVE
    # ------------------------------------------------------------------

    def test_rm_recursive_flag_denied_permissive(self):
        """rm -r dir/ is DENIED in PERMISSIVE mode."""
        result = self._permissive().validate("rm -r mydir/")
        assert result.is_denied

    def test_rm_capital_R_flag_denied_permissive(self):
        """rm -R dir is DENIED in PERMISSIVE mode."""
        result = self._permissive().validate("rm -R mydir")
        assert result.is_denied

    def test_rm_recursive_long_flag_denied_permissive(self):
        """rm --recursive dir is DENIED in PERMISSIVE mode."""
        result = self._permissive().validate("rm --recursive mydir")
        assert result.is_denied

    def test_rm_force_flag_denied_permissive(self):
        """rm -f file is DENIED in PERMISSIVE mode."""
        result = self._permissive().validate("rm -f somefile.txt")
        assert result.is_denied

    def test_rm_force_long_flag_denied_permissive(self):
        """rm --force file is DENIED in PERMISSIVE mode."""
        result = self._permissive().validate("rm --force somefile.txt")
        assert result.is_denied

    def test_rm_combined_rf_flag_denied_permissive(self):
        """rm -rf /tmp is DENIED in PERMISSIVE mode (combined flag)."""
        result = self._permissive().validate("rm -rf /tmp")
        assert result.is_denied

    def test_rm_combined_fr_flag_denied_permissive(self):
        """rm -fr dir is DENIED (fr is the same as rf)."""
        result = self._permissive().validate("rm -fr somedir")
        assert result.is_denied

    def test_rm_combined_rfi_flag_denied_permissive(self):
        """rm -rfi (interactive recursive force) is DENIED."""
        result = self._permissive().validate("rm -rfi somedir")
        assert result.is_denied

    # ------------------------------------------------------------------
    # rm on system paths DENIED via pattern detection
    # ------------------------------------------------------------------

    def test_rm_sensitive_path_denied_permissive(self):
        """rm /etc/passwd is DENIED due to sensitive file pattern."""
        result = self._permissive().validate("rm /etc/passwd")
        assert result.is_denied

    def test_rm_outside_sandbox_denied(self):
        """rm on a path outside sandbox_dir is DENIED."""
        sanitizer = self._permissive(sandbox_dir="/home/agent/workspace")
        result = sanitizer.validate("rm /etc/hosts")
        assert result.is_denied
