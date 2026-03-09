import os
from unittest.mock import patch


PG_ENV = {
    "PG_HOST": "db.example.com",
    "PG_PORT": "5433",
    "PG_DATABASE": "mydb",
    "PG_USER": "admin",
    "PG_PWD": "secret",
}

BQ_ENV = {
    "BIGQUERY_CREDENTIALS": "/tmp/sa.json",
    "BIGQUERY_PROJECT_ID": "my-project",
}


def _get_pg_creds():
    """Helper: call _get_default_credentials as unbound method."""
    from parrot.tools.database.abstract import AbstractSchemaManagerTool

    class _Stub:
        pass

    return AbstractSchemaManagerTool._get_default_credentials(_Stub(), "postgresql")


def _get_bq_creds():
    """Helper: call _get_default_credentials as unbound method."""
    from parrot.tools.database.abstract import AbstractSchemaManagerTool

    class _Stub:
        pass

    return AbstractSchemaManagerTool._get_default_credentials(_Stub(), "bigquery")


def test_pg_credentials_from_env():
    with patch.dict(os.environ, PG_ENV):
        creds = _get_pg_creds()
    assert creds["host"] == "db.example.com"
    assert creds["port"] == "5433"
    assert creds["database"] == "mydb"
    assert creds["user"] == "admin"
    assert creds["password"] == "secret"


def test_bq_credentials_from_env():
    with patch.dict(os.environ, BQ_ENV):
        creds = _get_bq_creds()
    assert creds["credentials"] == "/tmp/sa.json"
    assert creds["project_id"] == "my-project"
