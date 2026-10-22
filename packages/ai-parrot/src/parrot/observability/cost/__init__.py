"""parrot.observability.cost — USD cost calculation for LLM calls.

Namespace package. Concrete calculator lives in:
  * ``calculator`` — ``CostCalculator`` (TASK-1232)
  * ``pricing/`` — bundled JSON pricing tables (TASK-1232)
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from parrot.core.events.lifecycle.events import AfterClientCallEvent
    from parrot.observability.cost.calculator import CostCalculator

logger = logging.getLogger(__name__)
_LOCK = threading.Lock()
_SHARED: "Optional[CostCalculator]" = None


def get_shared_cost_calculator() -> "Optional[CostCalculator]":
    """Return the process-wide CostCalculator installed by observability bootstrap, or None."""
    return _SHARED


def set_shared_cost_calculator(calc: "Optional[CostCalculator]") -> None:
    """Install (or clear with None) the process-wide CostCalculator."""
    global _SHARED  # noqa: PLW0603
    with _LOCK:
        _SHARED = calc


def ensure_shared_cost_calculator() -> "CostCalculator":
    """Return the shared calculator, building one from PARROT_PRICING_PATH if none is installed."""
    global _SHARED  # noqa: PLW0603
    if _SHARED is not None:
        return _SHARED

    with _LOCK:
        if _SHARED is not None:
            return _SHARED

        override: Optional[str] = None
        try:
            from navconfig import config as nav_config  # noqa: PLC0415

            override = nav_config.get("PARROT_PRICING_PATH", fallback=None)
        except ImportError:
            logger.debug("navconfig not available; skipping PARROT_PRICING_PATH lookup.")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "navconfig raised an unexpected error during PARROT_PRICING_PATH lookup: %s",
                exc,
            )

        from parrot.observability.cost.calculator import CostCalculator  # noqa: PLC0415

        _SHARED = CostCalculator(override_path=override)
        return _SHARED


def resolve_event_cost(event: "AfterClientCallEvent", fallback: "Optional[CostCalculator]") -> Optional[float]:
    """Return the call's USD cost, computing it only when the origin did not.

    ``event.cost_usd`` wins when not None. Otherwise compute with the shared calculator, else ``fallback``
    (emitters that bypass AbstractClient, or tests that inject a calculator). Never raises.
    """
    if event.cost_usd is not None:
        return event.cost_usd
    calc = _SHARED or fallback
    if calc is None:
        return None
    from parrot.observability.attributes import resolve_gen_ai_system  # noqa: PLC0415

    try:
        return calc.cost_usd(
            provider=resolve_gen_ai_system(event.client_name),
            model=event.model,
            input_tokens=event.input_tokens or 0,
            output_tokens=event.output_tokens or 0,
        )
    except Exception:  # noqa: BLE001 — cost must never break telemetry
        logger.debug("resolve_event_cost failed", exc_info=True)
        return None
