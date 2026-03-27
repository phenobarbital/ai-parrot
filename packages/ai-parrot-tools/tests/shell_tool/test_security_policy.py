"""Tests for SecurityPolicy dataclass and defaults (TASK-256)."""

from parrot.tools.shell_tool.security import (
    CommandRule,
    SecurityLevel,
    SecurityPolicy,
    _DEFAULT_DENIED_COMMANDS,
    _MODERATE_SAFE_DEFAULTS,
    _default_command_rules,
)


class TestDefaultDeniedCommands:
    def test_has_50_plus_entries(self):
        assert len(_DEFAULT_DENIED_COMMANDS) >= 50

    def test_contains_destructive(self):
        assert "rm" in _DEFAULT_DENIED_COMMANDS
        assert "dd" in _DEFAULT_DENIED_COMMANDS
        assert "shred" in _DEFAULT_DENIED_COMMANDS

    def test_contains_privilege_escalation(self):
        assert "sudo" in _DEFAULT_DENIED_COMMANDS
        assert "su" in _DEFAULT_DENIED_COMMANDS
        assert "chmod" in _DEFAULT_DENIED_COMMANDS

    def test_contains_shells(self):
        assert "bash" in _DEFAULT_DENIED_COMMANDS
        assert "sh" in _DEFAULT_DENIED_COMMANDS
        assert "zsh" in _DEFAULT_DENIED_COMMANDS

    def test_contains_network_tools(self):
        assert "nc" in _DEFAULT_DENIED_COMMANDS
        assert "ssh" in _DEFAULT_DENIED_COMMANDS

    def test_contains_package_managers(self):
        assert "apt" in _DEFAULT_DENIED_COMMANDS
        assert "apt-get" in _DEFAULT_DENIED_COMMANDS
        assert "yum" in _DEFAULT_DENIED_COMMANDS

    def test_contains_container_tools(self):
        assert "docker" in _DEFAULT_DENIED_COMMANDS
        assert "podman" in _DEFAULT_DENIED_COMMANDS

    def test_is_set(self):
        assert isinstance(_DEFAULT_DENIED_COMMANDS, set)


class TestModerateSafeDefaults:
    def test_contains_common_commands(self):
        for cmd in ("ls", "cat", "grep", "find", "echo", "pwd"):
            assert cmd in _MODERATE_SAFE_DEFAULTS

    def test_contains_python(self):
        assert "python3" in _MODERATE_SAFE_DEFAULTS
        assert "python" in _MODERATE_SAFE_DEFAULTS

    def test_contains_git(self):
        assert "git" in _MODERATE_SAFE_DEFAULTS

    def test_is_set(self):
        assert isinstance(_MODERATE_SAFE_DEFAULTS, set)


class TestDefaultCommandRules:
    def test_returns_10_plus_rules(self):
        rules = _default_command_rules()
        assert len(rules) >= 10

    def test_contains_curl(self):
        rules = _default_command_rules()
        assert "curl" in rules
        curl = rules["curl"]
        assert isinstance(curl, CommandRule)
        assert "-o" in curl.denied_args
        assert "--output" in curl.denied_args

    def test_contains_wget(self):
        rules = _default_command_rules()
        assert "wget" in rules
        wget = rules["wget"]
        assert any("file://" in p for p in wget.denied_patterns)

    def test_contains_find(self):
        rules = _default_command_rules()
        assert "find" in rules
        find = rules["find"]
        assert "-exec" in find.denied_args
        assert "-delete" in find.denied_args

    def test_contains_python3(self):
        rules = _default_command_rules()
        assert "python3" in rules
        assert rules["python3"].risk_base > 0

    def test_contains_pip(self):
        rules = _default_command_rules()
        assert "pip" in rules
        pip = rules["pip"]
        assert pip.allowed_args is not None
        assert "install" in pip.allowed_args

    def test_contains_sed(self):
        rules = _default_command_rules()
        assert "sed" in rules
        assert "-i" in rules["sed"].denied_args

    def test_contains_awk(self):
        rules = _default_command_rules()
        assert "awk" in rules
        assert any("system" in p for p in rules["awk"].denied_patterns)

    def test_returns_fresh_dict_each_call(self):
        r1 = _default_command_rules()
        r2 = _default_command_rules()
        r1["curl"].denied_args.add("--new-flag")
        assert "--new-flag" not in r2["curl"].denied_args

    def test_git_has_low_risk_base(self):
        rules = _default_command_rules()
        assert rules["git"].risk_base <= 0.2


