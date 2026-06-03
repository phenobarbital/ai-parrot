"""Integration tests for PostgresEvalSink (TASK-1427).

These tests are gated on DB availability (EVAL_DB_DSN environment variable).
When the DSN is not set the tests are skipped cleanly.
"""
import os
import pytest

from parrot.eval import EvalReportSink, PostgresEvalSink


def _get_dsn() -> str | None:
    """Return the eval DB DSN from the environment."""
    try:
        from navconfig import config  # type: ignore[import]
        return config("EVAL_DB_DSN", default=None)
    except Exception:
        pass
    return os.environ.get("EVAL_DB_DSN")


# ---------------------------------------------------------------------------
# Unit tests (no DB required)
# ---------------------------------------------------------------------------


def test_sink_abc():
    """EvalReportSink is an abstract base."""
    with pytest.raises(TypeError):
        EvalReportSink()  # type: ignore[abstract]


def test_postgres_sink_importable():
    """PostgresEvalSink can be imported and instantiated without a real DSN."""
    sink = PostgresEvalSink(dsn=None)
    assert isinstance(sink, EvalReportSink)


async def test_postgres_sink_raises_without_dsn():
    """PostgresEvalSink.persist raises RuntimeError when no DSN is set."""
    sink = PostgresEvalSink(dsn=None)
    # Patch internal DSN to None
    sink._dsn = None
    with pytest.raises(RuntimeError, match="no DSN"):
        await sink.persist(object())


# ---------------------------------------------------------------------------
# Integration tests (require EVAL_DB_DSN)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_run(maybe_db_dsn):
    """PostgresEvalSink.persist writes eval_runs / eval_results rows."""
    if not maybe_db_dsn:
        pytest.skip("EVAL_DB_DSN not configured — skipping integration test")

    from parrot.eval import (
        EvalDataset,
        EvalReport,
        EvalRunConfig,
        EvalTask,
        Trajectory,
    )
    from parrot.eval.models import EvalResult, MetricScore

    # Build a minimal EvalReport
    tr = Trajectory(task_id="t1", attempt=1, final_output="done")
    result = EvalResult(
        task_id="t1",
        attempt=1,
        scores=[MetricScore(name="state_match", value=1.0, passed=True)],
        passed=True,
        trajectory=tr,
    )
    report = EvalReport(
        dataset_name="integration-test",
        config=EvalRunConfig(k=1),
        results=[result],
        total_tasks=1,
        total_attempts=1,
        pass_k=1.0,
        pass_at_1=1.0,
    )

    sink = PostgresEvalSink(dsn=maybe_db_dsn)
    run_id = await sink.persist(report)

    assert run_id is not None and len(run_id) > 0

    # Verify the data was written
    import asyncpg
    conn = await asyncpg.connect(maybe_db_dsn)
    try:
        row = await conn.fetchrow(
            "SELECT run_id, dataset_name FROM eval_runs WHERE run_id = $1",
            run_id,
        )
        assert row is not None
        assert row["dataset_name"] == "integration-test"

        count = await conn.fetchval(
            "SELECT COUNT(*) FROM eval_results WHERE run_id = $1",
            run_id,
        )
        assert count == 1
    finally:
        # Cleanup
        await conn.execute("DELETE FROM eval_results WHERE run_id = $1", run_id)
        await conn.execute("DELETE FROM eval_runs WHERE run_id = $1", run_id)
        await conn.close()


@pytest.fixture
def maybe_db_dsn():
    """Fixture that provides the eval DB DSN or None."""
    return _get_dsn()
