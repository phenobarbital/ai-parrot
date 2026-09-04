# TASK-2827: Prune policies (`PrunePolicy` registry, built-ins, `prune_turn`)

**Feature**: FEAT-525 — Per-Turn Conversation Compaction
**Spec**: `sdd/specs/per-turn-conversation-compaction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2819, TASK-2822
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7, §2 "Rendered text formats (normative)" (PRUNED view),
goals G6/G7 and the resolved decision "Per-tool `PrunePolicy`: registry keyed
by tool name". A PRUNED view keeps the user message and assistant text intact
and replaces each invocation's I/O with a one-line notice carrying enough to
recover the bytes (`id="om_…"`) or to re-run the tool. Errors are never
omitted (C7). This task delivers only pure functions; `compact_history`
(TASK-2828) decides *which* turns/invocations get pruned.

---

## Scope

- Create `parrot/memory/compaction/policies.py` with:
  - `POLICY_VERSION: str = "1"`.
  - `@dataclass(frozen=True) class PrunedInvocation: notice: str; omissions: Tuple[Omission, ...]`.
  - `class PrunePolicy(Protocol)`: `name: str`; `def prune(self, inv: ToolInvocation, *, turn_id: str, limit: Limit) -> PrunedInvocation`.
  - Shared line builder `format_invocation_line(inv, *, limit, body: str) -> str` producing
    `"- {tool_name} {ok|error}[ {elapsed:.1f}s] in={canonical_input[:limit.max_input_chars]}{…} {body}"`
    where `body` is the notice or the `error=` fragment; `in=` uses
    `orjson.dumps(inv.input, option=orjson.OPT_SORT_KEYS).decode()` truncated with `…`;
    `elapsed` printed only when `elapsed_ms is not None`.
  - Notice builder `omission_notice(inv, content_id, chars) -> str` =
    `<tool-output-omitted tool="{name}" chars="{chars}" id="{content_id}"[ wm="{wm_key}"]/>`
    (`wm=` only when `inv.wm_key`).
  - Built-ins (each `name` = class slug), all sharing this rule set: **if `inv.error`** → line ends with
    `error={inv.error}` (verbatim, already condensed by Stage 0) and, when output exists, the notice
    is still emitted before the `error=` fragment; **if `"output" in inv.omitted`** → notice with the
    stored id and `chars=inv.output_chars`, **no new Omission**; **else if `inv.output`** → notice with
    `content_id(inv.output)`, `chars=len(inv.output)`, one `Omission(content_id, inv.output, turn_id, tool_name, "output")`;
    **else** → no notice (nothing to omit).
    - `DefaultPolicy` — exactly the shared rules.
    - `FileWritePolicy` — `in=` summary keeps only `path` (or `file_path`/`filename` if present) and appends
      `out=written {chars:,} bytes`-style summary instead of the raw excerpt; content omitted.
    - `FileReadPolicy` — keep `path`; omit content.
    - `ShellPolicy` — keep `command`/`cmd` and an `exit=` code when the output JSON carries one; omit stdout/stderr.
    - `SubAgentPolicy` — keep the `task`/`prompt` first line; omit transcript.
    - `QueryPolicy` — keep `query`/`sql`/`url` and a `rows=`/`hits=` count when the output JSON is a list or has
      `rows`/`results`; omit body.
  - Alias table (module-level dict, small, editable): e.g. `write_file/save_file → FileWritePolicy`,
    `read_file/open_file → FileReadPolicy`, `bash/shell/run_command/execute_command → ShellPolicy`,
    `delegate/run_subagent/spawn_agent → SubAgentPolicy`, `query_database/execute_query/sql_query/http_request/fetch_url/web_search/search → QueryPolicy`.
    Names are a starter set — implementer keeps it small and tested.
  - `register_policy(tool_name: str, policy: PrunePolicy) -> None` (module registry; overrides alias/default).
  - `get_policy(tool_name: str) -> PrunePolicy`: registry exact name → alias table → `DefaultPolicy()`.
  - `prune_turn(turn: ConversationTurn, *, limit: Limit = Limit(), policies: Optional[Mapping[str, PrunePolicy]] = None) -> Tuple[str, Tuple[Omission, ...]]`:
    `""` when the turn has no invocations; otherwise
    `"\n\n<tool-activity>\n" + "\n".join(lines) + "\n</tool-activity>"` plus, **only when at least one
    `<tool-output-omitted` notice was emitted**, the trailing line
    `"\nOmitted content can be recovered with read_omitted_content(content_id) or read_omitted_content(turn_id=\"{turn_id}\")."`.
    `policies` (when given) is consulted before the module registry.
- Unit tests in `packages/ai-parrot/tests/unit/memory/compaction/test_policies.py`.

**NOT in scope**: RAW-view rendering (`render_tool_activity`, TASK-2828);
deciding which turns are pruned (TASK-2828); storing omissions (bot,
TASK-2830); a `prune_policy` attribute on `AbstractTool` (non-goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/compaction/policies.py` | CREATE | protocol, `PrunedInvocation`, line/notice builders, six built-ins, alias table, registry, `prune_turn` |
| `packages/ai-parrot/tests/unit/memory/compaction/test_policies.py` | CREATE | registry/default, errors kept, offloaded id reuse, notice format, suffix shape |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use only what is listed here. Verify anything else before using it.

