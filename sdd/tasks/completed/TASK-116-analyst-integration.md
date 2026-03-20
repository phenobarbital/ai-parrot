# TASK-116: Analyst Integration

**Feature**: FEAT-010
**Spec**: `sdd/specs/finance-research-collective-memory.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-113, TASK-114
**Assigned-to**: claude-session

---

## Context

This task integrates query tools into analyst agents. Analysts now "pull" research from collective memory instead of "receiving" it. This enables cross-pollination and historical comparison.

Reference: Spec Section 3 "Module 7: Analyst Integration"

---

## Scope

- Add query tools (`get_latest_research`, `get_research_history`, `get_cross_domain_research`) to each analyst
- Update analyst prompts to use pull model
- Enable cross-pollination by accessing other domains' research
- Update `CommitteeDeliberation` to pass memory tools to analysts

**NOT in scope**:
- Research crew integration (TASK-115)
- Memory implementation (already done)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/agents/analysts.py` | MODIFY | Add query tools to analysts |
| `parrot/finance/prompts.py` | MODIFY | Update analyst prompts for pull model |
| `parrot/finance/swarm.py` | MODIFY | Update deliberation to use memory |

---

## Implementation Notes

### Adding Tools to Analysts

```python
# parrot/finance/agents/analysts.py
from parrot.finance.research.memory.tools import (
    get_latest_research,
    get_research_history,
    get_cross_domain_research,
)


def create_analyst(
    analyst_id: str,
    domain: str,
    client: AbstractClient,
) -> Agent:
    """Create an analyst agent with research query tools."""

    # Query tools for pulling research
    query_tools = [
        get_latest_research,
        get_research_history,
        get_cross_domain_research,
    ]

    # Domain-specific analysis tools
    domain_tools = get_analyst_domain_tools(domain)

    all_tools = query_tools + domain_tools

    return Agent(
        name=analyst_id,
        client=client,
        system_prompt=ANALYST_PROMPTS[analyst_id],
        tools=all_tools,
        use_tools=True,
        max_iterations=15,
    )


def create_all_analysts(client: AbstractClient) -> dict[str, Agent]:
    """Create all 5 analysts with query tools."""
    analysts = {}
    for analyst_id in ["macro_analyst", "equity_analyst", "crypto_analyst",
                       "sentiment_analyst", "risk_analyst"]:
        domain = analyst_id.replace("_analyst", "")
        analysts[analyst_id] = create_analyst(analyst_id, domain, client)
    return analysts
```

### Updated Analyst Prompts

```python
# parrot/finance/prompts.py

ANALYST_QUERY_PREAMBLE = """
You have access to the collective research memory. Use these tools to gather research:

1. `get_latest_research(domain)` - Get the most recent research for a domain
2. `get_research_history(domain, last_n)` - Get N recent research documents for comparison
3. `get_cross_domain_research(domains)` - Get latest research from multiple domains

WORKFLOW:
1. First, pull research for your primary domain using `get_latest_research`
2. If you need historical comparison, use `get_research_history`
3. For cross-pollination, use `get_cross_domain_research` to access other domains

You are NOT receiving research passively - you must actively query for it.

"""

MACRO_ANALYST_PROMPT = ANALYST_QUERY_PREAMBLE + """
You are the Macro Analyst. Your role is to analyze macroeconomic conditions and their market implications.

RESEARCH GATHERING:
1. Call `get_latest_research("macro")` to get the latest macro research
2. Call `get_research_history("macro", 2)` to compare with previous period
3. Call `get_cross_domain_research(["sentiment", "risk"])` for cross-pollination

ANALYSIS:
Based on the gathered research:
- Identify key macroeconomic trends
- Assess impact on different asset classes
- Highlight risks and opportunities
- Compare with previous period findings

OUTPUT:
Provide your analysis as a structured assessment with:
- Current macro environment summary
- Key changes from previous period
- Asset class implications
- Risk factors
- Actionable insights
"""

CRYPTO_ANALYST_PROMPT = ANALYST_QUERY_PREAMBLE + """
You are the Crypto Analyst. Your role is to analyze cryptocurrency markets and DeFi trends.

RESEARCH GATHERING:
1. Call `get_latest_research("crypto")` to get the latest crypto research
2. Call `get_research_history("crypto", 3)` to see 4-hour trend (crypto updates every 4h)
3. Call `get_cross_domain_research(["macro", "sentiment"])` for market context

ANALYSIS:
Based on the gathered research:
- Analyze on-chain metrics and their implications
- Assess DeFi protocol trends
- Evaluate market sentiment in crypto
- Cross-reference with macro conditions

OUTPUT:
Provide your analysis with crypto-specific insights and trading implications.
"""

# Similar updates for equity, sentiment, risk analysts...

ANALYST_PROMPTS = {
    "macro_analyst": MACRO_ANALYST_PROMPT,
    "equity_analyst": EQUITY_ANALYST_PROMPT,
    "crypto_analyst": CRYPTO_ANALYST_PROMPT,
    "sentiment_analyst": SENTIMENT_ANALYST_PROMPT,
    "risk_analyst": RISK_ANALYST_PROMPT,
}
```

