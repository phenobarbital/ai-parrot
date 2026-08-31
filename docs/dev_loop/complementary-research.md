# Complementary (collaborative) research partner (FEAT-482)

FEAT-482 adds an **opt-in, read-only collaborative research partner** that
investigates a dev-flow/dev-loop request in parallel with the primary
Claude seat (`IdeationNode` in the dev-flow, `ResearchNode` in the ops
flow). The partner's findings are additive — the primary Claude seat reads
them, expands on them, and keeps sole authorship of every document it
writes. This is a **pure addition** ([R3]-style guarantee): an operator who
configures nothing sees byte-identical behaviour to before this feature.

## Why a collaborator, not an adversary

The repo already has an adversarial second opinion at *review* time
(`ParallelPerspectiveReviewDispatcher`, `dev_loop/code_review.py`) — a
seat that exists to challenge. Research wants the opposite: a second
researcher investigating the same request from its own angle, whose
findings the primary researcher reads and builds on. There is no verdict,
no pass/fail, and no "winning" side — just additive coverage from a model
in a different training lineage, which is the property that makes a
second opinion worth having at all.

## The two seats it serves

| Seat | Flow | Node | When it runs |
|---|---|---|---|
| Primary research (dev-flow) | dev-flow | `IdeationNode` | Round 1 only, concurrently with the node's existing wiki-context build |
| Primary research (ops) | dev-loop | `ResearchNode` | Once, alongside the existing wiki/graph-memory context injection, after the Jira ticket is resolved |

Both seats call the **same** `ComplementaryResearchCoordinator`
(`parrot.flows.dev_flow.complementary_research`) — one shared mechanism,
not a fork per flow.

## The two partner backends

Both backends authenticate with the **same `AWS_NOVA_API_KEY` Bedrock
credential** — no second vendor key, no Codex CLI dependency — and both
drive the identical `client.ask(prompt, use_tools=True,
structured_output=ResearchFindings)` call shape through one
`BedrockResearchPartner` implementation.

| Backend | Default model | Client | Transport | Reasoning knob |
|---|---|---|---|---|
| `gpt` (**default**) | `gpt-5.6-sol` | `BedrockMantleClient` | bedrock-mantle, OpenAI chat-completions | none wired (see note below) |
| `nova` | `us.amazon.nova-2-lite-v1:0` | `NovaClient` | Bedrock Converse | `thinking_budget` |

`gpt-5.6-sol` is the default because the seat exists to break confirmation
bias: with governance neutral (one AWS credential, one bill for either
choice), the remaining discriminator is training-lineage distance from the
primary Claude seat, and `gpt-5.6-sol` is furthest. `nova-2-lite` stays
selectable as the cheap option and the Converse-path test case.

**An Anthropic partner model is hard-rejected.** Configuring
`us.anthropic.*` / `global.anthropic.*` / `claude-*` for either backend's
model key raises `ValueError` naming both reasons: it would correlate
training priors with the primary Claude seat (defeating the seat's whole
purpose), and it 400s on Bedrock's legacy `thinking_budget` shape for
modern Anthropic models (fixed separately for every other Bedrock
Anthropic seat by this same feature's adaptive-thinking support in
`BedrockConverseBase`).

**Reasoning knob note**: `DEV_FLOW_RESEARCH_PARTNER_EFFORT` is read and
documented below for forward compatibility, but is **not currently
threaded into any call** — `BedrockMantleClient` inherits
`OpenAIBaseClient.ask()` unchanged, and that signature has no
`effort`/`reasoning_effort` parameter today. `DEV_FLOW_RESEARCH_PARTNER_
THINKING_BUDGET` **is** wired, Converse-only, for the `nova` backend.

## The read-only toolkit

The partner reads the repository through FEAT-484's `ReadOnlyRepoToolkit`
(`parrot.tools.repo`) — the partner's *only* repo-access surface. No
bespoke file/search/git tool is defined for this feature. The toolkit is
read-only by construction (no `write_file`/`apply_patch`/`run_command`
method exists on it, not behind a flag) — see
[`docs/tools/readonly-repo-toolkit.md`](../tools/readonly-repo-toolkit.md)
for its full tool list.

## Graph search for the primary Claude seat too

