"""Unit tests for DatabaseLoader."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from parrot_loaders.database import DatabaseLoader, DEFAULT_EXCLUDE_COLUMNS


# ── Constructor tests ──────────────────────────────────────────────────


class TestDatabaseLoaderInit:
    def test_defaults(self):
        loader = DatabaseLoader(table='plans', schema='att')
        assert loader.table == 'plans'
        assert loader.schema == 'att'
        assert loader.driver == 'pg'
        assert loader.content_format == 'yaml'
        assert loader.where is None
        assert loader.exclude_columns == DEFAULT_EXCLUDE_COLUMNS

    def test_required_table(self):
        with pytest.raises(TypeError):
            DatabaseLoader()

    def test_default_schema(self):
        loader = DatabaseLoader(table='t')
        assert loader.schema == 'public'

    def test_default_exclude_columns(self):
        loader = DatabaseLoader(table='t')
        assert 'created_at' in loader.exclude_columns
        assert 'updated_at' in loader.exclude_columns
        assert 'inserted_at' in loader.exclude_columns

    def test_custom_exclude_columns(self):
        loader = DatabaseLoader(table='t', exclude_columns=['internal_notes'])
        assert 'internal_notes' in loader.exclude_columns
        assert 'created_at' not in loader.exclude_columns

    def test_invalid_content_format(self):
        with pytest.raises(ValueError, match="content_format must be"):
            DatabaseLoader(table='t', content_format='xml')

    def test_custom_driver(self):
        loader = DatabaseLoader(table='t', driver='mysql')
        assert loader.driver == 'mysql'

    def test_custom_dsn(self):
        loader = DatabaseLoader(table='t', dsn='postgres://x:y@host/db')
        assert loader.dsn == 'postgres://x:y@host/db'

    def test_params_dict(self):
        params = {'host': 'localhost', 'port': 5432, 'database': 'mydb'}
        loader = DatabaseLoader(table='t', params=params)
        assert loader.params == params


# ── Query building ─────────────────────────────────────────────────────


class TestBuildQuery:
    def test_basic_query(self):
        loader = DatabaseLoader(table='plans', schema='att')
        assert loader._build_query() == 'SELECT * FROM att.plans'

    def test_with_where(self):
        loader = DatabaseLoader(
            table='plans', schema='att', where="price > 30"
        )
        assert loader._build_query() == "SELECT * FROM att.plans WHERE price > 30"

    def test_default_schema(self):
        loader = DatabaseLoader(table='users')
        assert loader._build_query() == 'SELECT * FROM public.users'


# ── Column filtering ──────────────────────────────────────────────────


class TestFilterColumns:
    def test_removes_default_excludes(self):
        loader = DatabaseLoader(table='t')
        row = {
            'name': 'Test',
            'created_at': '2026-01-01',
            'updated_at': '2026-01-02',
            'inserted_at': '2026-01-03',
            'price': 10,
        }
        filtered = loader._filter_columns(row)
        assert 'name' in filtered
        assert 'price' in filtered
        assert 'created_at' not in filtered
        assert 'updated_at' not in filtered
        assert 'inserted_at' not in filtered

    def test_custom_excludes(self):
        loader = DatabaseLoader(table='t', exclude_columns=['secret'])
        row = {'name': 'Test', 'secret': 'hidden', 'created_at': '2026-01-01'}
        filtered = loader._filter_columns(row)
        assert 'secret' not in filtered
        assert 'created_at' in filtered  # NOT excluded with custom list


# ── YAML serialization ────────────────────────────────────────────────


class TestYamlSerialization:
    def test_scalar_values(self):
        loader = DatabaseLoader(table='t')
        row = {'name': 'Test', 'price': 10.0}
        content = loader._serialize_row(row)
        assert 'name: Test' in content
        assert 'price: 10.0' in content

    def test_list_expanded_as_bullets(self):
        loader = DatabaseLoader(table='t')
        row = {'tags': ['a', 'b', 'c']}
        content = loader._serialize_row(row)
        assert '- a' in content
        assert '- b' in content
        assert '- c' in content

    def test_null_rendered(self):
        loader = DatabaseLoader(table='t')
        row = {'name': 'Test', 'email': None}
        content = loader._serialize_row(row)
        assert 'null' in content

    def test_roundtrip(self):
        loader = DatabaseLoader(table='t')
        row = {'name': 'Unlimited Saver', 'price': 35.0, 'specs': ['5G', 'Talk']}
        content = loader._serialize_row(row)
        parsed = yaml.safe_load(content)
        assert parsed['name'] == 'Unlimited Saver'
        assert parsed['price'] == 35.0
        assert parsed['specs'] == ['5G', 'Talk']


# ── JSON serialization ────────────────────────────────────────────────


class TestJsonSerialization:
    def test_arrays_preserved(self):
        loader = DatabaseLoader(table='t', content_format='json')
        row = {'tags': ['a', 'b']}
        content = loader._serialize_row(row)
        parsed = json.loads(content)
        assert parsed['tags'] == ['a', 'b']

    def test_null_rendered(self):
        loader = DatabaseLoader(table='t', content_format='json')
        row = {'name': 'Test', 'email': None}
        content = loader._serialize_row(row)
        parsed = json.loads(content)
        assert parsed['email'] is None

    def test_roundtrip(self):
        loader = DatabaseLoader(table='t', content_format='json')
        row = {'name': 'Ultra', 'price': 60, 'specs': ['5G+', 'Hotspot']}
        content = loader._serialize_row(row)
        parsed = json.loads(content)
        assert parsed == row


# ── _load() with mocked AsyncDB ───────────────────────────────────────


class TestLoad:
    @pytest.fixture
    def sample_records(self):
        """Simulate asyncpg Record objects as dict-castable items."""
        class FakeRecord(dict):
            pass

        return [
            FakeRecord(
                plan_name='Unlimited Saver',
                price=35.0,
                specifications=['5G access', 'Unlimited talk'],
                created_at='2026-01-01',
            ),
            FakeRecord(
                plan_name='Unlimited Ultra',
                price=60.0,
                specifications=['5G+ access', '50GB hotspot'],
                created_at='2026-01-01',
            ),
        ]

    @pytest.mark.asyncio
    async def test_load_returns_documents(self, sample_records):
        loader = DatabaseLoader(table='plans', schema='att')

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=sample_records)

        mock_db = MagicMock()
        mock_db.connection = AsyncMock(return_value=mock_conn)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with patch('parrot_loaders.database.AsyncDB', return_value=mock_db):
            docs = await loader._load(source='att.plans')

        assert len(docs) == 2
        assert docs[0].page_content  # non-empty
        assert docs[0].metadata['document_meta']['table'] == 'plans'
        assert docs[0].metadata['document_meta']['schema'] == 'att'
        assert docs[0].metadata['document_meta']['row_index'] == 0
        assert docs[0].metadata['document_meta']['driver'] == 'pg'
        assert docs[0].metadata['source'] == 'att.plans'

    @pytest.mark.asyncio
    async def test_load_excludes_columns(self, sample_records):
        loader = DatabaseLoader(table='plans', schema='att')

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=sample_records)

        mock_db = MagicMock()
        mock_db.connection = AsyncMock(return_value=mock_conn)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with patch('parrot_loaders.database.AsyncDB', return_value=mock_db):
            docs = await loader._load(source='att.plans')

        # created_at should NOT be in page_content
        assert 'created_at' not in docs[0].page_content

    @pytest.mark.asyncio
    async def test_load_empty_table(self):
        loader = DatabaseLoader(table='empty_table')

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_db = MagicMock()
        mock_db.connection = AsyncMock(return_value=mock_conn)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with patch('parrot_loaders.database.AsyncDB', return_value=mock_db):
            docs = await loader._load(source='public.empty_table')

        assert docs == []

    @pytest.mark.asyncio
    async def test_load_with_where(self, sample_records):
        loader = DatabaseLoader(
            table='plans', schema='att', where="price > 40"
        )

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=sample_records[1:])

        mock_db = MagicMock()
        mock_db.connection = AsyncMock(return_value=mock_conn)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with patch('parrot_loaders.database.AsyncDB', return_value=mock_db):
            docs = await loader._load(source='att.plans')

        assert len(docs) == 1
        # Verify the query that was called
        mock_conn.fetch.assert_called_once_with(
            "SELECT * FROM att.plans WHERE price > 40"
        )


# ── Registry ──────────────────────────────────────────────────────────


class TestRegistry:
    def test_registered(self):
        from parrot_loaders import LOADER_REGISTRY
        assert 'DatabaseLoader' in LOADER_REGISTRY
        assert LOADER_REGISTRY['DatabaseLoader'] == 'parrot_loaders.database.DatabaseLoader'
