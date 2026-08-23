# TASK-2295: Create examples/agents/aws/README.md + Final Verification

**Feature**: FEAT-437 — AWS Bedrock Sample Agents
**Spec**: `sdd/specs/claude-bedrock-sample-agents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2293, TASK-2294
**Assigned-to**: unassigned

---

## Context

This final task for FEAT-437 creates the shared `README.md` for the
`examples/agents/aws/` directory and runs the acceptance-criteria
verification checklist defined in the spec.

The README is the primary onboarding document for developers evaluating
AI-Parrot for AWS-centric deployments. It must cover:
- AWS credentials and environment variable setup (by client type)
- Model access prerequisites (Bedrock model access console)
- AWS region requirements (Claude Opus 5 / Haiku 4.5 → `us-*`, Claude Fable 5 → global)
- Explanation of the `bedrock-converse` vs `bedrock-mantle` client split
- Usage examples for each script

Implements spec Module 7 and the final acceptance-criteria sweep.

---

## Scope

- Write `examples/agents/aws/README.md` covering:
  - **Prerequisites**: Python env, AWS credentials, model access
  - **Environment Variables**: two tables — one for bedrock-converse scripts,
    one for bedrock-mantle scripts
  - **Model Access**: instructions for requesting model access in AWS console
  - **Region Requirements**: `claude-opus-5` / `claude-haiku-4-5` → `us-east-1`,
    `claude-fable-5` → `us-west-2` (global prefix); Deepseek/MiniMax → varies
  - **Client Split Explanation**: why Claude uses `bedrock-converse` and
    third-party vendors use `bedrock-mantle`
  - **Usage**: `python examples/agents/aws/<script>.py` for each script
  - **Troubleshooting**: common auth failure messages and how to fix them
- Run final acceptance-criteria verification (syntax checks for all 5 scripts)
- Commit README (not gitignored — only `.py` files in `examples/` are affected by `.gitignore`)

**NOT in scope**: creating or modifying agent scripts (TASK-2293 and TASK-2294).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/aws/README.md` | CREATE | Shared documentation for all 5 Bedrock agent examples |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verify that the 5 scripts from TASK-2293 and TASK-2294 exist before writing
> the README.

### Files That Must Exist Before This Task Runs

```
examples/agents/aws/agent_claude_opus5.py      # Created by TASK-2293
examples/agents/aws/agent_claude_fable5.py     # Created by TASK-2293
examples/agents/aws/agent_claude_haiku45.py    # Created by TASK-2293
examples/agents/aws/agent_deepseek_v32.py      # Created by TASK-2294
examples/agents/aws/agent_minimax_m25.py       # Created by TASK-2294
```

### Client and Model IDs (for README tables)

```
bedrock-converse:  # Claude models via native AWS Converse API + SigV4/boto3
  anthropic.claude-opus-5          → Claude Opus 5    (region prefix: us)
  anthropic.claude-fable-5         → Claude Fable 5   (region prefix: global)
  anthropic.claude-haiku-4-5       → Claude Haiku 4.5 (region prefix: us)

bedrock-mantle:    # Third-party models via OpenAI-compatible Bedrock endpoint
  deepseek.v3.2           → Deepseek V3.2
  minimax.minimax-m2.5    → MiniMax M2.5
```

### Environment Variables by Client Type

```
bedrock-converse scripts (Claude):
  AWS_ACCESS_KEY_ID       — required
  AWS_SECRET_ACCESS_KEY   — required
  AWS_DEFAULT_REGION      — required (us-east-1 for Opus/Haiku, us-west-2 or us-east-1 for Fable)
  AWS_SESSION_TOKEN       — optional (when using temporary credentials)

bedrock-mantle scripts (Deepseek, MiniMax):
  AWS_ACCESS_KEY_ID       — required
  AWS_SECRET_ACCESS_KEY   — required
  AWS_DEFAULT_REGION      — required
  BEDROCK_ENDPOINT_URL    — optional (custom Mantle endpoint override)
```

### Does NOT Exist

- ~~`parrot.models.bedrock_models.DeepseekModels`~~ — no enum; raw strings only
- ~~`parrot.models.bedrock_models.MiniMaxModels`~~ — no enum; raw strings only
- ~~`bedrock-mantle` support for Claude~~ — do NOT imply this works in the README

---

## Implementation Notes

### README Structure

