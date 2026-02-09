"""
Anti-Hallucination Deterministic Guard Architecture.

4-layer defense preventing LLMs from executing unauthorized trades:
    Layer 1: ExecutorConstraints.validate_order() — pre-LLM portfolio checks
    Layer 2: ExecutionMandate — immutable contract of what is permitted
    Layer 3: SafeToolWrapper — intercepts each tool call for validation
    Layer 4: Post-execution reconciliation — verifies fill vs. request
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ..tools.abstract import AbstractTool, ToolResult

logger = logging.getLogger("TradingSwarm.Guards")


# =============================================================================
# VIOLATION TAXONOMY
# =============================================================================

class ViolationType(str, Enum):
    """Every class of deterministic violation the guard can detect."""
    SYMBOL_MISMATCH = "symbol_mismatch"
    SIDE_MISMATCH = "side_mismatch"
    QUANTITY_EXCEEDED = "quantity_exceeded"
    PRICE_OUT_OF_BAND = "price_out_of_band"
    MAX_VALUE_EXCEEDED = "max_value_exceeded"
    INSUFFICIENT_CASH = "insufficient_cash"
    DAILY_TRADE_LIMIT = "daily_trade_limit"
    DAILY_VOLUME_LIMIT = "daily_volume_limit"
    UNAUTHORIZED_TOOL = "unauthorized_tool"
    EXTRA_ORDER = "extra_order"
    HALLUCINATED_PRICE = "hallucinated_price"
    INVALID_COMPANION_ORDER = "invalid_companion_order"
    EXECUTION_MISMATCH = "execution_mismatch"
    EMERGENCY_HALT = "emergency_halt"


# Violations that ALWAYS block execution (never auto-correct)
CRITICAL_VIOLATIONS: frozenset[ViolationType] = frozenset({
    ViolationType.SYMBOL_MISMATCH,
    ViolationType.SIDE_MISMATCH,
    ViolationType.UNAUTHORIZED_TOOL,
    ViolationType.EXTRA_ORDER,
    ViolationType.HALLUCINATED_PRICE,
    ViolationType.EMERGENCY_HALT,
})


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass(frozen=True)
class GuardViolation:
    """Immutable record of a single violation detected by the guard."""
    violation_type: ViolationType
    message: str
    is_critical: bool
    tool_name: str = ""
    param_key: str = ""
    expected: Any = None
    actual: Any = None
    corrected_to: Any = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for logging and audit."""
        return {
            "type": self.violation_type.value,
            "message": self.message,
            "critical": self.is_critical,
            "tool": self.tool_name,
            "param": self.param_key,
            "expected": str(self.expected),
            "actual": str(self.actual),
            "corrected_to": str(self.corrected_to) if self.corrected_to is not None else None,
        }


@dataclass
class GuardResult:
    """Outcome of a guard validation check."""
    allowed: bool
    violations: list[GuardViolation] = field(default_factory=list)
    corrected_params: dict[str, Any] | None = None

    @property
    def has_critical(self) -> bool:
        return any(v.is_critical for v in self.violations)

    def summary(self) -> str:
        if not self.violations:
            return "PASS: all checks passed"
        if self.has_critical:
            crit = [v for v in self.violations if v.is_critical]
            return f"BLOCKED: {len(crit)} critical violation(s) — {crit[0].message}"
        return f"WARN: {len(self.violations)} non-critical violation(s)"


# =============================================================================
# EXECUTION MANDATE — immutable contract
# =============================================================================

@dataclass(frozen=True)
class ExecutionMandate:
    """Immutable contract: what the LLM is allowed to do for one order."""
    # Identity
    order_id: str
    symbol: str
    side: str              # "buy" | "sell"

    # Quantity
    max_quantity: float     # upper bound on shares/units
    min_quantity: float     # lower bound (usually 0 or a lot size)

    # Price band
    limit_price: float | None  # from order.limit_price
    price_band_pct: float      # allowed deviation from limit (default 2%)

    # Value limits
    max_value_usd: float       # absolute cap for this order
    available_cash_usd: float  # portfolio cash at mandate creation time

    # Daily limits (remaining at mandate time)
    daily_trades_remaining: int
    daily_volume_remaining_usd: float

    # Tool ACL
    allowed_tools: frozenset[str]  # tool names the LLM may invoke
    max_place_order_calls: int = 1  # how many order-placement calls are allowed

    # Companion orders
    stop_loss: float | None = None
    take_profit: float | None = None


