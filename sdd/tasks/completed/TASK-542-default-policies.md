# TASK-542: Default YAML Policies

**Feature**: policy-based-access-control
**Spec**: `sdd/specs/policy-based-access-control.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Creates the default YAML policy files that ship with ai-parrot. These establish
> a deny-by-default baseline with sensible allows for common operations. They serve
> as both working defaults and documentation-by-example for policy authors.
>
> Implements Spec Module 9.

---

## Scope

- Create `policies/` directory at project root
- Create `policies/defaults.yaml`: Base deny-by-default with wildcard allows for
  common operations (list tools, list agents)
- Create `policies/agents.yaml`: Example agent access policies:
  - Business hours restriction example
  - Group-based agent access example
- Create `policies/tools.yaml`: Example tool access policies:
  - Per-group tool visibility (engineering, devops, etc.)
  - Wildcard patterns (tool:jira_*, tool:github_*)
- Create `policies/mcp.yaml`: Example MCP server access policies:
  - DevOps-only MCP servers
  - Read-only MCP access for all users
- Create `policies/README.md`: Policy authoring guide with:
  - YAML schema reference
  - Resource type and action type tables
  - Example policies for common scenarios
  - Priority resolution explanation

**NOT in scope**:
- Database-backed policies
- Policy validation tooling
- Hot-reload mechanism

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `policies/defaults.yaml` | CREATE | Base deny-by-default policies |
| `policies/agents.yaml` | CREATE | Agent access policy examples |
| `policies/tools.yaml` | CREATE | Tool access policy examples |
| `policies/mcp.yaml` | CREATE | MCP server policy examples |
| `policies/README.md` | CREATE | Policy authoring guide |

---

## Implementation Notes

### Policy Schema
```yaml
version: "1.0"
defaults:
  effect: deny
policies:
  - name: unique_policy_name
    effect: allow|deny
    description: "Human-readable description"
    resources:
      - "type:pattern"     # tool:*, agent:finance_bot, mcp:github_*
    actions:
      - "type:action"      # tool:execute, agent:chat, dataset:query
    subjects:
      groups: [engineering, "*"]
      users: [admin@acme.com]
      roles: [senior_engineer]
      exclude_groups: [contractors]
    conditions:
      environment:
        is_business_hours: true
      programs:
        - acme_corp
    priority: 20           # Higher = evaluated first
    enforcing: false       # true = short-circuit on match
```

### Key Constraints
- All default policies must use deny-by-default pattern
- Policies must be valid YAML parseable by `YAMLStorage`
- Use realistic but generic examples (not company-specific)
- Include comments in YAML files explaining each policy
- README must cover the full schema with all supported fields

### References in Codebase
- `navigator_auth/abac/storages/yaml_storage.py` — YAML schema reference
- `navigator_auth/abac/policies/resources.py` — ResourceType, ActionType enums
- `sdd/proposals/policy-based-access-control.brainstorm.md` — policy examples from user

---

## Acceptance Criteria

- [ ] `policies/` directory exists with all 4 YAML files + README
- [ ] All YAML files parse successfully via `YAMLStorage`
- [ ] `defaults.yaml` establishes deny-by-default baseline
- [ ] Example policies cover: agents, tools, MCP, business hours, groups
- [ ] README documents full policy schema with examples
- [ ] No company-specific or sensitive data in policy files

---

## Test Specification

```python
import pytest
import yaml
from pathlib import Path


class TestDefaultPolicies:
    def test_yaml_files_valid(self):
        """All policy YAML files parse without errors."""
        policy_dir = Path("policies")
        for f in policy_dir.glob("*.yaml"):
            data = yaml.safe_load(f.read_text())
            assert "version" in data
            assert "policies" in data

    def test_defaults_deny_by_default(self):
        """defaults.yaml has deny as default effect."""
        data = yaml.safe_load(Path("policies/defaults.yaml").read_text())
        assert data["defaults"]["effect"] == "deny"

    def test_all_policies_have_names(self):
        """Every policy has a unique name."""
        names = set()
        for f in Path("policies").glob("*.yaml"):
            data = yaml.safe_load(f.read_text())
            for p in data.get("policies", []):
                assert "name" in p
                assert p["name"] not in names
                names.add(p["name"])
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-542-default-policies.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: Created policies/ directory with defaults.yaml (4 policies), agents.yaml
(5 policies), tools.yaml (6 policies), mcp.yaml (5 policies), and README.md.
All YAML files validated successfully with yaml.safe_load(). 20 unique policy names
across all files. Deny-by-default established in all files.

**Deviations from spec**: none
