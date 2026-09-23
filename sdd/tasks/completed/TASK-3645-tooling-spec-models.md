# TASK-3645: ToolkitSpec / AgentMCPServerSpec models, normalization and secret hydration

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (1) and §3 Module 1. Every other backend task consumes the one shape
defined here: `ToolkitSpec` (agent-level or override config of one toolkit — non-secret params,
`user_overridable`, `secret_refs`, `vault_owner`) and `AgentMCPServerSpec` (agent-level MCP
server whose `headers`/`auth_config`/`env` live in the vault). `normalize_tooling()` is the
single normalization boundary (design research S1) used by both the DB build path
(TASK-3653) and the YAML factory (TASK-3656).

---

## Scope

- Create `parrot/tools/spec.py` with `SECRET_MASK`, `ToolkitSpec`, `AgentMCPServerSpec`,
  `NormalizedTooling`, `toolkit_vault_name`, `mcp_vault_name`, `normalize_tooling`,
  `tooling_revision`, `hydrate_params`, `hydrate_mcp`, `mask_spec`, `mask_mcp`.
- Dotted secret keys: `secret_refs` keys may be dotted paths (`datasources.0.dsn`); the vault
  entry for one spec is a flat dict keyed by those same dotted paths. `hydrate_params` expands
  them back into nested lists/dicts inside a deep copy of `params`.
- Write unit tests with a fake vault (monkeypatch `retrieve_vault_credential`).

**NOT in scope**: storing secrets (TASK-3659), JSON Schema / secret classification
(TASK-3646), wiring into bots (TASK-3654/3656).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/spec.py` | CREATE | Spec models, normalize_tooling, tooling_revision, hydrate/mask helpers |
| `packages/ai-parrot/tests/tools/test_tooling_spec.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
from parrot.security.vault_utils import retrieve_vault_credential  # verified: packages/ai-parrot/src/parrot/security/vault_utils.py:135
from pydantic import BaseModel, ConfigDict, Field, ValidationError  # pydantic v2 (core dep)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/security/vault_utils.py
async def retrieve_vault_credential(user_id: str, vault_name: str) -> Dict[str, Any]: ...  # :135
#   raises KeyError when not found, RuntimeError when vault keys are unconfigured
# Vault naming precedent (per-user MCP): f"mcp_{server}_{agent_id}"  (handlers/mcp_helper.py)
# packages/ai-parrot/src/parrot/models/basic.py
class ToolConfig(BaseModel): tools: List[Dict[str, Any]]; mcp_servers: List[Dict[str, Any]]; toolkits: List[str]  # :33-37
```

### Does NOT Exist
- ~~`parrot.tools.spec`~~ — this task creates it.
- ~~`parrot.tools.ToolkitSpec` re-export~~ — do NOT add to `parrot/tools/__init__.py` (it has a
  `sys.meta_path` redirect finder; importing `parrot.tools.spec` directly is the contract).
- ~~`parrot.handlers.vault_utils` as implementation~~ — thin re-export; import from `parrot.security.vault_utils`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/spec.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_tooling_spec.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#retrieve_vault_credential"
  ]
}
```

---

## Implementation Notes

- Pure module: no I/O except `hydrate_*` (async vault reads). Never log secret values — log keys only.
- `tooling_revision` hashes `model_dump(mode="json")` of both lists with `sort_keys=True`; secret
  *values* are never in a spec, so the hash is secret-free by construction.
- `normalize_tooling` must accept `tools` items that are not strings (AbstractTool instances,
  classes, ToolkitSpec) and pass non-string, non-spec items through untouched in
  `NormalizedTooling.tools`? No — `tools` is typed `list[Any]` for that reason: keep them in order.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `spec.py` with the models exactly as below — *why*: field names are fixed by spec §2 Data Models and reused by 8 later tasks.
