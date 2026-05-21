"""Entry point for the helpdesk orchestrator example.

Run scripted scenarios via ``--scenario``:

  hr           — vacation policy question, no escalation.
  it-clarify   — Outlook issue, orchestrator asks a clarifying question.
  tier1        — password reset, Tier-1 escalation (team manager).
  tier2        — production checkout outage, Tier-2 escalation (on-call).

Or run interactively without a flag to drive the orchestrator yourself.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from examples.orchestrator.escalation import read_tickets, reset_logs
from examples.orchestrator.hitl import SCRIPTED_ANSWERS
from examples.orchestrator.orchestrator import build_helpdesk_orchestrator


SCENARIOS: dict[str, dict[str, str]] = {
    "hr": {
        "question": "How many vacation days do I have per year?",
    },
    "it-clarify": {
        "question": "My email won't open this morning.",
        "scripted": "I'm on Windows. Outlook starts then closes immediately, no error visible.",
    },
    "tier1": {
        "question": "I can't reset my password — the SMS never arrives.",
        "scripted_employee_id": "12345678",
    },
    "tier2": {
        "question": (
            "Production order-service is down — customers cannot check "
            "out and we are bleeding revenue. Started 10 minutes ago."
        ),
        "scripted_employee_id": "12345678",
        "scripted_impact": "All checkout traffic blocked, ~$8k/min in lost orders.",
    },
}


def _seed_scripted_answers(scenario_cfg: dict[str, str]) -> None:
    """Pre-populate :data:`SCRIPTED_ANSWERS` for unattended runs."""
    if "scripted" in scenario_cfg:
        SCRIPTED_ANSWERS["details"] = scenario_cfg["scripted"]
        SCRIPTED_ANSWERS["describe"] = scenario_cfg["scripted"]
        SCRIPTED_ANSWERS["error"] = scenario_cfg["scripted"]
    if "scripted_employee_id" in scenario_cfg:
        SCRIPTED_ANSWERS["employee id"] = scenario_cfg["scripted_employee_id"]
        SCRIPTED_ANSWERS["badge"] = scenario_cfg["scripted_employee_id"]
    if "scripted_impact" in scenario_cfg:
        SCRIPTED_ANSWERS["impact"] = scenario_cfg["scripted_impact"]
        SCRIPTED_ANSWERS["customers affected"] = scenario_cfg["scripted_impact"]
        SCRIPTED_ANSWERS["revenue"] = scenario_cfg["scripted_impact"]


async def _maybe_load_indexes() -> None:
    """Attach pre-built PageIndex/FAISS indexes if ingest.py has been run."""
    from examples.orchestrator.knowledge.retrieval import PAGEINDEX_DIR

    if not any(PAGEINDEX_DIR.glob("*.json")):
        logging.getLogger("orchestrator").info(
            "No pre-built PageIndex found — using substring fallback. "
            "Run `python -m examples.orchestrator.knowledge.ingest` to "
            "enable real PageIndex retrieval."
        )
        return
    try:
        from examples.orchestrator.knowledge.ingest import build_all

        await build_all(reset=False)
    except Exception as exc:
        logging.getLogger("orchestrator").warning(
            "Could not load real indexes (%s); using fallback.", exc
        )


async def run_scenario(scenario: Optional[str], use_llm: str) -> None:
    cfg = SCENARIOS.get(scenario) if scenario else None
    if cfg:
        _seed_scripted_answers(cfg)
        question = cfg["question"]
        print(f"\n▶ Scripted scenario '{scenario}': {question}\n")
    else:
        question = input("Ask the helpdesk: ").strip()
        if not question:
            print("No question provided. Exiting.", file=sys.stderr)
            return

    await _maybe_load_indexes()
    orchestrator = await build_helpdesk_orchestrator(use_llm=use_llm)

    reset_logs()
    response = await orchestrator.conversation(
        question=question,
        use_conversation_history=False,
    )

    print("\n" + "=" * 72)
    print("ORCHESTRATOR RESPONSE")
    print("=" * 72)
    print(response.content)

    tickets = read_tickets()
    if tickets:
        print("\n" + "-" * 72)
        print(f"Tickets created ({len(tickets)}):")
        for t in tickets:
            print(f"  • {t['ticket_id']} ({t['tier']}, {t['priority']}) — {t['summary']}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()),
        help="Run a pre-scripted scenario instead of interactive input.",
    )
    parser.add_argument(
        "--use-llm",
        default="google",
        help="LLM backend for the orchestrator (default: google).",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable debug logging."
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    try:
        asyncio.run(run_scenario(args.scenario, args.use_llm))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
