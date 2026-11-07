"""G1-02 schema application check."""

from __future__ import annotations

from checks._common import apply_schema, execute, g1_check, connect
from harness import CheckResult, SpikeContext


@g1_check("G1-02", "Draft KnowledgeStore schema applies", blocking=True)
async def check_g1_02_schema(ctx: SpikeContext) -> CheckResult:
    """Apply the schema and prove strict, flexible, and relation tables exist."""
    query = "INFO FOR DB; CREATE bundle:test SET repo = 'r', path = 'p', commit = 'c', frontmatter = {extra: true}, updated_at = time::now();"
    async with connect(ctx, "g1", "g1_02") as db:
        await apply_schema(db)
        info, bundle = await execute(db, query)
    tables = info.get("tables", {}) if isinstance(info, dict) else {}
    assert {"bundle", "chunk", "mentions", "related", "synth"}.issubset(tables)
    assert bundle and bundle[0]["frontmatter"]["extra"] is True
    return CheckResult(
        check_id="G1-02",
        title=check_g1_02_schema.title,
        blocking=True,
        status="pass",
        evidence=f"{query} tables={sorted(tables)} bundle={bundle!r}",
    )