2. Implement `normalize_tooling` dedupe: spec wins over a bare name for the same slug (case-insensitive) — *why*: registering both raises `ToolNameCollisionError`.
3. Implement dotted-path expansion in `hydrate_params` — *why*: `dataset_manager` stores secrets nested inside `datasources[i]`.
4. Write the tests — *why*: AC2 (no plaintext) depends on `mask_spec` correctness.

### `packages/ai-parrot/src/parrot/tools/spec.py` (CREATE)
```python
"""Agent tooling specs (FEAT-593): the one shape for toolkit / MCP configuration."""
from __future__ import annotations

import copy
import hashlib
import json
import logging
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from parrot.security.vault_utils import retrieve_vault_credential  # verified: security/vault_utils.py:135

logger = logging.getLogger(__name__)

SECRET_MASK: str = "********"
MCP_SECRET_FIELDS: tuple[str, ...] = ("headers", "auth_config", "env")


class ToolkitSpec(BaseModel):
    """Agent-level (or per-user override) configuration of one toolkit."""

    model_config = ConfigDict(extra="forbid")
    slug: str
    params: dict[str, Any] = Field(default_factory=dict)
    user_overridable: list[str] = Field(default_factory=list)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    vault_owner: str | None = None


class AgentMCPServerSpec(BaseModel):
    """Agent-level MCP server; ``headers``/``auth_config``/``env`` live in the vault."""

    model_config = ConfigDict(extra="forbid")
    name: str
    transport: str = "http"
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    allowed_tools: list[str] | None = None
    blocked_tools: list[str] | None = None
    description: str | None = None
    auth_type: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    vault_owner: str | None = None


class NormalizedTooling(BaseModel):
    """Output of :func:`normalize_tooling`."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    tools: list[Any] = Field(default_factory=list)
    toolkits: list[ToolkitSpec] = Field(default_factory=list)
    mcp_servers: list[AgentMCPServerSpec] = Field(default_factory=list)


def toolkit_vault_name(slug: str, agent_name: str) -> str:
    """Return ``f"toolkit_{slug}_{agent_name}"``."""
    return f"toolkit_{slug}_{agent_name}"


def mcp_vault_name(server: str, agent_name: str) -> str:
    """Return ``f"mcp_agent_{server}_{agent_name}"`` (never collides with per-user ``mcp_``)."""
    return f"mcp_agent_{server}_{agent_name}"
```
**Why this shape**: `extra="forbid"` makes a typo in a YAML entry fail loudly at load time
(normalize drops it with a WARNING instead of registering garbage). The vault-name helpers
live here so writer (TASK-3659) and reader (TASK-3654) can never disagree.