### Verified Imports
```python
from parrot.memory.abstract import ConversationTurn                                   # dev: memory/abstract.py:11
from parrot.memory.compaction.models import ToolInvocation, ToolStatus, Omission, Limit   # TASK-2819
from parrot.memory.compaction.omission import content_id                              # TASK-2822 ("om_" + blake2b-8 hexdigest)
import orjson                                                                          # verified: 3.12.0
from typing import Protocol, Mapping, Optional, Tuple
```

### Existing Signatures to Use
```python
# models.py (TASK-2819)
class ToolInvocation: tool_name: str; input: Dict[str, Any]; output: Optional[str]; status: ToolStatus
                      error: Optional[str]; elapsed_ms: Optional[int]; output_chars: Optional[int]
                      omitted: Dict[str, str]  # "output" -> "om_…" when offloaded at write time (TASK-2826)
                      wm_key: Optional[str]    # FEAT-380 tee key
class Limit: max_invocations=12; max_input_chars=200; max_output_chars=400; max_block_tokens=1_500   # only max_input_chars used here
class Omission(frozen): content_id: str; content: str; turn_id: str; tool_name: str; field: str

# Normative PRUNED format (spec §2):
# <tool-activity>
# - query_database ok 1.2s in={"sql":"SELECT * FROM sales …"} <tool-output-omitted tool="query_database" chars="48213" id="om_3f9a1c2b7d4e5f60" wm="__tee__:query_database:…"/>
# - write_file ok 0.1s in={"path":"report.md"} <tool-output-omitted tool="write_file" chars="2140" id="om_…"/>
# - fetch_url error 3.0s in={"url":"https://…"} error=HTTPError 503 (condensed)
# </tool-activity>
# Omitted content can be recovered with read_omitted_content(content_id) or read_omitted_content(turn_id="…").
```

