"""Package-wide fixtures for ai-parrot-integrations tests.

Network isolation: no test may open a real DocumentDB connection. asyncdb's
mongo driver can block for minutes on an unreachable host, which hung the full
test sweep (ledger issue:312c1988479b).
"""

import pytest


@pytest.fixture(autouse=True)
def _no_real_documentdb(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``DocumentDb.documentdb_connect`` fail fast with ``ConnectionError``.

    The class attribute is patched, so tests that replace the ``DocumentDb``
    name at its import site keep their own mock. Tests marked ``live_vendor``
    are exempt.

    Args:
        request: The requesting test's fixture request.
        monkeypatch: pytest monkeypatch fixture; undoes the patch after the test.
    """
    if request.node.get_closest_marker("live_vendor"):
        return
    try:
        from parrot.interfaces.documentdb import DocumentDb
    except ImportError:
        return

    async def _refuse_connect(self: DocumentDb) -> None:
        raise ConnectionError("DocumentDB access is disabled in unit tests")

    monkeypatch.setattr(DocumentDb, "documentdb_connect", _refuse_connect)