### `packages/ai-parrot/src/parrot/tools/spec.py` (CREATE — continued: functions)
```python
def normalize_tooling(
    tools: Sequence[Any] | None,
    toolkits: Sequence[Any] | None = None,
    mcp_servers: Sequence[Any] | None = None,
    *,
    toolkit_config: dict[str, dict[str, Any]] | None = None,
) -> NormalizedTooling:
    """Merge every legacy shape into (tools, toolkit specs, mcp specs).

    Bare strings in ``toolkits`` become ``ToolkitSpec(slug=s)``; dicts are validated.
    ``toolkit_config`` is the DB JSONB map ``{slug: spec-dict}`` (``slug`` key optional).
    A slug that is both a plain tool name and a spec is emitted once, as the spec.
    Duplicate specs for one slug: the last one wins (WARNING). Invalid entries → WARNING, dropped.
    """
    specs: dict[str, ToolkitSpec] = {}
    # FILL IN: collect specs from `toolkits` (str | dict | ToolkitSpec) then `toolkit_config`
    #   (inject slug=key when absent); catch ValidationError → logger.warning + skip — bounded by spec §3 M1
    # FILL IN: build `plain` from `tools`: keep non-str items in order; keep str items whose
    #   .lower() is not a key of `specs` (compare lowercased) — bounded by AC13 / no double registration
    # FILL IN: build mcp list from `mcp_servers` (dict | AgentMCPServerSpec); a dict carrying raw
    #   headers/auth_config/env (legacy YAML) is accepted: move those keys into `params` untouched
    #   so the factory keeps working — they are NOT vaulted here (TASK-3659 vaults on Studio save)
    return NormalizedTooling(tools=plain, toolkits=list(specs.values()), mcp_servers=mcp)


def tooling_revision(toolkits: Sequence[ToolkitSpec], mcp_servers: Sequence[AgentMCPServerSpec]) -> str:
    """sha256 of the canonical JSON of both lists (secret values are never in a spec)."""
    payload = {
        "toolkits": [t.model_dump(mode="json") for t in toolkits],
        "mcp": [m.model_dump(mode="json") for m in mcp_servers],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _set_dotted(target: dict[str, Any], dotted: str, value: Any) -> None:
    """Set ``value`` at ``a.0.b`` inside nested dicts/lists (list indexes are ints)."""
    # FILL IN: walk the path; digit segments index lists (extend with {} if short);
    #   other segments index dicts (setdefault {}) — bounded by M1 dotted-key contract


async def hydrate_params(spec: ToolkitSpec) -> dict[str, Any]:
    """Return a deep copy of ``spec.params`` with vault secrets restored.

    Raises KeyError (missing vault entry) / RuntimeError (vault unconfigured). Never logs values.
    """
    params = copy.deepcopy(spec.params)
    if not spec.secret_refs:
        return params
    # FILL IN: group secret_refs by vault name; for each: secrets = await retrieve_vault_credential(
    #   spec.vault_owner or "", vault_name); for each dotted key → _set_dotted(params, key, secrets[key])
    #   (missing key inside the entry → KeyError) — bounded by AC2
    return params


async def hydrate_mcp(spec: AgentMCPServerSpec) -> dict[str, Any]:
    """Return ``MCPServerConfig`` kwargs with headers/auth_config/env restored from the vault."""
    # FILL IN: base = spec fields except params/secret_refs/vault_owner (drop None) + spec.params;
    #   for field in secret_refs: base[field] = (await retrieve_vault_credential(owner, name))[field]
    raise NotImplementedError


def mask_spec(spec: ToolkitSpec) -> dict[str, Any]:
    """API dump: every ``secret_refs`` key rendered as ``SECRET_MASK`` inside ``params``."""
    data = spec.model_dump(mode="json")
    for dotted in spec.secret_refs:
        _set_dotted(data["params"], dotted, SECRET_MASK)
    return data


def mask_mcp(spec: AgentMCPServerSpec) -> dict[str, Any]:
    """API dump of an MCP spec: each vaulted field rendered as ``SECRET_MASK``."""
    data = spec.model_dump(mode="json")
    for field in spec.secret_refs:
        data[field] = SECRET_MASK
    return data
```
**Why**: `hydrate_*` are the only async functions so they can run in `configure()`
(TASK-3654) — never from the sync `__init__`. `mask_*` exist so no handler ever hand-builds a
masked dict.

### FILL IN checklist
- [ ] `normalize_tooling` — spec collection, dedupe, mcp list; bounded by spec §3 M1 + AC13
- [ ] `_set_dotted` — nested dict/list writer; bounded by the dotted-key contract
- [ ] `hydrate_params` — vault grouping + expansion; bounded by AC2 (never log values)
- [ ] `hydrate_mcp` — MCPServerConfig kwargs; bounded by spec §2 Data Models

---

## Acceptance Criteria

- [ ] `from parrot.tools.spec import ToolkitSpec, AgentMCPServerSpec, normalize_tooling, hydrate_params, mask_spec` works.
- [ ] `normalize_tooling(["jira", "weather"], [{"slug": "jira", "params": {"default_project": "T"}}])`
      → tools `["weather"]`, one `jira` spec (AC13 dedupe).
