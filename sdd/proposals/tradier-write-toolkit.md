+-----------------------------------------------------------------------+
| **◈ PARROT**                                                          |
|                                                                       |
| **TradierWriteToolkit**                                               |
|                                                                       |
| Spec-Driven Implementation Guide for Claude Code                      |
|                                                                       |
| PARROT Framework • Execution Layer • v1.0 • 2026                      |
+-----------------------------------------------------------------------+

**1. Purpose & Scope**

This document is a spec-driven development (SDD) brief intended for
execution by Claude Code. It defines all requirements, architecture
decisions, API contracts, and acceptance criteria needed to implement
TradierWriteToolkit as a first-class execution platform within the
PARROT trading system.

Tradier is selected as the primary Options executor because: (a) the
developer holds an existing Tradier account, (b) its REST API natively
supports multi-leg option orders, (c) it provides an integrated sandbox
environment at https://sandbox.tradier.com, and (d) its option chain
endpoints expose Greeks and expiration data needed by PARROT\'s
deliberation layer.

**2. System Context**

**2.1 PARROT Executor Architecture**

The PARROT execution layer follows a strict separation: write-side
toolkits implement all broker I/O and expose async methods that are
auto-converted into AbstractTool instances via the AbstractToolkit base
class. The ExecutionOrchestrator routes orders to the correct toolkit
using a PLATFORM_ROUTING map keyed by AssetClass.

Current routing table (before this change):

  ----------------------- -----------------------------------------------
  **AssetClass**          **Platform priority list**

  STOCK / ETF             \[ALPACA, IBKR\]

  CRYPTO                  \[BINANCE, BYBIT, KRAKEN\]

  OPTION (new)            \[TRADIER, IBKR\]
  ----------------------- -----------------------------------------------

**2.2 Files to Create / Modify**

  ----------------------------------------------- ------------- ---------------------------
  **File path**                                   **Action**    **Notes**

  parrot/finance/tools/tradier_write.py           CREATE        Main toolkit --- primary
                                                                deliverable

  parrot/finance/schemas.py                       MODIFY        Add Platform.TRADIER,
                                                                AssetClass.OPTION

  parrot/finance/tools/execution_integration.py   MODIFY        Factory + routing for
                                                                Tradier

  parrot/finance/agents/executors.py              MODIFY        create_option_executor()

  parrot/finance/prompts.py                       MODIFY        EXECUTOR_OPTION system
                                                                prompt

  tests/finance/test_tradier_write.py             CREATE        Unit + integration tests

  .env.example                                    MODIFY        Add TRADIER\_\* env vars
  ----------------------------------------------- ------------- ---------------------------

**3. Tradier API Reference**

**3.1 Base URLs**

  ------------------ ----------------------------------------------------
  **Environment**    Base URL

  Sandbox            https://sandbox.tradier.com/v1

  Production         https://api.tradier.com/v1
  ------------------ ----------------------------------------------------

  -----------------------------------------------------------------------
  **⚠ SAFETY DEFAULT** The toolkit MUST default to sandbox mode. Live
  trading requires explicit TRADIER_SANDBOX=false in environment config.

  -----------------------------------------------------------------------

**3.2 Authentication**

Tradier uses Bearer token authentication. All requests include:

> Authorization: Bearer {TRADIER_ACCESS_TOKEN}
>
> Accept: application/json