def create_mandate_from_order(
    order: Any,
    portfolio: Any,
    constraints: Any,
    allowed_tools: set[str] | None = None,
    price_band_pct: float = 2.0,
) -> ExecutionMandate:
    """Build an ExecutionMandate from the real TradingOrder + PortfolioSnapshot.

    Adapts the real schema fields (sizing_pct, limit_price, etc.) into the
    flat mandate structure the guard expects.
    """
    # Compute max order value from sizing_pct, capped by constraint
    sizing_value = (order.sizing_pct * portfolio.total_value_usd / 100.0)
    max_value_usd = min(
        sizing_value,
        constraints.max_order_value_usd,
    ) if constraints else sizing_value

    # Compute max quantity from value and limit price
    if order.limit_price and order.limit_price > 0:
        max_qty = max_value_usd / order.limit_price
    elif order.quantity:
        max_qty = float(order.quantity)
    else:
        max_qty = 0.0

    # If the order already specifies a quantity, use it as the upper bound
    if order.quantity and order.quantity > 0:
        max_qty = min(max_qty, float(order.quantity)) if max_qty > 0 else float(order.quantity)

    daily_trades_remaining = (
        constraints.max_daily_trades - portfolio.daily_trades_executed
    ) if constraints else 999
    daily_volume_remaining = (
        constraints.max_daily_volume_usd - portfolio.daily_volume_usd
    ) if constraints else float("inf")

    return ExecutionMandate(
        order_id=order.id,
        symbol=order.asset,
        side=order.action.lower(),
        max_quantity=max_qty,
        min_quantity=0.0,
        limit_price=order.limit_price,
        price_band_pct=price_band_pct,
        max_value_usd=max_value_usd,
        available_cash_usd=portfolio.cash_available_usd,
        daily_trades_remaining=daily_trades_remaining,
        daily_volume_remaining_usd=daily_volume_remaining,
        allowed_tools=frozenset(allowed_tools or set()),
        max_place_order_calls=1,
        stop_loss=order.stop_loss,
        take_profit=order.take_profit,
    )


# =============================================================================
# DETERMINISTIC GUARD — 14 checks
# =============================================================================