- [ ] `tooling_revision` is stable across calls and changes when a param changes.
- [ ] `hydrate_params` restores `datasources.0.dsn` into `params["datasources"][0]["dsn"]`.
- [ ] `mask_spec` never contains a vaulted value (AC2).
- [ ] `ruff check packages/ai-parrot/src/parrot/tools/spec.py` clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/tools/test_tooling_spec.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_tooling_spec.py
import pytest
from parrot.tools import spec as spec_module
from parrot.tools.spec import (
    AgentMCPServerSpec, SECRET_MASK, ToolkitSpec, hydrate_params, mask_spec, normalize_tooling, tooling_revision,
)


@pytest.fixture
def fake_vault(monkeypatch):
    store = {("42", "toolkit_dataset_manager_a1"): {"datasources.0.dsn": "postgres://secret"}}

    async def _retrieve(user_id, vault_name):
        return store[(user_id, vault_name)]

    monkeypatch.setattr(spec_module, "retrieve_vault_credential", _retrieve)
    return store


def test_normalize_dedupes_slug():
    out = normalize_tooling(["jira", "weather"], [{"slug": "jira", "params": {"default_project": "T"}}])
    assert out.tools == ["weather"]
    assert [s.slug for s in out.toolkits] == ["jira"]


def test_normalize_toolkit_config_map_injects_slug():
    out = normalize_tooling([], toolkit_config={"querysource": {"params": {"programs": ["troc"]}}})
    assert out.toolkits[0].slug == "querysource"


def test_normalize_drops_invalid_entry(caplog):
    out = normalize_tooling([], [{"slug": "x", "bogus": 1}])
    assert out.toolkits == []


def test_revision_stable_and_sensitive():
    a = [ToolkitSpec(slug="jira", params={"p": 1})]
    assert tooling_revision(a, []) == tooling_revision(a, [])
    assert tooling_revision(a, []) != tooling_revision([ToolkitSpec(slug="jira", params={"p": 2})], [])


@pytest.mark.asyncio
async def test_hydrate_dotted_datasource_secret(fake_vault):
    s = ToolkitSpec(slug="dataset_manager", params={"datasources": [{"kind": "sql", "name": "d", "sql": "x"}]},
                    secret_refs={"datasources.0.dsn": "toolkit_dataset_manager_a1"}, vault_owner="42")
    params = await hydrate_params(s)
    assert params["datasources"][0]["dsn"] == "postgres://secret"
    assert "dsn" not in s.params["datasources"][0]  # original untouched


def test_mask_spec_masks_every_ref():
    s = ToolkitSpec(slug="jira", params={"server_url": "u"}, secret_refs={"token": "v"}, vault_owner="1")
    assert mask_spec(s)["params"]["token"] == SECRET_MASK
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Overview, §3 module, §7 risks).
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import and
   signature listed still exists (`grep`/`read`). If anything moved, update the contract first.
4. **Update status** in `sdd/tasks/index/tool-configuration-agentstudio.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria; run the Validation Commands (in a worktree prefix with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-tools/src`).
7. **Move this file** to `sdd/tasks/completed/` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note


- Task: TASK-3645
- Feature: tool-configuration-agentstudio
- Implementation SHA: a6153ab0e37a6d450968b29b2b50a5188e4a68d0
- Closed at (UTC): 2026-09-23T14:03:23+00:00
- Fix commits: a6153ab0e37a6d450968b29b2b50a5188e4a68d0

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 1 |
| feedback_id | coder-feedback: recorded separately via coder_record_feedback |
| notes | Merge-tier validation (packages/ai-parrot/tests/tools) initially failed at collection: 'from parrot.tools import spec as spec_module' triggered the package's PEP 562 __getattr__ via hasattr() in Python's fromlist import resolution before the submodule existed, raising ImportError uncaught by hasattr(). Fixed in-scope (test file only) by using a plain dotted absolute import, per the task's own Codebase Contract note. Re-run: 53 failed / 2053 passed / 105 skipped, none in test_tooling_spec.py or test_config_schema.py, and no existing file was modified by this task (confirmed via git diff --stat against origin/dev) -- the 53 failures are pre-existing and unrelated to FEAT-593. |
| review_id | coder-review:e94e8becff1ecf1e40f37eba |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 160.97s · Tokens: n/a |