class TestSecurityPolicyDefaults:
    def test_default_level_is_moderate(self):
        policy = SecurityPolicy()
        assert policy.level == SecurityLevel.MODERATE

    def test_default_allowed_commands_empty(self):
        policy = SecurityPolicy()
        assert policy.allowed_commands == set()

    def test_default_denied_commands_not_empty(self):
        policy = SecurityPolicy()
        assert len(policy.denied_commands) > 0

    def test_default_sandbox_dir_none(self):
        policy = SecurityPolicy()
        assert policy.sandbox_dir is None

    def test_default_allow_shell_operators_false(self):
        policy = SecurityPolicy()
        assert policy.allow_shell_operators is False

    def test_default_allow_chaining_false(self):
        policy = SecurityPolicy()
        assert policy.allow_chaining is False

    def test_default_allow_env_expansion_false(self):
        policy = SecurityPolicy()
        assert policy.allow_env_expansion is False

    def test_default_allow_command_substitution_false(self):
        policy = SecurityPolicy()
        assert policy.allow_command_substitution is False

    def test_default_allow_glob_true(self):
        policy = SecurityPolicy()
        assert policy.allow_glob is True

    def test_default_audit_log_true(self):
        policy = SecurityPolicy()
        assert policy.audit_log is True

    def test_max_output_bytes(self):
        policy = SecurityPolicy()
        assert policy.max_output_bytes == 1_048_576

    def test_max_stderr_bytes(self):
        policy = SecurityPolicy()
        assert policy.max_stderr_bytes == 262_144


class TestRestrictiveFactory:
    def test_level_is_restrictive(self):
        policy = SecurityPolicy.restrictive()
        assert policy.level == SecurityLevel.RESTRICTIVE

    def test_empty_allowed_commands_by_default(self):
        policy = SecurityPolicy.restrictive()
        assert policy.allowed_commands == set()

    def test_custom_allowed_commands(self):
        policy = SecurityPolicy.restrictive(allowed_commands={"ls", "cat"})
        assert "ls" in policy.allowed_commands
        assert "cat" in policy.allowed_commands

    def test_denied_commands_empty(self):
        policy = SecurityPolicy.restrictive()
        assert policy.denied_commands == set()

    def test_sandbox_dir_none_by_default(self):
        policy = SecurityPolicy.restrictive()
        assert policy.sandbox_dir is None

    def test_sandbox_dir_set(self):
        policy = SecurityPolicy.restrictive(sandbox_dir="/tmp/sandbox")
        assert policy.sandbox_dir == "/tmp/sandbox"

    def test_max_command_length_2048(self):
        policy = SecurityPolicy.restrictive()
        assert policy.max_command_length == 2048

    def test_allow_shell_operators_false(self):
        policy = SecurityPolicy.restrictive()
        assert policy.allow_shell_operators is False

    def test_allow_chaining_false(self):
        policy = SecurityPolicy.restrictive()
        assert policy.allow_chaining is False

    def test_allow_env_expansion_false(self):
        policy = SecurityPolicy.restrictive()
        assert policy.allow_env_expansion is False

    def test_allow_command_substitution_false(self):
        policy = SecurityPolicy.restrictive()
        assert policy.allow_command_substitution is False

    def test_allow_glob_false(self):
        policy = SecurityPolicy.restrictive()
        assert policy.allow_glob is False

    def test_audit_log_true(self):
        policy = SecurityPolicy.restrictive()
        assert policy.audit_log is True

    def test_custom_command_rules(self):
        rule = CommandRule(name="git")
        policy = SecurityPolicy.restrictive(command_rules={"git": rule})
        assert "git" in policy.command_rules

    def test_empty_command_rules_by_default(self):
        policy = SecurityPolicy.restrictive()
        assert policy.command_rules == {}


