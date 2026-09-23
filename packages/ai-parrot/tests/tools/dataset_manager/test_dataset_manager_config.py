import pytest
from pydantic import ValidationError

from parrot.tools.dataset_manager.config import DatasetManagerConfig, FileDatasource


def test_schema_has_nine_kinds():
    schema = DatasetManagerConfig.model_json_schema()
    items = schema["properties"]["datasources"]["items"]
    assert len(items["oneOf"]) == 9
    assert items["discriminator"]["propertyName"] == "kind"


def test_parquet_delta_default():
    f = FileDatasource(kind="file", name="p", path="/x/a.parquet")
    assert f.is_parquet and f.effective_delta_path == "/x/a.delta"


@pytest.mark.parametrize("kw", [{"path": "/x/a.txt"}, {"path": "/x/a.csv", "delta_path": "/y"}])
def test_file_validation(kw):
    with pytest.raises(ValidationError):
        FileDatasource(kind="file", name="p", **kw)


def test_duplicate_names_rejected():
    with pytest.raises(ValidationError):
        DatasetManagerConfig(datasources=[{"kind": "query_slug", "name": "a", "slug": "s"},
                                          {"kind": "query_slug", "name": "a", "slug": "t"}])


def test_secret_markers():
    defs = DatasetManagerConfig.model_json_schema()["$defs"]
    assert defs["SqlDatasource"]["properties"]["dsn"]["x-secret"] is True
