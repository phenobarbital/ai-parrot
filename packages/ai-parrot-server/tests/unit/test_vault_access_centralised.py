"""AC5: only vault storage plumbing may name the user credentials collection."""

from pathlib import Path


REPO = Path(__file__).resolve().parents[4]
ALLOWED = {
    "packages/ai-parrot/src/parrot/security/vault_utils.py",
    "packages/ai-parrot/src/parrot/security/vault_store_redis.py",
    "packages/ai-parrot/src/parrot/security/__init__.py",
    "packages/ai-parrot/src/parrot/handlers/vault_utils.py",
    "packages/ai-parrot/src/parrot/vault_targets.py",
    "packages/ai-parrot/src/parrot/userstore/collections.py",
    "packages/ai-parrot/src/parrot/userstore/settings.py",
    "packages/ai-parrot/src/parrot/userstore/copy.py",
    "packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_store.py",
    "packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_targets.py",
    "packages/ai-parrot-server/src/parrot/handlers/studio/storage/secrets_copy.py",
    "packages/ai-parrot-server/src/parrot/handlers/credentials.py",
}
NEEDLES = ('"user_credentials"', "VAULT_CRED_COLLECTION")


def test_user_credentials_access_is_centralised() -> None:
    """Reject collection access outside the reviewed vault modules."""
    offenders = []
    for path in REPO.glob("packages/*/src/**/*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        relative = str(path.relative_to(REPO))
        if any(needle in text for needle in NEEDLES) and relative not in ALLOWED:
            offenders.append(relative)
    assert offenders == []


def test_handlers_do_not_import_documentdb() -> None:
    """Keep request-path handlers independent of DocumentDB."""
    for relative in (
        "packages/ai-parrot-server/src/parrot/handlers/credentials.py",
        "packages/ai-parrot-server/src/parrot/handlers/agent.py",
    ):
        assert "DocumentDb" not in (REPO / relative).read_text(encoding="utf-8")