class TestModerateFactory:
    def test_level_is_moderate(self):
        policy = SecurityPolicy.moderate()
        assert policy.level == SecurityLevel.MODERATE

    def test_includes_safe_defaults(self):
        policy = SecurityPolicy.moderate()
        for cmd in ("ls", "cat", "grep", "git", "python3"):
            assert cmd in policy.allowed_commands

    def test_merges_custom_commands(self):
        policy = SecurityPolicy.moderate(allowed_commands={"my_tool"})
        assert "my_tool" in policy.allowed_commands
        assert "ls" in policy.allowed_commands  # Safe defaults still present

    def test_denied_commands_not_empty(self):
        policy = SecurityPolicy.moderate()
        assert len(policy.denied_commands) > 0
        assert "rm" in policy.denied_commands

    def test_sandbox_dir_none_by_default(self):
        policy = SecurityPolicy.moderate()
        assert policy.sandbox_dir is None

    def test_sandbox_dir_set(self):
        policy = SecurityPolicy.moderate(sandbox_dir="/workspace")
        assert policy.sandbox_dir == "/workspace"

    def test_max_command_length_4096(self):
        policy = SecurityPolicy.moderate()
        assert policy.max_command_length == 4096

    def test_allow_shell_operators_true(self):
        policy = SecurityPolicy.moderate()
        assert policy.allow_shell_operators is True

    def test_allow_chaining_false(self):
        policy = SecurityPolicy.moderate()
        assert policy.allow_chaining is False

    def test_allow_env_expansion_false(self):
        policy = SecurityPolicy.moderate()
        assert policy.allow_env_expansion is False

    def test_allow_command_substitution_false(self):
        policy = SecurityPolicy.moderate()
        assert policy.allow_command_substitution is False

    def test_allow_glob_true(self):
        policy = SecurityPolicy.moderate()
        assert policy.allow_glob is True

    def test_has_default_command_rules(self):
        policy = SecurityPolicy.moderate()
        assert "curl" in policy.command_rules
        assert "find" in policy.command_rules


class TestPermissiveFactory:
    def test_level_is_permissive(self):
        policy = SecurityPolicy.permissive()
        assert policy.level == SecurityLevel.PERMISSIVE

    def test_allowed_commands_empty(self):
        policy = SecurityPolicy.permissive()
        assert policy.allowed_commands == set()

    def test_default_denied_commands(self):
        policy = SecurityPolicy.permissive()
        # rm is intentionally excluded from PERMISSIVE denied list (TASK-260);
        # it is guarded by CommandRule instead.
        assert "rm" not in policy.denied_commands
        assert "sudo" in policy.denied_commands

    def test_custom_denied_commands(self):
        policy = SecurityPolicy.permissive(denied_commands={"nc", "nmap"})
        assert "nc" in policy.denied_commands
        assert "nmap" in policy.denied_commands
        assert "rm" not in policy.denied_commands  # Only custom set used

    def test_empty_denied_commands_allowed(self):
        policy = SecurityPolicy.permissive(denied_commands=set())
        assert policy.denied_commands == set()

    def test_sandbox_dir_set(self):
        policy = SecurityPolicy.permissive(sandbox_dir="/data")
        assert policy.sandbox_dir == "/data"

    def test_max_command_length_8192(self):
        policy = SecurityPolicy.permissive()
        assert policy.max_command_length == 8192

    def test_allow_shell_operators_true(self):
        policy = SecurityPolicy.permissive()
        assert policy.allow_shell_operators is True

    def test_allow_chaining_true(self):
        policy = SecurityPolicy.permissive()
        assert policy.allow_chaining is True

    def test_allow_env_expansion_true(self):
        policy = SecurityPolicy.permissive()
        assert policy.allow_env_expansion is True

    def test_allow_command_substitution_false(self):
        policy = SecurityPolicy.permissive()
        assert policy.allow_command_substitution is False

    def test_allow_glob_true(self):
        policy = SecurityPolicy.permissive()
        assert policy.allow_glob is True

    def test_has_default_command_rules(self):
        policy = SecurityPolicy.permissive()
        assert "curl" in policy.command_rules
        assert "awk" in policy.command_rules


class TestSecurityPolicyMutability:
    def test_denied_commands_mutable(self):
        policy = SecurityPolicy.moderate()
        policy.denied_commands.add("my_cmd")
        assert "my_cmd" in policy.denied_commands

    def test_denied_patterns_mutable(self):
        policy = SecurityPolicy.moderate()
        policy.denied_patterns.append(r"secret")
        assert r"secret" in policy.denied_patterns

    def test_instances_do_not_share_denied_commands(self):
        p1 = SecurityPolicy.moderate()
        p2 = SecurityPolicy.moderate()
        p1.denied_commands.add("__test__")
        assert "__test__" not in p2.denied_commands
