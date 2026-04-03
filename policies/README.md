# AI-Parrot PBAC Policy Files

This directory contains YAML-based Policy-Based Access Control (PBAC) definitions
for AI-Parrot. Policies are evaluated by the navigator-auth `PolicyEvaluator` on
every request.

## Directory Structure

```
policies/
├── defaults.yaml   # Baseline deny-by-default + admin/superuser allow
├── agents.yaml     # Agent access control (who can chat/configure which agents)
├── tools.yaml      # Tool visibility and execution (which tools each group sees)
├── mcp.yaml        # MCP server access (which external servers each group can use)
└── README.md       # This file
```

All `.yaml` files in this directory are loaded automatically at startup.

## Policy Schema

```yaml
version: "1.0"                    # Required — must be "1.0"

defaults:
  effect: deny                    # Default effect when no policy matches: allow | deny

policies:
  - name: unique_policy_name      # Required — unique across ALL policy files
    effect: allow                 # Required — allow | deny
    description: "..."            # Optional — human-readable explanation

    resources:                    # Required — list of resource patterns
      - "tool:*"                  # All tools
      - "agent:finance_bot"       # Specific agent
      - "mcp:github_*"            # Pattern match
      - "dataset:sales_*"         # Dataset pattern

    actions:                      # Required — list of action strings
      - "tool:execute"
      - "tool:list"
      - "agent:chat"
      - "agent:configure"
      - "dataset:query"

    subjects:                     # Required — who this policy applies to
      groups:
        - engineering             # Group name
        - "*"                     # Wildcard = any authenticated user
      users:
        - admin@example.com       # Specific user by username/email
      roles:
        - senior_engineer         # Role name
      exclude_groups:             # Exclusions take precedence over includes
        - contractors
      exclude_users:
        - blocked@example.com

    conditions:                   # Optional — attribute-based conditions
      environment:
        is_business_hours: true   # Only during 09:00-17:00 Mon-Fri
        day_of_week: [0, 1, 2, 3, 4]  # 0=Mon, 6=Sun
      programs:                   # Tenant/organization conditions
        - acme_corp
        - partner_org

    priority: 20                  # Optional — higher = evaluated first (default: 10)
    enforcing: false              # Optional — true = short-circuit on match (default: false)
```

## Resource Types

| Type        | Pattern Example           | Description                        |
|-------------|---------------------------|------------------------------------|
| `tool`      | `tool:jira_create`        | Individual tool or toolkit tool    |
| `agent`     | `agent:finance_bot`       | AI agent / chatbot                 |
| `mcp`       | `mcp:github`              | External MCP server                |
| `dataset`   | `dataset:sales_2024`      | DatasetManager dataset             |
| `kb`        | `kb:product_docs`         | Knowledge base                     |
| `vector`    | `vector:embeddings`       | Vector store collection            |

## Action Types

| Action             | Resource   | Description                                   |
|--------------------|------------|-----------------------------------------------|
| `agent:chat`       | agent      | Send messages to an agent                     |
| `agent:configure`  | agent      | Configure agent tools / MCP servers           |
| `agent:list`       | agent      | Discover available agents                     |
| `tool:execute`     | tool       | Execute / invoke a tool                       |
| `tool:list`        | tool       | Discover available tools                      |
| `tool:configure`   | tool       | Modify tool settings                          |
| `dataset:query`    | dataset    | Read / query a dataset                        |
| `dataset:write`    | dataset    | Write / update a dataset                      |
| `dataset:list`     | dataset    | List available datasets                       |
| `kb:query`         | kb         | Query / search a knowledge base               |
| `kb:write`         | kb         | Add documents to a knowledge base             |
| `kb:admin`         | kb         | Manage knowledge base settings                |

## Priority and Conflict Resolution

1. Policies are evaluated from **highest priority first** (larger number = first).
2. At **equal priority**, DENY takes precedence over ALLOW.
3. If a policy is `enforcing: true`, evaluation stops immediately on match.
4. If no policy matches, the `defaults.effect` is applied (typically `deny`).

```
Priority 100: allow_superuser_all          <- Evaluated first
Priority 50:  deny_contractors_finance     <- Deny at high priority
Priority 30:  devops_agents_anytime
Priority 20:  engineering_agents_biz_hours
Priority 10:  all_staff_utility_tools      <- Evaluated last
---
Default effect: deny                       <- Applied if nothing matched
```

## Common Policy Patterns

### Business Hours Restriction

```yaml
- name: group_access_business_hours
  effect: allow
  resources: ["agent:*"]
  actions: ["agent:chat"]
  subjects:
    groups: [engineering]
  conditions:
    environment:
      is_business_hours: true
  priority: 20
```

### Group-Based Tool Visibility

```yaml
- name: finance_tools_only
  effect: allow
  resources: ["tool:financial_*", "tool:report_*"]
  actions: ["tool:execute", "tool:list"]
  subjects:
    groups: [finance, accounting]
  priority: 20
```

### Deny with Enforcing Short-Circuit

```yaml
- name: deny_contractors_sensitive
  effect: deny
  resources: ["agent:finance_*", "tool:admin_*"]
  actions: ["agent:chat", "tool:execute"]
  subjects:
    groups: [contractors]
  priority: 50
  enforcing: true     # Stop evaluation immediately on match
```

### Program/Tenant-Based Access

```yaml
- name: acme_corp_agents
  effect: allow
  resources: ["agent:acme_*"]
  actions: ["agent:chat"]
  subjects:
    groups: ["*"]
  conditions:
    programs: [acme_corp]
  priority: 15
```

## File Loading

All `*.yaml` files in this directory are loaded at startup. Files with errors
are skipped with a warning — the application continues with valid policies only.

To add custom policies:
1. Create a new `.yaml` file in this directory (e.g., `my_project.yaml`).
2. Follow the schema above with unique policy names.
3. Restart the application (or wait for cache TTL expiry in future hot-reload).

## Environment Variables

| Variable       | Default      | Description                              |
|----------------|--------------|------------------------------------------|
| `POLICY_DIR`   | `policies`   | Path to the policy directory             |
| `PBAC_CACHE_TTL` | `30`       | Seconds before cached decisions expire   |
