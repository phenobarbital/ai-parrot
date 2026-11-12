"""FEAT-713 M5 — planning."""

from __future__ import annotations

import copy
import json
from datetime import date
from decimal import Decimal

import pytest
import yaml

import sqlglot
from sqlglot import exp

from parrot.semantic.accounting.compiler import (
    canonical_request,
    compile_assertion,
    compile_metric,
    plan_assertion,
    plan_metric,
    render_plan,
    self_check,
)
from parrot.semantic.accounting.errors import AccountingError, PeriodSpansMembershipChange, RequestValidationError
from parrot.semantic.accounting.loader import load_model
from parrot.semantic.accounting.models import (
    AccountingModel,
    AssertionRequest,
    MetricPlan,
    MetricRequest,
    PlanExpr,
    PlanSet,
)

_PLAIN = (dict, list, tuple, str, int, bool, float, Decimal, date, type(None))


def _request(**kwargs) -> MetricRequest:
    period = kwargs.pop("period")
    return MetricRequest.model_validate({**kwargs, "period": period})


def _walk(value: object) -> None:
    assert isinstance(value, _PLAIN), f"non-plain value in plan: {type(value)!r}"
    assert not type(value).__module__.startswith("sqlglot")
    if isinstance(value, dict):
        for key, item in value.items():
            assert isinstance(key, str)
            _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _walk(item)


