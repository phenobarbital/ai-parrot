import pytest
from parrot.bots.data import PandasTable
from parrot.bots.database import QueryDataset, QueryResponse


def test_query_dataset_serialises_pandas_table():
    """Round-trip PandasTable -> QueryDataset -> JSON -> QueryDataset preserves rows/columns/row_count."""
    table = PandasTable(columns=["id", "name"], rows=[[1, "a"], [2, "b"]])
    ds = QueryDataset(
        data=table, columns=["id", "name"], row_count=2, execution_time_ms=12.5
    )
    payload = ds.model_dump_json()
    restored = QueryDataset.model_validate_json(payload)
    assert restored.row_count == 2
    assert restored.columns == ["id", "name"]
    assert restored.data is not None
    assert restored.data.rows == [[1, "a"], [2, "b"]]


def test_query_response_pydantic_schema_includes_explanation_query_data():
    """QueryResponse.model_json_schema() exposes the three required fields."""
    schema = QueryResponse.model_json_schema()
    props = schema["properties"]
    for field in ("explanation", "query", "data", "data_variable", "data_variables"):
        assert field in props, f"missing field {field} in schema"
    assert "explanation" in schema.get("required", [])


def test_query_response_data_variable_path():
    """QueryResponse accepts data=None + data_variable='result_df' without errors."""
    response = QueryResponse(
        explanation="Returned a large result set.",
        query="SELECT * FROM events",
        data=None,
        data_variable="result_df",
    )
    assert response.data is None
    assert response.data_variable == "result_df"
