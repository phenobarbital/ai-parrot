def test_import_pg_tool():
    from parrot.tools.database import PgSchemaSearchTool
    assert PgSchemaSearchTool is not None


def test_import_bq_tool():
    from parrot.tools.database import BQSchemaSearchTool
    assert BQSchemaSearchTool is not None


def test_all_exports():
    import parrot.tools.database as db_pkg
    assert "PgSchemaSearchTool" in db_pkg.__all__
    assert "BQSchemaSearchTool" in db_pkg.__all__