The primary Claude seat (`IdeationNode`'s `sdd-ideation` dispatch) also
gains three read-only MCP tools backed by the same AST/tree-sitter
knowledge-graph plane the partner uses: `mcp__wikitoolkit__wiki_query`,
`mcp__wikitoolkit__wiki_page`, `mcp__wikitoolkit__wiki_related`. This
requires a new `mcp_servers` field on `ClaudeCodeDispatchProfile` — the
dispatch's `strict_mcp_config` stays `True` (the safe default that isolates
a headless dispatch from the operator's interactive Claude Code
connectors), so the server must be passed explicitly rather than relying
on the filesystem `.mcp.json`. The write-shaped `wiki_remember` /
`wiki_note` tools are deliberately **not** exposed to this seat.

## The soft-degradation contract

`ComplementaryResearchCoordinator.research()` returns
`Optional[ComplementaryFindings]` and **never raises**. Every failure —
the seat disabled, a timeout, a credential error, a Bedrock outage, an
unparseable structured-output response, or empty/trivial findings —
becomes `None` plus a warning log and a `partner.degraded` event. The run
always completes normally, single-agent, exactly as it would with the
seat disabled.

On success, the coordinator renders the findings to
`sdd/proposals/<slug>.research.md` and commits it, staging **only that
path**. A write/commit failure does not lose the findings — the run still
receives them in memory with `document_path=""` and a warning.

## Configuration

All keys default to **off/inert** — an operator who sets none of these
sees byte-identical behavior to before this feature.

| Key | Default | Purpose |
|---|---|---|
| `DEV_FLOW_RESEARCH_PARTNER` | `""` (disabled) | Backend selector: `"gpt"` or `"nova"`. Unset/empty disables the seat entirely — no client is built, no work is performed. |
| `DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL` | `gpt-5.6-sol` | Bedrock-mantle model for the `"gpt"` backend. |
| `DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL` | `us.amazon.nova-2-lite-v1:0` | Bedrock Converse model for the `"nova"` backend. |
| `DEV_FLOW_RESEARCH_PARTNER_THINKING_BUDGET` | `4096` | Converse-only reasoning knob. Ignored on the `"gpt"` (mantle) path. |
| `DEV_FLOW_RESEARCH_PARTNER_EFFORT` | `high` | Reserved mantle-only reasoning knob — see the note above; not yet wired into any call. |
| `DEV_FLOW_RESEARCH_PARTNER_TIMEOUT` | `600` | Hard deadline, in seconds, the coordinator gives the partner before soft-degrading the run. |
| `DEV_FLOW_RESEARCH_PARTNER_MAX_TOKENS` | `16384` | Cost ceiling passed to the partner's `ask(max_tokens=...)` call. |
| `DEV_FLOW_RESEARCH_PARTNER_WEB_SEARCH` | **`true`** | See "Web-search egress" below. |
| `DEV_FLOW_IDEATION_MODEL` | `claude-opus-5` | The **primary** dev-flow research seat's model (replaces the hardwired `claude-sonnet-4-6`). Set `claude-fable-5` to trade cost for capability with no code change. |

### Web-search egress — read this before enabling the partner

`DEV_FLOW_RESEARCH_PARTNER_WEB_SEARCH` defaults to **`true`** *once the
partner itself is enabled*. When both are on, the partner's toolkit
exposes a keyless `web_search` tool (`DdgSearchTool`), and **brief content
— which may describe unreleased work — can reach a third-party search
provider** as part of the partner's own query formulation. This key is
independently switchable: set `DEV_FLOW_RESEARCH_PARTNER_WEB_SEARCH=false`
to keep the partner's repo-grounded tools while disabling that egress
path. The key is inert while `DEV_FLOW_RESEARCH_PARTNER` itself is unset,
so the pure-addition guarantee for an unconfigured deployment is
unaffected either way.

### Enabling the partner

```bash
# .env or environment
DEV_FLOW_RESEARCH_PARTNER=gpt          # or "nova"
# Everything else is optional — the defaults above apply.
```

No new required dependency, and no `OPENAI_API_KEY` — the `"gpt"` backend
reaches `gpt-5.6-sol` through bedrock-mantle on the same `AWS_NOVA_API_KEY`
Bedrock credential the `"nova"` backend (and the existing Nova
adversarial-review seat) already use. The feature degrades cleanly to
single-agent behavior without AWS credentials configured at all.