### Does NOT Exist
- ~~`parrot.memory.compaction.policies`~~ — this task creates it.
- ~~`AbstractTool.prune_policy`~~ — non-goal; registry keyed by tool name only.
- ~~A registry of tool names in `parrot.memory`~~ — none; the alias table here is a best-effort starter, unknown names → `DefaultPolicy`.
- ~~`ToolInvocation.result` / `.arguments`~~ — the fields are `output` / `input` (ToolCall's names were mapped in TASK-2819).
- ~~Omitting `error`~~ — forbidden by C7; every built-in must keep `error=` verbatim.
- ~~Importing `parrot.tools`~~ — leaf-module rule (spec §7); the policies module never imports tools, bots or clients.

---

## Implementation Notes

### Pattern to Follow
```python
class DefaultPolicy:
    name = "default"
    def prune(self, inv: ToolInvocation, *, turn_id: str, limit: Limit) -> PrunedInvocation:
        omissions: list[Omission] = []
        parts: list[str] = []
        if "output" in inv.omitted:
            parts.append(omission_notice(inv, inv.omitted["output"], inv.output_chars or len(inv.output or "")))
        elif inv.output:
            cid = content_id(inv.output)
            omissions.append(Omission(cid, inv.output, turn_id, inv.tool_name, "output"))
            parts.append(omission_notice(inv, cid, len(inv.output)))
        if inv.error:
            parts.append(f"error={inv.error}")
        return PrunedInvocation(format_invocation_line(inv, limit=limit, body=" ".join(parts)), tuple(omissions))
```

### Key Constraints
- Pure and synchronous; no logging, no I/O; content ids computed here via `content_id` (same function the store uses, so ids match TASK-2826's write-time offload).
- `in=` truncation happens **after** canonical JSON so key order is stable across renders (determinism, C1).
- Status word: `"error"` when `inv.status is ToolStatus.ERROR or inv.error`, else `"ok"`.
- `prune_turn` must not read `context_used` and must not mutate the turn.

### References in Codebase
- `packages/ai-parrot/src/parrot/security/groundedness/normalize.py` — pure/sync module style.
- `packages/ai-parrot/src/parrot/tools/compression/tee.py:161-182` — where `wm_key` values originate (read-only context).

---

## Acceptance Criteria

- [ ] `get_policy("query_database")` is a `QueryPolicy`; `get_policy("totally_unknown")` is a `DefaultPolicy`; `register_policy("query_database", custom)` makes `get_policy` return `custom`.
- [ ] Every built-in keeps `error=…` verbatim in its line; notices carry `tool`, `chars`, `id` and `wm=` only when `wm_key` is set (regex-checked).
- [ ] An invocation with `omitted["output"] = "om_abc"` and `output_chars=48213` yields a notice with `id="om_abc" chars="48213"` and **zero** new `Omission`s.
- [ ] A fresh output yields exactly one `Omission` whose `content_id == content_id(output)`; the notice's `id` matches it.
- [ ] `prune_turn` returns `""` for a turn without invocations; with invocations the suffix starts with `"\n\n<tool-activity>\n"`, ends with `</tool-activity>` (plus the recovery hint line iff a notice exists); same input ⇒ identical bytes.
- [ ] All tests pass: `timeout -s KILL 300 pytest packages/ai-parrot/tests/unit/memory/compaction/test_policies.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/compaction/policies.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/memory/compaction/test_policies.py
import re
from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import Limit, ToolInvocation, ToolStatus
from parrot.memory.compaction.omission import content_id
from parrot.memory.compaction import policies as p

NOTICE = re.compile(r'<tool-output-omitted tool="(\w+)" chars="(\d+)" id="(om_[0-9a-f]{16})"( wm="[^"]+")?/>')


def test_policy_registry_and_default():
    assert isinstance(p.get_policy("query_database"), p.QueryPolicy)
    assert isinstance(p.get_policy("nope"), p.DefaultPolicy)
    custom = p.DefaultPolicy(); p.register_policy("nope", custom)
    assert p.get_policy("nope") is custom


def test_policies_keep_errors_and_notice_shape():
    inv = ToolInvocation(tool_name="fetch_url", input={"url": "https://x"}, output="body", status=ToolStatus.ERROR,
                         error="HTTPError 503", elapsed_ms=3000, wm_key="__tee__:fetch_url:t:1")
    for policy in (p.DefaultPolicy(), p.FileWritePolicy(), p.FileReadPolicy(), p.ShellPolicy(), p.SubAgentPolicy(), p.QueryPolicy()):
        out = policy.prune(inv, turn_id="t", limit=Limit())
        assert "error=HTTPError 503" in out.notice and out.notice.startswith("- fetch_url error 3.0s in=")
        m = NOTICE.search(out.notice); assert m and m.group(4) == ' wm="__tee__:fetch_url:t:1"'


def test_prune_turn_reuses_offloaded_id():
    inv = ToolInvocation(tool_name="q", input={}, output="preview …", omitted={"output": "om_0123456789abcdef"}, output_chars=48213)
    turn = ConversationTurn(turn_id="t1", user_id="u", user_message="q", assistant_response="a", tool_invocations=[inv])
    suffix, omissions = p.prune_turn(turn)
    assert omissions == () and 'id="om_0123456789abcdef" chars="48213"' in suffix.replace('chars="48213" id="om_0123456789abcdef"', 'id="om_0123456789abcdef" chars="48213"')
    assert suffix.startswith("\n\n<tool-activity>\n") and 'read_omitted_content(turn_id="t1")' in suffix


def test_prune_turn_fresh_output_and_empty():
    big = "x" * 5000
    turn = ConversationTurn(turn_id="t2", user_id="u", user_message="q", assistant_response="a",
                            tool_invocations=[ToolInvocation(tool_name="q", input={"b": 1, "a": 2}, output=big)])
    suffix, (om,) = p.prune_turn(turn)
    assert om.content_id == content_id(big) and om.content == big and om.turn_id == "t2" and om.field == "output"
    assert 'in={"a":2,"b":1}' in suffix and p.prune_turn(turn) == (suffix, (om,))
    assert p.prune_turn(ConversationTurn(turn_id="t3", user_id="u", user_message="q", assistant_response="a")) == ("", ())
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2819 and TASK-2822 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code; update it first if anything changed
4. **Update status** in `sdd/tasks/index/per-turn-conversation-compaction.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2827-prune-policies.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