def _data(path) -> dict:
    return copy.deepcopy(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_plan_is_plain_json(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    request = _request(
        metric="gross_margin",
        grain="month",
        dimensions=("entity",),
        filters={"product_line": ("pokemon", "magic"), "cost_center": "CC100"},
        period={"from": "2025-02-15", "to": "2025-06-30"},
    )
    plan = plan_metric(model, request)
    _walk(plan.model_dump())
    assert MetricPlan.model_validate_json(plan.model_dump_json()) == plan
    assert json.loads(plan.model_dump_json())["schema_version"] == 1
    assert plan_metric(model, request).plan_hash == plan.plan_hash

    assert plan.table == "journal"
    assert plan.cast_decimal is False
    assert plan.scan_from == plan.output_from == date(2025, 2, 15)
    assert plan.to_exclusive == date(2025, 7, 1)
    assert [alias for alias, _ in plan.filters] == ["cost_center", "product_line"]
    assert dict(plan.filters)["product_line"] == ("magic", "pokemon")
    assert [s.alias for s in plan.sets] == ["set_cost_of_sales", "set_product_sales", "set_returns"]
    for plan_set in plan.sets:
        assert list(plan_set.accounts) == sorted(plan_set.accounts)
    used = {a for s in plan.sets for a in s.accounts}
    assert {a for a, _ in plan.natures} == used
    assert plan.columns[0][0] == "m_gross_margin"
    revenue = PlanExpr(
        op="sub", args=(PlanExpr(op="set", alias="set_product_sales"), PlanExpr(op="set", alias="set_returns"))
    )
    assert plan.columns[0][1] == PlanExpr(op="sub", args=(revenue, PlanExpr(op="set", alias="set_cost_of_sales")))

    key_request = json.dumps(request.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":"))
    assert canonical_request(request) == key_request

    ytd = plan_metric(
        model,
        _request(
            metric="revenue", grain="month", period={"from": "2025-05-10", "to": "2025-06-30", "cumulative": "ytd"}
        ),
    )
    assert ytd.scan_from == date(2025, 1, 1)
    assert ytd.output_from == date(2025, 5, 10)
    assert ytd.cumulative == "ytd"
    qtd = plan_metric(
        model,
        _request(metric="revenue", grain="day", period={"from": "2025-05-10", "to": "2025-06-30", "cumulative": "qtd"}),
    )
    assert qtd.scan_from == date(2025, 4, 1)
    mtd = plan_metric(
        model,
        _request(metric="revenue", grain="day", period={"from": "2025-05-10", "to": "2025-05-30", "cumulative": "mtd"}),
    )
    assert mtd.scan_from == date(2025, 5, 1)


def test_refuse_membership_change(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    with pytest.raises(PeriodSpansMembershipChange) as info:
        plan_metric(model, _request(metric="revenue", period={"from": "2024-12-01", "to": "2025-01-31"}))
    assert info.value.boundary == date(2025, 1, 1)
    assert "2024-12-01..2024-12-31" in info.value.suggestion
    assert "2025-01-01..2025-01-31" in info.value.suggestion

    with pytest.raises(PeriodSpansMembershipChange) as info:
        plan_metric(
            model,
            _request(
                metric="revenue", grain="month", period={"from": "2024-12-01", "to": "2025-02-28", "cumulative": "ytd"}
            ),
        )
    assert info.value.boundary == date(2025, 1, 1)

    # Periods ending on / starting at the boundary do not cross it.
    plan_metric(model, _request(metric="revenue", period={"from": "2024-12-01", "to": "2024-12-31"}))
    plan_metric(model, _request(metric="revenue", period={"from": "2025-01-01", "to": "2025-01-31"}))

    # Widened ytd window crossing a mid-year boundary while the period itself does not.
    data = _data(troc_pnl_yaml)
    data["sets"]["d_and_a"]["valid_from"] = "2025-04-01"
    data["sets"]["d_and_a_legacy"]["valid_to"] = "2025-04-01"
    shifted = load_model(data, chart_snapshot)
    period = {"from": "2025-05-01", "to": "2025-05-31"}
    assert plan_metric(shifted, _request(metric="revenue", grain="month", period=period)).scan_from == date(2025, 5, 1)
    with pytest.raises(PeriodSpansMembershipChange) as info:
        plan_metric(shifted, _request(metric="revenue", grain="month", period={**period, "cumulative": "ytd"}))
    assert info.value.boundary == date(2025, 4, 1)
    assert "2025-01-01..2025-03-31" in info.value.suggestion
    assert "2025-04-01..2025-05-31" in info.value.suggestion
    qtd = plan_metric(shifted, _request(metric="revenue", grain="month", period={**period, "cumulative": "qtd"}))
    assert qtd.scan_from == date(2025, 4, 1)


def test_request_validation_errors(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    period = {"from": "2025-02-01", "to": "2025-02-28"}
    with pytest.raises(RequestValidationError):
        plan_metric(model, _request(metric="no_such_metric", period=period))
    with pytest.raises(RequestValidationError):
        plan_metric(model, _request(metric="revenue", dimensions=("region",), period=period))
    with pytest.raises(RequestValidationError):
        plan_metric(model, _request(metric="revenue", filters={"account_id": "4000"}, period=period))
    with pytest.raises(RequestValidationError):
        plan_metric(model, _request(metric="revenue", filters={"entity": ()}, period=period))

    data = _data(troc_pnl_yaml)
    data["metrics"]["revenue"]["dimensions"] = ["entity"]
    data["metrics"]["depreciation"] = {"expr": "sum(d_and_a)"}
    restricted = load_model(data, chart_snapshot)
    with pytest.raises(RequestValidationError):
        plan_metric(restricted, _request(metric="revenue", dimensions=("product_line",), period=period))
    plan_metric(restricted, _request(metric="revenue", dimensions=("entity",), period=period))
    with pytest.raises(RequestValidationError) as info:
        plan_metric(restricted, _request(metric="depreciation", period={"from": "2024-02-01", "to": "2024-02-28"}))
    assert not isinstance(info.value, PeriodSpansMembershipChange)
    plan = plan_metric(restricted, _request(metric="depreciation", period=period))
    assert plan.sets == (PlanSet(alias="set_d_and_a", accounts=("6810", "6820")),)


def test_plan_assertion_index(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    period = {"from": "2025-02-01", "to": "2025-02-28"}
    plan = plan_assertion(model, AssertionRequest.model_validate({"assertion_index": 0, "period": period}))
    assert [name for name, _ in plan.columns] == ["lhs", "rhs"]
    assert plan.columns[0][1] == plan.columns[1][1]
    assert plan.grain is None and plan.dimensions == () and plan.filters == () and plan.cumulative is None
    assert plan.scan_from == plan.output_from == date(2025, 2, 1)
    assert [s.alias for s in plan.sets] == ["set_cost_of_sales", "set_product_sales", "set_returns"]
    with pytest.raises(RequestValidationError):
        plan_assertion(model, AssertionRequest.model_validate({"assertion_index": 1, "period": period}))
    with pytest.raises(PeriodSpansMembershipChange):
        plan_assertion(
            model,
            AssertionRequest.model_validate(
                {"assertion_index": 0, "period": {"from": "2024-12-01", "to": "2025-01-31"}}
            ),
        )


def test_plan_hash_formula_identity(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    period = {"from": "2025-02-01", "to": "2025-02-28"}
    margin = plan_metric(model, _request(metric="gross_margin", grain="month", period=period))
    ratio = plan_metric(model, _request(metric="gross_margin_pct", grain="month", period=period))
    assert margin.sets == ratio.sets
    assert margin.natures == ratio.natures
    assert margin.plan_hash != ratio.plan_hash
    assert (
        plan_metric(model, _request(metric="gross_margin", grain="month", period=period)).plan_hash == margin.plan_hash
    )


# --- Rendering (TASK-5531) ---------------------------------------------------------------------------------------

_DIALECTS = ("duckdb", "postgres", "bigquery")
_JOURNAL_COLUMNS = frozenset({"account_id", "posting_date", "amount", "entity", "product_line", "cost_center"})
_EXACT = "CAST(amount AS DECIMAL(38, 6))"


def _set_sql(sql: str, alias: str, dialect: str = "duckdb") -> str:
    """The rendered expression aliased *alias* in the innermost scan."""
    tree = sqlglot.parse_one(sql, read=dialect)
    for node in tree.find_all(exp.Alias):
        if node.alias == alias and node.find(exp.Sum) is not None and node.find(exp.Window) is None:
            return node.this.sql(dialect=dialect)
    raise AssertionError(f"no aggregate aliased {alias!r}")


def test_compile_deterministic(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    request = _request(
        metric="gross_margin",
        grain="month",
        dimensions=("entity",),
        filters={"product_line": ("pokemon", "magic"), "cost_center": "CC100"},
        period={"from": "2025-02-15", "to": "2025-06-30"},
    )
    for dialect in _DIALECTS:
        compiled = [compile_metric(model, request, dialect) for _ in range(50)]
        assert len({query.sql_hash for query in compiled}) == 1
        assert len({query.sql for query in compiled}) == 1
        first = compiled[0]
        assert first.model_hash == model.model_hash
        assert first.plan_hash == first.plan.plan_hash
        assert first.request == request
        assert first.lineage.metric == "gross_margin" and first.lineage.assertion_index is None
        assert first.lineage.assertions == ("gross_margin == revenue - cogs",)
        for node in sqlglot.parse_one(first.sql, read=dialect).find_all(exp.In):
            values = [item.this for item in node.expressions]
            assert values == sorted(values)

    # Untrusted filter values are rendered as escaped literals, never as SQL.
    hostile = "x' OR 1=1 --"
    query = compile_metric(
        model,
        _request(metric="revenue", filters={"entity": hostile}, period={"from": "2025-02-01", "to": "2025-02-28"}),
        "duckdb",
    )
    literals = [node.this for node in sqlglot.parse_one(query.sql, read="duckdb").find_all(exp.Literal)]
    assert hostile in literals
    assert "OR 1=1" not in query.sql.replace("'x'' OR 1=1 --'", "")

    assertion = compile_assertion(
        model, AssertionRequest.model_validate({"assertion_index": 0, "period": {"from": "2025-01-01", "to": "2025-01-31"}}),
        "postgres",
    )
    assert assertion.lineage.metric is None and assertion.lineage.assertion_index == 0
    assert assertion.lineage.assertions == ("gross_margin == revenue - cogs",)
    assert assertion.lineage.formula == "gross_margin == revenue - cogs"


def _convention_model(troc_pnl_yaml, chart_snapshot, convention: str) -> AccountingModel:
    data = _data(troc_pnl_yaml)
    chart = data["chart_of_accounts"]
    chart["amount_convention"] = convention
    if convention == "debit_credit_columns":
        del chart["amount"]
        chart["debit"] = "debit"
        chart["credit"] = "credit"
    if convention == "natural_balance":
        del chart["nature"]
    return load_model(data, chart_snapshot)


def test_sign_normalisation_per_convention(troc_pnl_yaml, chart_snapshot) -> None:
    exact_debit = "COALESCE(CAST(debit AS DECIMAL(38, 6)), 0)"
    exact_credit = "COALESCE(CAST(credit AS DECIMAL(38, 6)), 0)"
    sales_in = "account_id IN ('4000', '4010', '4020', '4030', '4040', '4050', '4060', '4070', '4080', '4090')"
    expected = {
        "debit_positive": (f"-{_EXACT}", _EXACT),
        "credit_positive": (_EXACT, f"-{_EXACT}"),
        "debit_credit_columns": (f"{exact_credit} - {exact_debit}", f"{exact_debit} - {exact_credit}"),
    }
    period = {"from": "2025-02-01", "to": "2025-02-28"}
    request = _request(metric="revenue", period=period)
    for convention, (sales_amount, returns_amount) in expected.items():
        sql = compile_metric(_convention_model(troc_pnl_yaml, chart_snapshot, convention), request, "duckdb").sql
        assert _set_sql(sql, "set_product_sales") == (
            f"COALESCE(SUM(CASE WHEN {sales_in} THEN CASE WHEN {sales_in} THEN {sales_amount} END END), 0)"
        )
        assert _set_sql(sql, "set_returns") == (
            "COALESCE(SUM(CASE WHEN account_id IN ('4900') THEN CASE WHEN account_id IN ('4900') "
            f"THEN {returns_amount} END END), 0)"
        )
    natural = compile_metric(_convention_model(troc_pnl_yaml, chart_snapshot, "natural_balance"), request, "duckdb")
    assert _set_sql(natural.sql, "set_returns") == f"COALESCE(SUM(CASE WHEN account_id IN ('4900') THEN {_EXACT} END), 0)"

    duckdb = pytest.importorskip("duckdb")
    rows = {
        "debit_positive": [("4000", Decimal("-100.00")), ("4900", Decimal("10.00"))],
        "credit_positive": [("4000", Decimal("100.00")), ("4900", Decimal("-10.00"))],
        "natural_balance": [("4000", Decimal("100.00")), ("4900", Decimal("10.00"))],
    }
    for convention in (*rows, "debit_credit_columns"):
        model = _convention_model(troc_pnl_yaml, chart_snapshot, convention)
        connection = duckdb.connect()
        try:
            if convention == "debit_credit_columns":
                connection.execute(
                    "CREATE TABLE journal (account_id VARCHAR, posting_date DATE, debit DECIMAL(18, 2), "
                    "credit DECIMAL(18, 2))"
                )
                connection.execute(
                    "INSERT INTO journal VALUES ('4000', DATE '2025-02-03', NULL, 100.00), "
                    "('4900', DATE '2025-02-04', 10.00, NULL)"
                )
            else:
                connection.execute("CREATE TABLE journal (account_id VARCHAR, posting_date DATE, amount DECIMAL(18, 2))")
                for account, amount in rows[convention]:
                    connection.execute("INSERT INTO journal VALUES (?, DATE '2025-02-03', ?)", [account, amount])
            result = connection.execute(compile_metric(model, request, "duckdb").sql).fetchall()
        finally:
            connection.close()
        assert result == [(Decimal("100.000000"), Decimal("10.000000"))], convention


def test_cumulative_window_shape(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    request = _request(
        metric="gross_margin_pct",
        grain="month",
        dimensions=("entity",),
        period={"from": "2025-03-15", "to": "2025-06-30", "cumulative": "ytd"},
    )
    query = compile_metric(model, request, "duckdb")
    sql = query.sql
    assert "posting_date >= CAST('2025-01-01' AS DATE) AND posting_date < CAST('2025-07-01' AS DATE)" in sql
    assert "PARTITION BY CAST(DATE_TRUNC('YEAR', bucket) AS DATE), entity ORDER BY bucket" in sql
    assert sql.endswith(
        "WHERE bucket >= CAST(DATE_TRUNC('MONTH', CAST('2025-03-15' AS DATE)) AS DATE) ORDER BY bucket, entity"
    )
    tree = sqlglot.parse_one(sql, read="duckdb")
    assert tree.args["where"] is not None
    assert not any(True for _ in tree.args["where"].find_all(exp.Window))
    windows = list(tree.find_all(exp.Window))
    assert len(windows) == len(query.plan.sets)
    assert all(window.parent_select is not tree for window in windows)
    assert [node.alias_or_name for node in tree.expressions] == ["bucket", "entity"] + [
        plan_set.alias for plan_set in query.plan.sets
    ]
    assert query.plan.columns[0][1].op == "div"

    qtd = compile_metric(
        model, _request(metric="revenue", grain="day", period={"from": "2025-05-10", "to": "2025-05-20", "cumulative": "qtd"}),
        "postgres",
    )
    assert "posting_date >= CAST('2025-04-01' AS DATE)" in qtd.sql
    assert "PARTITION BY CAST(DATE_TRUNC('QUARTER', bucket) AS DATE) ORDER BY bucket" in qtd.sql
    assert "bucket >= CAST(DATE_TRUNC('DAY', CAST('2025-05-10' AS DATE)) AS DATE)" in qtd.sql
    mtd = compile_metric(
        model, _request(metric="revenue", grain="month", period={"from": "2025-05-10", "to": "2025-05-20", "cumulative": "mtd"}),
        "bigquery",
    )
    assert "PARTITION BY CAST(DATE_TRUNC(bucket, MONTH) AS DATE) ORDER BY bucket" in mtd.sql

    plain = compile_metric(model, _request(metric="revenue", grain="month", period={"from": "2025-03-15", "to": "2025-06-30"}), "duckdb")
    assert "OVER" not in plain.sql and "posting_date >= CAST('2025-03-15' AS DATE)" in plain.sql

    with pytest.raises(ValueError):
        _request(metric="revenue", grain="week", period={"from": "2025-05-10", "to": "2025-05-20", "cumulative": "ytd"})
    weekly = query.plan.model_copy(update={"grain": "week"})
    with pytest.raises(RequestValidationError):
        render_plan(weekly, "duckdb")


def test_self_check_rejects_foreign_columns(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    request = _request(
        metric="revenue",
        grain="month",
        dimensions=("entity",),
        period={"from": "2025-03-15", "to": "2025-06-30", "cumulative": "ytd"},
    )
    for dialect in _DIALECTS:
        sql = compile_metric(model, request, dialect).sql
        self_check(sql, dialect, table="journal", columns=_JOURNAL_COLUMNS)

    sql = compile_metric(model, request, "duckdb").sql
    tampered = (
        sql.replace("entity", "salary"),
        sql.replace("FROM journal", "FROM payroll"),
        sql.replace("FROM journal", "FROM read_csv('/etc/passwd')"),
        sql.replace("SELECT bucket, entity,", "SELECT *, bucket, entity,", 1),
        sql.replace("CAST(amount AS", "CAST(secret AS", 1),
        sql.replace("AS set_returns FROM journal", "AS set_returns, secret AS set_secret FROM journal"),
        sql.replace("posting_date >=", "journal.posting_date >=", 1),
        sql + "; DROP TABLE journal",
    )
    for bad in tampered:
        assert bad != sql
        with pytest.raises(AccountingError):
            self_check(bad, "duckdb", table="journal", columns=_JOURNAL_COLUMNS)
    with pytest.raises(AccountingError):
        self_check(sql, "duckdb", table="journal", columns=_JOURNAL_COLUMNS - {"entity"})
    with pytest.raises(AccountingError):
        self_check(sql, "duckdb", table="ledger.journal", columns=_JOURNAL_COLUMNS)
    with pytest.raises(AccountingError):
        compile_metric(model, request, "mysql")

    # Model-supplied identifiers are quoted, so a hostile name stays one identifier and the self-check holds.
    plan = plan_metric(model, request).model_copy(update={"table": 'fin.journal"; DROP TABLE x; --'})
    hostile = render_plan(plan, "postgres")
    assert 'FROM fin."journal""; DROP TABLE x; --"' in hostile


def test_coalesce_and_no_sql_division(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    period = {"from": "2025-08-01", "to": "2025-08-31"}  # the fixture's empty month
    ratio = compile_metric(model, _request(metric="gross_margin_pct", grain="month", period=period), "duckdb")
    for dialect in _DIALECTS:
        sql = compile_metric(model, _request(metric="gross_margin_pct", grain="month", period=period), dialect).sql
        tree = sqlglot.parse_one(sql, read=dialect)
        assert not any(True for _ in tree.find_all(exp.Div))
        assert not any(True for _ in tree.find_all(exp.Nullif))
        assert "/" not in sql and "NULLIF" not in sql.upper()
        for plan_set in ratio.plan.sets:
            aggregate = sqlglot.parse_one(_set_sql(sql, plan_set.alias, dialect), read=dialect)
            assert isinstance(aggregate, exp.Coalesce)
            assert aggregate.expressions[0].this == "0"
            assert isinstance(aggregate.this, exp.Sum)
    assert ratio.plan.columns[0][0] == "m_gross_margin_pct"
    assert ratio.plan.columns[0][1].op == "div"
    assert ratio.lineage.warnings == ("division_by_zero_possible",)
    assert ratio.lineage.formula == "gross_margin / revenue"
    assert [s.name for s in ratio.lineage.sets] == ["cost_of_sales", "product_sales", "returns"]

    margin = compile_metric(model, _request(metric="gross_margin", grain="month", period=period), "duckdb")
    assert margin.sql == ratio.sql and margin.sql_hash == ratio.sql_hash
    assert margin.plan_hash != ratio.plan_hash
    assert margin.lineage.warnings == ()

    data = _data(troc_pnl_yaml)
    data["chart_of_accounts"]["allow_float"] = True
    floaty = compile_metric(load_model(data, chart_snapshot), _request(metric="gross_margin_pct", period=period), "duckdb")
    assert floaty.lineage.warnings == ("division_by_zero_possible", "float_cast")

    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect()
    try:
        connection.execute("CREATE TABLE journal (account_id VARCHAR, posting_date DATE, amount DECIMAL(18, 2))")
        connection.execute("INSERT INTO journal VALUES ('4000', DATE '2025-07-01', -5.00)")
        plain = compile_metric(model, _request(metric="gross_margin_pct", period=period), "duckdb")
        assert connection.execute(plain.sql).fetchall() == [(Decimal("0"), Decimal("0"), Decimal("0"))]
    finally:
        connection.close()


def test_resolved_natures_compile_without_snapshot(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    restored = AccountingModel.model_validate_json(model.model_dump_json())
    assert restored == model
    assert dict(restored.natures)["4000"] == "credit" and dict(restored.natures)["4900"] == "debit"
    request = _request(metric="revenue", grain="month", period={"from": "2025-02-01", "to": "2025-02-28"})
    for dialect in _DIALECTS:
        assert compile_metric(restored, request, dialect).sql_hash == compile_metric(model, request, dialect).sql_hash
    sql = compile_metric(restored, request, "duckdb").sql
    assert f"THEN -{_EXACT} END END), 0) AS set_product_sales" in sql
    assert f"THEN {_EXACT} END END), 0) AS set_returns" in sql
    plan = plan_metric(restored, request)
    assert render_plan(MetricPlan.model_validate_json(plan.model_dump_json()), "duckdb") == sql