The toolkit reads TRADIER_ACCESS_TOKEN and TRADIER_ACCOUNT_ID from
navconfig (consistent with AlpacaWriteToolkit\'s config.get() pattern).

**3.3 Endpoints Required**

  ------------ ------------------------------ -------------------------------
  **Method**   **Endpoint**                   **Purpose**

  POST         /accounts/{id}/orders          Place equity / option order

  DELETE       /accounts/{id}/orders/{oid}    Cancel an order

  PUT          /accounts/{id}/orders/{oid}    Modify pending order

  GET          /accounts/{id}/orders          List all orders

  GET          /accounts/{id}/orders/{oid}    Get single order

  GET          /accounts/{id}/positions       Open positions

  GET          /accounts/{id}/balances        Account balances

  GET          /markets/options/chains        Option chain (Greeks)

  GET          /markets/options/expirations   Available expirations

  GET          /markets/quotes                Real-time quote
  ------------ ------------------------------ -------------------------------

**4. TradierWriteToolkit --- Detailed Spec**

**4.1 Class Skeleton**

> \# parrot/finance/tools/tradier_write.py
>
> from \...tools.toolkit import AbstractToolkit
>
> from \...tools.decorators import tool_schema
>
> from \...interfaces.http import HTTPService
>
> class TradierWriteError(RuntimeError): \...
>
> class TradierWriteToolkit(AbstractToolkit):
>
> name: str = \"tradier_write_toolkit\"
>
> description: str = \"Execute equity and option orders on Tradier.\"
>
> SANDBOX_URL = \"https://sandbox.tradier.com/v1\"
>
> LIVE_URL = \"https://api.tradier.com/v1\"

The class must follow the KrakenWriteToolkit pattern for raw HTTP calls
(no third-party Tradier SDK): use HTTPService for all requests, build
auth headers internally, and expose public async methods decorated with
\@tool_schema.

**4.2 Constructor Behaviour**

-   Read TRADIER_ACCESS_TOKEN via config.get(\'TRADIER_ACCESS_TOKEN\')

-   Read TRADIER_ACCOUNT_ID via config.get(\'TRADIER_ACCOUNT_ID\')

-   Read TRADIER_SANDBOX via config.get(\'TRADIER_SANDBOX\',
    fallback=True) --- cast string to bool

-   Set self.base_url = SANDBOX_URL if self.sandbox else LIVE_URL

-   Instantiate self.\_http = HTTPService(\...) with Accept:
    application/json header

-   Log effective mode at INFO level: \'TradierWriteToolkit ready
    (SANDBOX)\' or \'(LIVE)\'

**4.3 Pydantic Input Schemas**

Define one schema per public method, following the AlpacaWriteToolkit
naming convention ({Action}{Target}Input):

  --------------------------- -------------------------------------------
  **Schema class**            Fields (required unless marked optional)

  PlaceEquityOrderInput       symbol, side, qty, order_type, duration,
                              limit_price?, stop_price?

  PlaceOptionOrderInput       class\_=\'option\', symbol, option_symbol,
                              side, qty, order_type, duration,
                              limit_price?, stop_price?

  PlaceMultilegOrderInput     class\_=\'multileg\', symbol, type
                              (e.g.\'debit\'), duration, legs:
                              List\[LegInput\]

  LegInput (nested)           option_symbol, side
                              (\'buy_to_open\'\|\'sell_to_open\'\|...),
                              qty

  CancelOrderInput            order_id: str

  ModifyOrderInput            order_id, type?, duration?, price?, stop?

  GetOrdersInput              includeTags?: bool = False

  GetOptionChainInput         symbol, expiration (YYYY-MM-DD), greeks?:
                              bool = True

  GetExpirationsInput         symbol, includeAllRoots?: bool, strikes?:
                              bool

  GetQuoteInput               symbols: str (comma-separated)
  --------------------------- -------------------------------------------

**4.4 Public Methods (Tools)**

All methods must be async, decorated with
\@tool_schema(\<InputSchema\>), and return Dict\[str, Any\] or
List\[Dict\[str, Any\]\]. Error handling must raise TradierWriteError
with descriptive message.

**place_equity_order**

-   POST /accounts/{id}/orders with class=equity

-   Validate side in (\'buy\',\'sell\'); order_type in
    (\'market\',\'limit\',\'stop\',\'stop_limit\')

-   Validate duration in (\'day\',\'gtc\',\'pre\',\'post\')

-   Return: { order_id, status, symbol, side, qty }

**place_option_order**

-   POST /accounts/{id}/orders with class=option

-   option_symbol must follow OCC format: AAPL230616C00150000

-   Validate side in
    (\'buy_to_open\',\'buy_to_close\',\'sell_to_open\',\'sell_to_close\')

-   Return: { order_id, status, option_symbol, side, qty }

**place_multileg_order**

-   POST /accounts/{id}/orders with class=multileg

-   Support 2-4 legs for spreads, condors, strangles

-   Each leg: option_symbol\[n\], side\[n\], quantity\[n\] --- numbered
    params as per Tradier API

-   Return: { order_id, status, symbol, type, legs_count }

**cancel_order**

-   DELETE /accounts/{id}/orders/{order_id}

-   Return: { cancelled: true, order_id }

**modify_order**

-   PUT /accounts/{id}/orders/{order_id}

-   Only non-None params are sent to avoid overwriting existing values

-   Return: { order_id, status }

**get_orders**

-   GET /accounts/{id}/orders

-   Return list of order dicts from response\[\'orders\'\]\[\'order\'\]
    (handle single-item API quirk)

**get_positions**

-   GET /accounts/{id}/positions

-   Handle \'null\' response when no positions exist --- return \[\]

**get_balances**

-   GET /accounts/{id}/balances

-   Return the balances dict for account summary use by executor

**get_option_chain**

-   GET
    /markets/options/chains?symbol=X&expiration=YYYY-MM-DD&greeks=true

-   Return list of option contracts with bid, ask, Greeks (delta, gamma,
    theta, vega, iv)

-   This is a read helper used by the deliberation layer --- still
    include in write toolkit for executor co-location

**get_expirations**

-   GET /markets/options/expirations?symbol=X

-   Return list of expiration date strings

**get_quote**

-   GET /markets/quotes?symbols=X,Y

-   Return list of quote dicts --- used for price staleness checks
    pre-execution

**5. Schema & Routing Changes**

**5.1 parrot/finance/schemas.py**

Add to Platform enum:

> class Platform(str, Enum):
>
> \...
>
> TRADIER = \"tradier\" \# ← ADD

Add to AssetClass enum:

> class AssetClass(str, Enum):
>
> \...
>
> OPTION = \"option\" \# ← ADD

  -----------------------------------------------------------------------
  **ℹ NOTE** AssetClass.OPTION covers both equity options and ETF
  options. Index options (SPX, VIX) are excluded from v1 scope --- they
  require margin account handling.

  -----------------------------------------------------------------------

**5.2 execution_integration.py**

Add factory function:

> def create_tradier_write_toolkit(\*\*kwargs) -\> TradierWriteToolkit:
>
> return TradierWriteToolkit(\*\*kwargs)

Update PLATFORM_ROUTING:

> PLATFORM_ROUTING = {
>
> AssetClass.STOCK: \[Platform.ALPACA, Platform.IBKR\],
>
> AssetClass.ETF: \[Platform.ALPACA, Platform.IBKR\],
>
> AssetClass.OPTION: \[Platform.TRADIER, Platform.IBKR\], \# ← ADD
>
> AssetClass.CRYPTO: \[Platform.BINANCE, Platform.BYBIT,
> Platform.KRAKEN\],
>
> }

Add OPTION_EXECUTOR_PROFILE (new AgentCapabilityProfile) consistent with
STOCK_EXECUTOR_PROFILE and CRYPTO_EXECUTOR_PROFILE:

> OPTION_EXECUTOR_PROFILE = AgentCapabilityProfile(
>
> agent_id=\"option_executor\",
>
> role=\"option_executor\",
>
> capabilities={READ_MARKET_DATA, READ_PORTFOLIO, PLACE_ORDER_OPTION,
>
> CANCEL_ORDER, MODIFY_ORDER, CLOSE_POSITION},
>
> platforms=\[Platform.TRADIER, Platform.IBKR\],
>
> asset_classes=\[AssetClass.OPTION\],
>
> constraints=ExecutorConstraints(
>
> max_order_value_usd=10_000,
>
> max_daily_trades=20,
>
> max_order_pct=5.0,
>
> allowed_order_types=\[\'limit\',\'debit\',\'credit\'\],
>
> ),
>
> )

**5.3 executors.py**

Add create_option_executor() following the create_stock_executor()
pattern:

-   Agent name: \'Option Executor (Tradier)\'

-   agent_id: \'option_executor\'

-   system_prompt: EXECUTOR_OPTION (new prompt to be added to
    prompts.py)

-   Include in create_all_executors() dict under key \'option\'

**6. EXECUTOR_OPTION System Prompt Spec**

Add EXECUTOR_OPTION to parrot/finance/prompts.py. The prompt must follow
the same structure as EXECUTOR_STOCK and EXECUTOR_CRYPTO (role, mandate,
order_to_execute, portfolio_state, constraints, instructions,
output_format sections).

**Key mandates for the option executor:**

-   Execute ONLY on Tradier (primary) or IBKR (fallback) --- reject
    orders for other platforms

-   Accept only AssetClass.OPTION orders --- reject stocks, ETFs, crypto

-   NEVER use market orders for options --- limit orders only

-   Price staleness check: if bid/ask mid deviates \>5% from memo\'s
    entry price, REJECT with \'stale_option_price\'

-   Verify option symbol follows OCC format before submission

-   For multi-leg orders: validate all legs before submitting any

-   Check time-to-expiry: warn if expiry \< 5 DTE and require
    ConsensusLevel.UNANIMOUS

-   Log both legs and combined net debit/credit in the execution report

**7. Environment Configuration**

**Variables to add to .env.example:**

> \# ── Tradier ──────────────────────────────────────────────────────
>
> TRADIER_ACCESS_TOKEN=your_sandbox_or_live_token_here
>
> TRADIER_ACCOUNT_ID=your_account_id_here
>
> \# Set to false ONLY for live trading --- defaults to sandbox
>
> TRADIER_SANDBOX=true

  -----------------------------------------------------------------------
  **🔴 CRITICAL** TRADIER_SANDBOX must default to True in
  TradierWriteToolkit.\_\_init\_\_(). A misconfiguration here would route
  paper orders to live markets.

  -----------------------------------------------------------------------

**8. Test Specification**

File: tests/finance/test_tradier_write.py

**8.1 Unit Tests (mocked HTTP)**

1.  test_sandbox_default --- assert base_url == SANDBOX_URL when
    TRADIER_SANDBOX not set

2.  test_place_equity_order_buy_limit --- mock POST, assert correct
    payload keys

3.  test_place_equity_order_invalid_side --- assert TradierWriteError
    raised

4.  test_place_option_order_invalid_occ --- assert TradierWriteError on
    bad option_symbol

5.  test_place_multileg_2leg --- assert legs encoded as
    option_symbol\[0\], side\[0\], quantity\[0\], \...

6.  test_cancel_order --- mock DELETE, assert { cancelled: True }

7.  test_get_positions_empty --- mock \'null\' response, assert returns
    \[\]

8.  test_get_orders_single_item --- Tradier returns dict instead of
    list, assert normalized to list

**8.2 Integration Tests (sandbox env)**

Decorated with \@pytest.mark.integration and skipped unless
TRADIER_SANDBOX=true and credentials present:

9.  test_integration_get_balances --- assert response has \'cash\' key

10. test_integration_place_and_cancel --- place limit order far from
    market, immediately cancel, assert status=cancelled

11. test_integration_get_option_chain --- fetch chain for SPY next
    Friday, assert greeks present

**9. Claude Code Implementation Steps**

Claude Code should execute the following steps in order. Each step is
self-contained and testable before proceeding.

**Step 1 --- Schema extensions**

-   Open parrot/finance/schemas.py

-   Add Platform.TRADIER to Platform enum

-   Add AssetClass.OPTION to AssetClass enum

-   Add Capability.PLACE_ORDER_OPTION if Capability enum exists

-   Run: python -c \"from parrot.finance.schemas import Platform,
    AssetClass; print(Platform.TRADIER, AssetClass.OPTION)\"

**Step 2 --- TradierWriteToolkit**

-   Create parrot/finance/tools/tradier_write.py following Section 4

-   Model structure after kraken_write.py (raw HTTP) not alpaca_write.py
    (SDK)

-   Implement all 10 methods from Section 4.4

-   Run: python -c \"from parrot.finance.tools.tradier_write import
    TradierWriteToolkit; t = TradierWriteToolkit(); print(t.base_url)\"

**Step 3 --- execution_integration.py updates**

-   Add create_tradier_write_toolkit() factory

-   Add OPTION_EXECUTOR_PROFILE

-   Update PLATFORM_ROUTING with AssetClass.OPTION

-   Add \'option_executor\' to create_all_executor_toolkits()

-   Run: python -c \"from parrot.finance.tools.execution_integration
    import PLATFORM_ROUTING; from parrot.finance.schemas import
    AssetClass; print(PLATFORM_ROUTING\[AssetClass.OPTION\])\"

**Step 4 --- Executor agent**

-   Add EXECUTOR_OPTION prompt to parrot/finance/prompts.py (see Section
    6 mandates)

-   Add create_option_executor() to parrot/finance/agents/executors.py

-   Add \'option\' key to create_all_executors() return dict

-   Run: python -c \"from parrot.finance.agents.executors import
    create_all_executors; e = create_all_executors();
    print(list(e.keys()))\"

**Step 5 --- Tests**

-   Create tests/finance/test_tradier_write.py following Section 8

-   Run unit tests: pytest tests/finance/test_tradier_write.py -v -m
    \'not integration\'

-   All 8 unit tests must pass before integration tests are attempted

**Step 6 --- Integration validation**

-   Set TRADIER_ACCESS_TOKEN and TRADIER_ACCOUNT_ID in environment

-   Confirm TRADIER_SANDBOX=true

-   Run: pytest tests/finance/test_tradier_write.py -v -m integration

-   Verify get_balances returns valid data, option chain returns Greeks

**10. Acceptance Criteria**

  -----------------------------------------------------------------------
  **✅ DEFINITION OF DONE** All criteria below must be met before the PR
  is considered complete.

  -----------------------------------------------------------------------

  -------- ------------------------------------------------------------------
  **\#**   **Criterion**

  AC-01    TradierWriteToolkit defaults to sandbox mode without any explicit
           config

  AC-02    All 10 methods are registered as AbstractTool instances
           (toolkit.get_tools_sync() returns 10 tools)

  AC-03    Platform.TRADIER and AssetClass.OPTION exist in schemas with no
           import errors

  AC-04    PLATFORM_ROUTING\[AssetClass.OPTION\] returns \[Platform.TRADIER,
           Platform.IBKR\]

  AC-05    create_all_executors() returns a dict containing the \'option\'
           key

  AC-06    All 8 unit tests pass with mocked HTTP (no real API calls)

  AC-07    Integration test test_integration_place_and_cancel completes in
           sandbox without error

  AC-08    Integration test test_integration_get_option_chain returns delta,
           gamma, theta, vega for at least one contract

  AC-09    Existing stock and crypto executor tests continue to pass (no
           regressions)

  AC-10    No bare except clauses --- all errors raise TradierWriteError with
           descriptive message
  -------- ------------------------------------------------------------------

**11. Out of Scope (v1)**

-   Index options (SPX, NDX, VIX) --- require margin account and
    different OCC symbol parsing

-   Futures and forex via Tradier --- not supported by their API

-   Tradier streaming (SSE) --- deferred to a read-side
    TradierReadToolkit in Phase 3

-   Option Greeks calculation --- the toolkit reads Greeks from the
    chain API; it does not compute them

-   Automatic roll logic --- covered by Roll Candidate Scoring (roadmap
    item)

-   IBKR option fallback implementation --- the routing map includes
    IBKR but the IBKRWriteToolkit option methods are a separate task

*PARROT --- Autonomous Trading System • Internal Engineering Document*