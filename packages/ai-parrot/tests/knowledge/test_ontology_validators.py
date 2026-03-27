"""Tests for AQL security validator."""
import pytest

from parrot.knowledge.ontology.exceptions import AQLValidationError
from parrot.knowledge.ontology.validators import validate_aql


class TestMutationBlocking:

    @pytest.mark.asyncio
    async def test_blocks_insert(self):
        with pytest.raises(AQLValidationError, match="INSERT"):
            await validate_aql("INSERT { name: 'test' } INTO employees")

    @pytest.mark.asyncio
    async def test_blocks_update(self):
        with pytest.raises(AQLValidationError, match="UPDATE"):
            await validate_aql("UPDATE doc WITH { name: 'x' } IN employees")

    @pytest.mark.asyncio
    async def test_blocks_remove(self):
        with pytest.raises(AQLValidationError, match="REMOVE"):
            await validate_aql("REMOVE { _key: '1' } IN employees")

    @pytest.mark.asyncio
    async def test_blocks_replace(self):
        with pytest.raises(AQLValidationError, match="REPLACE"):
            await validate_aql("REPLACE { _key: '1' } WITH {} IN employees")

    @pytest.mark.asyncio
    async def test_blocks_upsert(self):
        with pytest.raises(AQLValidationError, match="UPSERT"):
            await validate_aql(
                "UPSERT { _key: '1' } INSERT {} UPDATE {} IN employees"
            )

    @pytest.mark.asyncio
    async def test_blocks_case_insensitive(self):
        with pytest.raises(AQLValidationError):
            await validate_aql("insert { name: 'test' } into employees")


class TestSystemCollections:

    @pytest.mark.asyncio
    async def test_blocks_system(self):
        with pytest.raises(AQLValidationError, match="_system"):
            await validate_aql("FOR doc IN _system RETURN doc")

    @pytest.mark.asyncio
    async def test_blocks_graphs(self):
        with pytest.raises(AQLValidationError, match="_graphs"):
            await validate_aql("FOR g IN _graphs RETURN g")

    @pytest.mark.asyncio
    async def test_blocks_modules(self):
        with pytest.raises(AQLValidationError, match="_modules"):
            await validate_aql("FOR m IN _modules RETURN m")


class TestJavaScript:

    @pytest.mark.asyncio
    async def test_blocks_apply(self):
        with pytest.raises(AQLValidationError, match="APPLY"):
            await validate_aql("RETURN APPLY('myFunc', [1, 2])")

    @pytest.mark.asyncio
    async def test_blocks_call(self):
        with pytest.raises(AQLValidationError, match="CALL"):
            await validate_aql("RETURN CALL('myFunc')")

    @pytest.mark.asyncio
    async def test_blocks_v8(self):
        with pytest.raises(AQLValidationError, match="V8"):
            await validate_aql("RETURN V8('code')")


class TestTraversalDepth:

    @pytest.mark.asyncio
    async def test_blocks_excessive_depth(self):
        with pytest.raises(AQLValidationError, match="depth 10"):
            await validate_aql(
                "FOR v IN 1..10 OUTBOUND @start edges RETURN v",
                max_depth=4,
            )

    @pytest.mark.asyncio
    async def test_allows_within_limit(self):
        result = await validate_aql(
            "FOR v IN 1..3 OUTBOUND @start edges RETURN v",
            max_depth=4,
        )
        assert "OUTBOUND" in result

    @pytest.mark.asyncio
    async def test_exact_limit_passes(self):
        result = await validate_aql(
            "FOR v IN 1..4 OUTBOUND @start edges RETURN v",
            max_depth=4,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_one_over_limit_fails(self):
        with pytest.raises(AQLValidationError, match="depth 5"):
            await validate_aql(
                "FOR v IN 1..5 OUTBOUND @start edges RETURN v",
                max_depth=4,
            )

    @pytest.mark.asyncio
    async def test_default_depth_used(self):
        """Default max_depth from conf (4) should apply."""
        result = await validate_aql(
            "FOR v IN 1..4 OUTBOUND @start edges RETURN v",
        )
        assert result is not None


class TestValidQueries:

    @pytest.mark.asyncio
    async def test_simple_read(self):
        aql = "FOR doc IN employees RETURN doc"
        result = await validate_aql(aql)
        assert result == aql

    @pytest.mark.asyncio
    async def test_traversal(self):
        aql = "FOR v IN 1..2 OUTBOUND @uid reports_to RETURN v"
        result = await validate_aql(aql)
        assert result == aql

    @pytest.mark.asyncio
    async def test_with_filter(self):
        aql = "FOR doc IN employees FILTER doc.name == @name RETURN doc"
        result = await validate_aql(aql)
        assert result == aql

    @pytest.mark.asyncio
    async def test_with_collect(self):
        aql = "FOR doc IN employees COLLECT dept = doc.dept RETURN dept"
        result = await validate_aql(aql)
        assert result == aql

    @pytest.mark.asyncio
    async def test_multiline(self):
        aql = """
        FOR emp IN employees
            FOR v IN 1..1 OUTBOUND emp._id belongs_to_dept
                RETURN { employee: emp.name, department: v.name }
        """
        result = await validate_aql(aql)
        assert result == aql