### Update CommitteeDeliberation

```python
# parrot/finance/swarm.py
from parrot.finance.research.memory import FileResearchMemory


class CommitteeDeliberation:
    """Orchestrate analyst deliberation using collective memory."""

    def __init__(
        self,
        memory: FileResearchMemory,
        client: AbstractClient,
        # ...
    ):
        self.memory = memory
        self.client = client
        self._analysts = create_all_analysts(client)
        # ...

    async def run_deliberation(
        self,
        portfolio: Portfolio,
        constraints: Constraints,
    ) -> InvestmentMemo:
        """Run deliberation with analysts pulling from memory.

        Analysts now query the collective memory themselves via tools.
        No need to pass briefings explicitly.
        """
        # Analysts will use their query tools to fetch research
        # The memory is accessible via global set_research_memory()

        # Run cross-pollination round
        cross_pollination_results = await self._run_cross_pollination()

        # Run debate rounds
        debate_results = await self._run_debate(cross_pollination_results)

        # Secretary synthesizes memo
        memo = await self._synthesize_memo(debate_results)

        return memo

    async def _run_cross_pollination(self) -> dict[str, Any]:
        """Each analyst gathers and shares research insights."""
        results = {}
        for analyst_id, analyst in self._analysts.items():
            # Analyst uses query tools internally
            result = await analyst.execute(
                "Gather research from collective memory and provide your initial analysis."
            )
            results[analyst_id] = result
        return results
```

### Key Constraints

- Analysts must actively call query tools (pull model)
- Cross-pollination is enabled by `get_cross_domain_research`
- Historical comparison enabled by `get_research_history`
- Prompts must clearly instruct the pull workflow
- `CommitteeDeliberation` no longer passes briefings explicitly

### References in Codebase

- `parrot/finance/agents/analysts.py` — Current analyst creation
- `parrot/finance/prompts.py` — Current prompts
- `parrot/finance/swarm.py` — `CommitteeDeliberation` class

---

## Acceptance Criteria

- [ ] All 5 analysts have query tools (`get_latest_research`, `get_research_history`, `get_cross_domain_research`)
- [ ] Analyst prompts include query preamble
- [ ] Prompts instruct pull workflow (query → analyze → output)
- [ ] Cross-pollination enabled via `get_cross_domain_research`
- [ ] `CommitteeDeliberation` updated for pull model
- [ ] Analysts can execute and pull research successfully
- [ ] No linting errors

---

## Test Specification

```python
# tests/test_analyst_pull_model.py
import pytest
from parrot.finance.agents.analysts import create_all_analysts
from parrot.finance.research.memory.tools import set_research_memory


class TestAnalystPullModel:
    @pytest.mark.asyncio
    async def test_analysts_have_query_tools(self, mock_client):
        analysts = create_all_analysts(mock_client)

        for analyst_id, analyst in analysts.items():
            tool_names = [t.name for t in analyst.tools]
            assert "get_latest_research" in tool_names
            assert "get_research_history" in tool_names
            assert "get_cross_domain_research" in tool_names

    @pytest.mark.asyncio
    async def test_analyst_pulls_research(self, mock_client, populated_memory):
        """Analyst should pull research via tools."""
        set_research_memory(populated_memory)

        analyst = create_analyst(
            "macro_analyst",
            "macro",
            mock_client,
        )

        # Execute analyst - it should call get_latest_research
        # ...

    @pytest.mark.asyncio
    async def test_cross_pollination(self, mock_client, populated_memory):
        """Analyst can access other domains' research."""
        set_research_memory(populated_memory)

        # Macro analyst accesses sentiment research
        # ...
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — TASK-113 and TASK-114 must be complete
2. **Read current** `agents/analysts.py`, `prompts.py`, and `swarm.py`
3. **Update status** → `"in-progress"`
4. **Add tools** to analyst creation
5. **Update prompts** for pull model
6. **Update** `CommitteeDeliberation`
7. **Run tests**: `pytest tests/test_analyst_pull_model.py -v`
8. **Move to completed** and update index

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-03
**Notes**:
- Added `ANALYST_QUERY_PREAMBLE` to `parrot/finance/prompts.py` with pull-based research instructions
- Updated all 5 analyst prompts (MACRO, EQUITY, CRYPTO, SENTIMENT, RISK) to include preamble
- Added query tools (`get_latest_research`, `get_research_history`, `get_cross_domain_research`) to all analysts
- Created `_get_query_tools()` helper in `parrot/finance/agents/analysts.py`
- Added `create_analyst()` factory function for creating analysts by ID
- Updated `CommitteeDeliberation.configure()` in `parrot/finance/swarm.py` to pass query tools
- Updated `ANALYST_CONFIG` with `use_tools=True` for all analysts
- Added `_get_analyst_query_tools()` helper in swarm.py
- Created `tests/test_analyst_pull_model.py` with 19 passing tests
- All 106 related tests passing