```markdown
# AWS Bedrock Agent Examples

Interactive CLI agents demonstrating AI-Parrot on AWS Bedrock.

## Prerequisites
- Python 3.11+
- AI-Parrot installed (see root README)
- AWS account with Bedrock access
- Requested model access in the AWS Bedrock console (see below)

## Environment Variables

### Claude Scripts (bedrock-converse)
| Variable | Required | Description |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | ✅ | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | ✅ | AWS secret key |
| `AWS_DEFAULT_REGION` | ✅ | Region (see model table) |
| `AWS_SESSION_TOKEN` | optional | Temporary session token |

### Deepseek / MiniMax Scripts (bedrock-mantle)
| Variable | Required | Description |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | ✅ | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | ✅ | AWS secret key |
| `AWS_DEFAULT_REGION` | ✅ | AWS region |
| `BEDROCK_ENDPOINT_URL` | optional | Custom Mantle endpoint override |

## Model Access

Request model access in the AWS Console:
AWS Console → Amazon Bedrock → Model access → Request access

| Script | Model ID | Region | Client |
|---|---|---|---|
| `agent_claude_opus5.py` | `anthropic.claude-opus-5` | us-east-1 | bedrock-converse |
| `agent_claude_fable5.py` | `anthropic.claude-fable-5` | us-east-1 or us-west-2 | bedrock-converse |
| `agent_claude_haiku45.py` | `anthropic.claude-haiku-4-5-20251001-v1:0` | us-east-1 | bedrock-converse |
| `agent_deepseek_v32.py` | `deepseek.v3.2` | us-east-1 | bedrock-mantle |
| `agent_minimax_m25.py` | `minimax.minimax-m2.5` | us-east-1 | bedrock-mantle |

## Usage
# Activate venv
source .venv/bin/activate

# Run any agent
python examples/agents/aws/agent_claude_opus5.py

## Client Split Explanation
...
## Troubleshooting
...
```

### Key Constraints

- Do NOT overstate tool-calling support — note that Deepseek/MiniMax tool calling on Bedrock Mantle
  is model-version-dependent; if it fails at runtime the agent falls back to text-only
- README is NOT gitignored (only `.py` files in `examples/` are affected by `.gitignore` line 21)
  so `git add` (without `-f`) is sufficient

### Final Acceptance-Criteria Verification

After writing the README, run the full syntax check sweep:

```bash
source .venv/bin/activate
python -m py_compile \
  examples/agents/aws/agent_claude_opus5.py \
  examples/agents/aws/agent_claude_fable5.py \
  examples/agents/aws/agent_claude_haiku45.py \
  examples/agents/aws/agent_deepseek_v32.py \
  examples/agents/aws/agent_minimax_m25.py
echo "✅ All 5 scripts pass syntax check"
```

---

## Acceptance Criteria

- [ ] `examples/agents/aws/README.md` exists and covers prerequisites, env vars, model
      access, region requirements, usage examples, and client-split explanation
- [ ] README mentions `git add -f` requirement for `.py` files (developer note)
- [ ] All 5 scripts pass `python -m py_compile` syntax check
- [ ] All acceptance criteria in spec §5 are confirmed met:
  - [ ] Directory `examples/agents/aws/` exists
  - [ ] 5 agent scripts exist
  - [ ] Scripts use `BasicAgent` from `parrot.bots.agent`
  - [ ] Claude scripts use `bedrock-converse` with commented `bedrock` alternative
  - [ ] Deepseek uses `bedrock-mantle:deepseek.v3.2`
  - [ ] MiniMax uses `bedrock-mantle:minimax.minimax-m2.5`
  - [ ] Each script has `PythonREPLTool` + ≥2 `@tool` functions
  - [ ] Each script has CLI loop with exit on exit/quit/bye
  - [ ] Each script wraps `agent.configure()` in try/except
  - [ ] No new library dependencies introduced

---

## Test Specification

```bash
# Verify README exists and has meaningful content
test -f examples/agents/aws/README.md && \
  grep -q "bedrock-converse" examples/agents/aws/README.md && \
  grep -q "bedrock-mantle" examples/agents/aws/README.md && \
  grep -q "AWS_ACCESS_KEY_ID" examples/agents/aws/README.md && \
  echo "✅ README content checks passed"

# Final syntax check — all 5 scripts
source .venv/bin/activate
python -m py_compile \
  examples/agents/aws/agent_claude_opus5.py \
  examples/agents/aws/agent_claude_fable5.py \
  examples/agents/aws/agent_claude_haiku45.py \
  examples/agents/aws/agent_deepseek_v32.py \
  examples/agents/aws/agent_minimax_m25.py && echo "✅ All scripts OK"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/claude-bedrock-sample-agents.spec.md`
2. **Check dependencies** — TASK-2293 and TASK-2294 must be in `sdd/tasks/completed/`
3. **Verify all 5 scripts exist** in `examples/agents/aws/`
4. **Write `examples/agents/aws/README.md`** following the structure in Implementation Notes
5. **Add README** with `git add examples/agents/aws/README.md` (no `-f` needed for `.md`)
6. **Run final syntax check** on all 5 scripts
7. **Commit** with message: `feat(FEAT-437): add Bedrock agents README + FEAT-437 complete`
8. **Move this file** to `sdd/tasks/completed/TASK-2295-bedrock-agents-readme.md`
9. **Update index** at `sdd/tasks/index/claude-bedrock-sample-agents.json` → `"done"`, set `"completed_at"` on the feature header
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