class DeterministicGuard:
    """Validates tool calls against an ExecutionMandate using only Python logic."""

    # Tool names that count as "placing an order"
    ORDER_PLACEMENT_TOOLS: frozenset[str] = frozenset({
        "alpaca_place_order",
        "binance_place_order",
        "binance_place_oco",
    })

    def __init__(self, mandate: ExecutionMandate) -> None:
        self.mandate = mandate
        self._order_calls: int = 0
        self._violations: list[GuardViolation] = []
        self._halted: bool = False

    # ── public API ───────────────────────────────────────────────

    @property
    def violations(self) -> list[GuardViolation]:
        return list(self._violations)

    def halt(self) -> None:
        """Emergency halt — block everything from this point on."""
        self._halted = True

    def validate_tool_call(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> GuardResult:
        """Run all deterministic checks on a tool call.

        Returns a GuardResult:
            - allowed=True → proceed (possibly with corrected_params)
            - allowed=False → block the call
        """
        violations: list[GuardViolation] = []
        corrected: dict[str, Any] = dict(params)

        # ═══ Check 0: Emergency halt ═════════════════════════════
        if self._halted:
            v = GuardViolation(
                violation_type=ViolationType.EMERGENCY_HALT,
                message="Guard is in emergency halt — all calls blocked",
                is_critical=True,
                tool_name=tool_name,
            )
            violations.append(v)
            self._violations.extend(violations)
            return GuardResult(allowed=False, violations=violations)

        # ═══ Check 1: Tool authorization ═════════════════════════
        if self.mandate.allowed_tools and tool_name not in self.mandate.allowed_tools:
            v = GuardViolation(
                violation_type=ViolationType.UNAUTHORIZED_TOOL,
                message=f"Tool '{tool_name}' not in allowed set",
                is_critical=True,
                tool_name=tool_name,
                expected=sorted(self.mandate.allowed_tools),
                actual=tool_name,
            )
            violations.append(v)
            self._violations.extend(violations)
            return GuardResult(allowed=False, violations=violations)

        # ═══ Read-only tools: always allowed ═════════════════════
        if self._is_read_only_tool(tool_name):
            return GuardResult(allowed=True)

        # ═══ Cancel tools: always allowed ════════════════════════
        if "cancel" in tool_name.lower():
            return GuardResult(allowed=True)

        # ═══ Order placement tools: full validation ══════════════
        if self._is_order_tool(tool_name):
            return self._validate_place_order(tool_name, params, violations, corrected)

        # ═══ Companion tools (stop-loss, take-profit) ════════════
        if self._is_companion_tool(tool_name):
            return self._validate_companion(tool_name, params, violations, corrected)

        # Unknown tool type — allow but log
        return GuardResult(allowed=True)

    def reconcile_execution(
        self,
        requested_symbol: str,
        requested_side: str,
        requested_qty: float,
        requested_price: float | None,
        filled_symbol: str | None,
        filled_side: str | None,
        filled_qty: float | None,
        filled_price: float | None,
    ) -> GuardResult:
        """Post-execution reconciliation (Layer 4).

        Compares what was requested with what was filled.
        """
        violations: list[GuardViolation] = []

        if filled_symbol and filled_symbol.upper() != requested_symbol.upper():
            violations.append(GuardViolation(
                violation_type=ViolationType.EXECUTION_MISMATCH,
                message=f"Filled symbol {filled_symbol} != requested {requested_symbol}",
                is_critical=True,
                param_key="symbol",
                expected=requested_symbol,
                actual=filled_symbol,
            ))

        if filled_side and filled_side.lower() != requested_side.lower():
            violations.append(GuardViolation(
                violation_type=ViolationType.EXECUTION_MISMATCH,
                message=f"Filled side {filled_side} != requested {requested_side}",
                is_critical=True,
                param_key="side",
                expected=requested_side,
                actual=filled_side,
            ))

        if filled_qty is not None and requested_qty > 0:
            deviation = abs(filled_qty - requested_qty) / requested_qty
            if deviation > 0.10:  # >10% deviation
                violations.append(GuardViolation(
                    violation_type=ViolationType.EXECUTION_MISMATCH,
                    message=(
                        f"Filled qty {filled_qty} deviates {deviation:.1%} "
                        f"from requested {requested_qty}"
                    ),
                    is_critical=False,
                    param_key="quantity",
                    expected=requested_qty,
                    actual=filled_qty,
                ))

        if (
            filled_price is not None
            and requested_price is not None
            and requested_price > 0
        ):
            price_dev = abs(filled_price - requested_price) / requested_price
            if price_dev > 0.05:  # >5% slippage
                violations.append(GuardViolation(
                    violation_type=ViolationType.EXECUTION_MISMATCH,
                    message=(
                        f"Fill price ${filled_price:.4f} deviates {price_dev:.1%} "
                        f"from requested ${requested_price:.4f}"
                    ),
                    is_critical=False,
                    param_key="price",
                    expected=requested_price,
                    actual=filled_price,
                ))

        self._violations.extend(violations)
        has_critical = any(v.is_critical for v in violations)
        return GuardResult(
            allowed=not has_critical,
            violations=violations,
        )

    # ── private helpers ──────────────────────────────────────────

    @staticmethod
    def _is_read_only_tool(name: str) -> bool:
        read_prefixes = ("get_", "read_", "list_", "search_", "fetch_")
        return any(name.lower().startswith(p) or f"_{p[:-1]}" in name.lower()
                   for p in read_prefixes)

    @staticmethod
    def _is_order_tool(name: str) -> bool:
        return "place_order" in name.lower() or "place_oco" in name.lower()

    @staticmethod
    def _is_companion_tool(name: str) -> bool:
        return any(kw in name.lower() for kw in ("stop_loss", "take_profit", "trailing"))

    def _validate_place_order(
        self,
        tool_name: str,
        params: dict[str, Any],
        violations: list[GuardViolation],
        corrected: dict[str, Any],
    ) -> GuardResult:
        """Full deterministic validation of an order-placement tool call."""
        m = self.mandate

        # ── Extra order check ────────────────────────────────────
        self._order_calls += 1
        if self._order_calls > m.max_place_order_calls:
            violations.append(GuardViolation(
                violation_type=ViolationType.EXTRA_ORDER,
                message=f"Order call #{self._order_calls} exceeds limit of {m.max_place_order_calls}",
                is_critical=True,
                tool_name=tool_name,
                expected=m.max_place_order_calls,
                actual=self._order_calls,
            ))
            self._violations.extend(violations)
            return GuardResult(allowed=False, violations=violations)

        # ── Symbol check ─────────────────────────────────────────
        symbol = self._extract_symbol(params)
        if symbol and symbol.upper() != m.symbol.upper():
            violations.append(GuardViolation(
                violation_type=ViolationType.SYMBOL_MISMATCH,
                message=f"Symbol '{symbol}' != mandated '{m.symbol}'",
                is_critical=True,
                tool_name=tool_name,
                param_key="symbol",
                expected=m.symbol,
                actual=symbol,
            ))

        # ── Side check ───────────────────────────────────────────
        side = self._extract_side(params)
        if side and side.lower() != m.side:
            violations.append(GuardViolation(
                violation_type=ViolationType.SIDE_MISMATCH,
                message=f"Side '{side}' != mandated '{m.side}'",
                is_critical=True,
                tool_name=tool_name,
                param_key="side",
                expected=m.side,
                actual=side,
            ))

        # ── Price checks ─────────────────────────────────────────
        price = self._extract_price(params)
        if price is not None:
            if price <= 0:
                violations.append(GuardViolation(
                    violation_type=ViolationType.HALLUCINATED_PRICE,
                    message=f"Hallucinated price: ${price}",
                    is_critical=True,
                    tool_name=tool_name,
                    param_key="price",
                    expected="> 0",
                    actual=price,
                ))
            elif m.limit_price and m.limit_price > 0:
                band = m.limit_price * (m.price_band_pct / 100.0)
                low = m.limit_price - band
                high = m.limit_price + band
                if not (low <= price <= high):
                    violations.append(GuardViolation(
                        violation_type=ViolationType.PRICE_OUT_OF_BAND,
                        message=(
                            f"Price ${price:.4f} outside band "
                            f"[${low:.4f}, ${high:.4f}]"
                        ),
                        is_critical=False,
                        tool_name=tool_name,
                        param_key="price",
                        expected=f"[{low:.4f}, {high:.4f}]",
                        actual=price,
                    ))

        # ── Quantity check ───────────────────────────────────────
        qty = self._extract_quantity(params)
        if qty is not None and m.max_quantity > 0:
            if qty > m.max_quantity:
                deviation = (qty - m.max_quantity) / m.max_quantity
                if deviation <= 0.05:
                    # Auto-correct small overages (≤5%)
                    corrected_qty = m.max_quantity
                    qty_key = self._find_param_key(params, ("qty", "quantity", "size", "amount"))
                    if qty_key:
                        corrected[qty_key] = corrected_qty
                    violations.append(GuardViolation(
                        violation_type=ViolationType.QUANTITY_EXCEEDED,
                        message=f"Quantity {qty} auto-corrected to {corrected_qty}",
                        is_critical=False,
                        tool_name=tool_name,
                        param_key="quantity",
                        expected=m.max_quantity,
                        actual=qty,
                        corrected_to=corrected_qty,
                    ))
                else:
                    violations.append(GuardViolation(
                        violation_type=ViolationType.QUANTITY_EXCEEDED,
                        message=f"Quantity {qty} exceeds max {m.max_quantity} by {deviation:.1%}",
                        is_critical=True,
                        tool_name=tool_name,
                        param_key="quantity",
                        expected=m.max_quantity,
                        actual=qty,
                    ))

        # ── Value check (qty × price) ────────────────────────────
        effective_price = price if price and price > 0 else (m.limit_price or 0)
        effective_qty = qty if qty else 0
        if effective_price > 0 and effective_qty > 0:
            order_value = effective_price * effective_qty
            if order_value > m.max_value_usd:
                violations.append(GuardViolation(
                    violation_type=ViolationType.MAX_VALUE_EXCEEDED,
                    message=f"Order value ${order_value:.2f} > max ${m.max_value_usd:.2f}",
                    is_critical=True,
                    tool_name=tool_name,
                    param_key="value",
                    expected=m.max_value_usd,
                    actual=order_value,
                ))

        # ── Cash sufficiency (for buys) ──────────────────────────
        if m.side == "buy" and effective_price > 0 and effective_qty > 0:
            order_value = effective_price * effective_qty
            if order_value > m.available_cash_usd:
                violations.append(GuardViolation(
                    violation_type=ViolationType.INSUFFICIENT_CASH,
                    message=(
                        f"Order value ${order_value:.2f} > "
                        f"available cash ${m.available_cash_usd:.2f}"
                    ),
                    is_critical=True,
                    tool_name=tool_name,
                    param_key="cash",
                    expected=m.available_cash_usd,
                    actual=order_value,
                ))

        # ── Daily trade limit ────────────────────────────────────
        if m.daily_trades_remaining <= 0:
            violations.append(GuardViolation(
                violation_type=ViolationType.DAILY_TRADE_LIMIT,
                message="Daily trade limit exhausted",
                is_critical=True,
                tool_name=tool_name,
                expected="> 0 remaining",
                actual=m.daily_trades_remaining,
            ))

        # ── Daily volume limit ───────────────────────────────────
        if effective_price > 0 and effective_qty > 0:
            order_value = effective_price * effective_qty
            if order_value > m.daily_volume_remaining_usd:
                violations.append(GuardViolation(
                    violation_type=ViolationType.DAILY_VOLUME_LIMIT,
                    message=(
                        f"Order ${order_value:.2f} would exceed daily volume "
                        f"remaining ${m.daily_volume_remaining_usd:.2f}"
                    ),
                    is_critical=True,
                    tool_name=tool_name,
                    expected=m.daily_volume_remaining_usd,
                    actual=order_value,
                ))

        # ── Verdict ──────────────────────────────────────────────
        self._violations.extend(violations)
        has_critical = any(v.is_critical for v in violations)

        has_corrections = corrected != params
        return GuardResult(
            allowed=not has_critical,
            violations=violations,
            corrected_params=corrected if has_corrections else None,
        )

    def _validate_companion(
        self,
        tool_name: str,
        params: dict[str, Any],
        violations: list[GuardViolation],
        corrected: dict[str, Any],
    ) -> GuardResult:
        """Validate stop-loss / take-profit companion orders."""
        m = self.mandate

        # Symbol must match
        symbol = self._extract_symbol(params)
        if symbol and symbol.upper() != m.symbol.upper():
            violations.append(GuardViolation(
                violation_type=ViolationType.INVALID_COMPANION_ORDER,
                message=f"Companion order symbol '{symbol}' != mandated '{m.symbol}'",
                is_critical=True,
                tool_name=tool_name,
                expected=m.symbol,
                actual=symbol,
            ))

        # Stop-loss price sanity
        stop_price = self._extract_param(params, ("stop_price", "stop_loss", "stop"))
        if stop_price is not None:
            if stop_price <= 0:
                violations.append(GuardViolation(
                    violation_type=ViolationType.HALLUCINATED_PRICE,
                    message=f"Stop-loss price ${stop_price} is invalid",
                    is_critical=True,
                    tool_name=tool_name,
                    param_key="stop_price",
                    actual=stop_price,
                ))
            elif m.stop_loss and abs(stop_price - m.stop_loss) / m.stop_loss > 0.10:
                violations.append(GuardViolation(
                    violation_type=ViolationType.INVALID_COMPANION_ORDER,
                    message=(
                        f"Stop-loss ${stop_price:.4f} deviates >10% from "
                        f"mandated ${m.stop_loss:.4f}"
                    ),
                    is_critical=False,
                    tool_name=tool_name,
                    param_key="stop_price",
                    expected=m.stop_loss,
                    actual=stop_price,
                ))

        self._violations.extend(violations)
        has_critical = any(v.is_critical for v in violations)
        return GuardResult(
            allowed=not has_critical,
            violations=violations,
            corrected_params=corrected if corrected != params else None,
        )

    # ── param extraction helpers ─────────────────────────────────

    @staticmethod
    def _extract_param(
        params: dict[str, Any],
        keys: tuple[str, ...],
    ) -> Any | None:
        """Try multiple key names to find a param value."""
        for k in keys:
            if k in params:
                return params[k]
        return None

    def _extract_symbol(self, params: dict[str, Any]) -> str | None:
        val = self._extract_param(params, ("symbol", "ticker", "asset", "pair"))
        return str(val) if val is not None else None

    def _extract_side(self, params: dict[str, Any]) -> str | None:
        val = self._extract_param(params, ("side", "action", "direction", "order_side"))
        return str(val).lower() if val is not None else None

    def _extract_price(self, params: dict[str, Any]) -> float | None:
        val = self._extract_param(
            params, ("price", "limit_price", "limit", "entry_price")
        )
        return float(val) if val is not None else None

    def _extract_quantity(self, params: dict[str, Any]) -> float | None:
        val = self._extract_param(
            params, ("qty", "quantity", "size", "amount", "shares", "notional")
        )
        return float(val) if val is not None else None

    @staticmethod
    def _find_param_key(
        params: dict[str, Any],
        candidates: tuple[str, ...],
    ) -> str | None:
        for k in candidates:
            if k in params:
                return k
        return None


# =============================================================================
# SAFE TOOL WRAPPER — Layer 3
# =============================================================================

class SafeToolWrapper(AbstractTool):
    """Wraps an AbstractTool, intercepting execute() for guard validation.

    Inherits from AbstractTool so ToolManager treats it as a first-class tool.
    Delegates get_schema(), name, description, and args_schema to the wrapped
    tool so the LLM sees the original interface.
    """

    def __init__(
        self,
        wrapped_tool: AbstractTool,
        guard: DeterministicGuard,
    ) -> None:
        # Initialize with the wrapped tool's name and description
        # but skip directory creation by passing output_dir as None
        self._wrapped = wrapped_tool
        self._guard = guard
        # Copy identity from wrapped tool
        self.name = wrapped_tool.name
        self.description = wrapped_tool.description
        self.args_schema = wrapped_tool.args_schema
        self.return_direct = wrapped_tool.return_direct
        # Minimal AbstractTool init — logger only
        self.logger = logging.getLogger(
            f"SafeToolWrapper.{self.name}"
        )
        # Store init kwargs for clone compatibility
        self._init_kwargs = {}

    # ── Schema delegation ────────────────────────────────────────

    def get_schema(self) -> dict[str, Any]:
        """Delegate schema to the wrapped tool (LLM sees original interface)."""
        return self._wrapped.get_schema()

    def validate_args(self, **kwargs) -> Any:
        """Delegate argument validation to the wrapped tool."""
        return self._wrapped.validate_args(**kwargs)

    # ── Core execution with guard interception ───────────────────

    async def execute(self, *args, **kwargs) -> ToolResult:
        """Intercept execution, validate against guard, then delegate."""
        result = self._guard.validate_tool_call(self.name, kwargs)

        if not result.allowed:
            blocked_msg = (
                f"BLOCKED by guard: {result.summary()} | "
                f"tool={self.name} params={kwargs}"
            )
            self.logger.warning(blocked_msg)
            return ToolResult(
                success=False,
                status="blocked_by_guard",
                result=None,
                error=blocked_msg,
                metadata={
                    "tool_name": self.name,
                    "guard_violations": [v.to_dict() for v in result.violations],
                },
            )

        # Use corrected params if the guard auto-corrected
        effective_kwargs = result.corrected_params if result.corrected_params else kwargs

        if result.violations:
            self.logger.info(
                f"Guard warnings for {self.name}: "
                f"{[v.message for v in result.violations]}"
            )

        # Delegate to wrapped tool
        return await self._wrapped.execute(*args, **effective_kwargs)

    async def _execute(self, **kwargs) -> Any:
        """Not used directly — execute() is overridden."""
        return await self._wrapped._execute(**kwargs)


def wrap_tools_with_guards(
    tools: list[AbstractTool],
    guard: DeterministicGuard,
) -> list[SafeToolWrapper]:
    """Wrap a list of tools with the deterministic guard."""
    wrapped = []
    for tool in tools:
        if isinstance(tool, AbstractTool):
            wrapped.append(SafeToolWrapper(wrapped_tool=tool, guard=guard))
        else:
            # Non-AbstractTool entries (e.g. ToolDefinition) pass through
            # They won't be guarded but won't break the pipeline
            logger.warning(
                f"Tool '{getattr(tool, 'name', '?')}' is not an AbstractTool "
                f"— skipping guard wrapping"
            )
    return wrapped


# =============================================================================
# AUDIT LOG
# =============================================================================

@dataclass
class ExecutionAuditEntry:
    """Full audit record for a guarded execution."""
    order_id: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    mandate: dict[str, Any] = field(default_factory=dict)
    violations: list[dict[str, Any]] = field(default_factory=list)
    tool_calls_intercepted: int = 0
    execution_blocked: bool = False
    reconciliation_passed: bool | None = None

    @classmethod
    def from_guard(
        cls,
        guard: DeterministicGuard,
        blocked: bool = False,
        reconciliation_passed: bool | None = None,
    ) -> ExecutionAuditEntry:
        """Build audit entry from a completed guard session."""
        m = guard.mandate
        return cls(
            order_id=m.order_id,
            mandate={
                "symbol": m.symbol,
                "side": m.side,
                "max_quantity": m.max_quantity,
                "max_value_usd": m.max_value_usd,
                "limit_price": m.limit_price,
            },
            violations=[v.to_dict() for v in guard.violations],
            tool_calls_intercepted=guard._order_calls,
            execution_blocked=blocked,
            reconciliation_passed=reconciliation_passed,
        )
