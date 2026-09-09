"""Operator CLI tests (TASK-3051)."""

from __future__ import annotations

import ast
import io
from pathlib import Path
from typing import Any

import pytest

from parrot.knowledge.contracts.evidence import EvidenceArchive
from parrot.knowledge.contracts.models import (
    AnswerRecord,
    AuthorizationOutcome,
    Citation,
)
from parrot_tools.contracts.cli import (
    COMMANDS,
    CONFIRMING_COMMANDS,
    build_parser,
    main,
    run_command,
)
from parrot_tools.contracts.retrieval import ContractRetrieval
from parrot_tools.contracts.service import ContractsAnswerService
from parrot_tools.contracts.verifier import CitationVerifier

from .test_retrieval import FROZEN_NOW, TODAY, FakeCatalog, make_card

CLAUSE = "Vendor shall maintain SOC 2 Type II certification."
CLI_DIR = Path(__file__).resolve().parents[2] / "src" / "parrot_tools" / "contracts"


class RecordingLibrary:
    """Records the library calls the CLI makes."""

    def __init__(self, catalog: FakeCatalog) -> None:
        self.catalog = catalog
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def add_contract(self, source, *, source_uri=None, force=False):
        self.calls.append(("add_contract", {"source": source, "source_uri": source_uri, "force": force}))
        return type(
            "Result",
            (),
            {
                "outcome": "added",
                "card": await self.catalog.get("acme-msa"),
                "reason": "",
                "publication_state": "pending",
            },
        )()

    async def add_folder(self, folder, *, recursive=False, force=False):
        self.calls.append(("add_folder", {"folder": folder, "recursive": recursive, "force": force}))
        return type(
            "Report",
            (),
            {"summary": lambda self: {"added": 1, "updated": 0, "skipped": 0, "errors": 0},
             "items": [], "errors": 0},
        )()

    async def refresh_card(self, contract_id, *, source=None):
        self.calls.append(("refresh_card", {"contract_id": contract_id, "source": source}))
        return type(
            "Result",
            (),
            {"outcome": "updated", "card": await self.catalog.get("acme-msa"), "reason": ""},
        )()

    async def relate_contracts(self, contract_ids=None, *, force=False):
        self.calls.append(("relate_contracts", {"contract_ids": contract_ids, "force": force}))
        return type(
            "Report",
            (),
            {
                "calls": 1,
                "judged": ["acme-msa->zeta-nda=none"],
                "none_outcomes": 1,
                "rejected": [],
                "invalidated": 0,
                "errors": [],
            },
        )()


class RecordingService(ContractsAnswerService):
    """Wraps the real service, recording the administrative calls."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def verify_card(self, contract_id, fields=None, *, request_context, expected_revision=None):
        self._require_owner(request_context, operation="verify_card")
        self.calls.append(
            (
                "verify_card",
                {
                    "contract_id": contract_id,
                    "fields": fields,
                    "user": request_context.user_id,
                    "expected_revision": expected_revision,
                },
            )
        )
        return type(
            "Result",
            (),
            {"verified": ["title"], "corrected": list(fields or {}), "blockers": [], "card_verified": True},
        )()

    async def merge_parties(self, keep_party_id, merge_party_id, *, request_context):
        self._require_owner(request_context, operation="merge_parties")
        self.calls.append(
            ("merge_parties", {"keep": keep_party_id, "merge": merge_party_id, "user": request_context.user_id})
        )
        return type("Result", (), {"model_dump": lambda self, mode=None: {"ok": True}})()


@pytest.fixture()
async def services(tmp_path) -> dict[str, Any]:
    catalog = FakeCatalog()
    card = make_card(stale_fields=["term.expiration_date"])
    await catalog.upsert(card)
    archive = EvidenceArchive(tmp_path / "evidence", tenant_id="troc")
    await archive.archive(
        archive.reference("acme-msa", version_n=1, revision=1, source_sha256="sha-acme-msa"),
        {"0005": f"4. Compliance. {CLAUSE}"},
    )
    service = RecordingService(
        retrieval=ContractRetrieval(catalog=catalog, today=lambda: TODAY),
        verifier=CitationVerifier(catalog=catalog, evidence=archive),
    )
    return {"library": RecordingLibrary(catalog), "service": service}


def parse(*argv: str):
    """Parse a CLI invocation."""
    return build_parser().parse_args(list(argv))


# --------------------------------------------------------------------------
# 1. Dispatch to real services
# --------------------------------------------------------------------------


def test_every_documented_command_exists():
    assert set(COMMANDS) == {
        "add",
        "add-folder",
        "refresh",
        "verify",
        "merge-parties",
        "queue",
        "search",
        "relate",
        "publish",
        "retire-answer",
    }
    parser = build_parser()
    for command in COMMANDS:
        assert parser.parse_args(["--user", "bob", command, *_stub_args(command)])


def _stub_args(command: str) -> list[str]:
    return {
        "add": ["/tmp/a.md"],
        "add-folder": ["/tmp"],
        "refresh": ["acme-msa"],
        "verify": ["acme-msa"],
        "merge-parties": ["keep", "merge"],
        "queue": [],
        "search": ["security"],
        "relate": [],
        "publish": [],
        "retire-answer": ["ans-1", "--reason", "x"],
    }[command]


@pytest.mark.asyncio
async def test_add_and_add_folder_preserve_force(services):
    code, payload = await run_command(
        parse("--user", "bob", "--role", "contract_reader", "add", "/tmp/a.md", "--force"),
        **services,
    )
    assert code == 0 and payload["outcome"] == "added"
    assert services["library"].calls[-1] == (
        "add_contract",
        {"source": "/tmp/a.md", "source_uri": None, "force": True},
    )

    code, payload = await run_command(
        parse("--user", "bob", "add-folder", "/tmp", "--recursive"), **services
    )
    assert code == 0
    assert services["library"].calls[-1][1]["recursive"] is True


@pytest.mark.asyncio
async def test_relate_preserves_force_and_ids(services):
    code, payload = await run_command(
        parse("--user", "bob", "relate", "acme-msa", "--force"), **services
    )
    assert code == 0
    assert payload["calls"] == 1
    assert services["library"].calls[-1] == (
        "relate_contracts",
        {"contract_ids": ["acme-msa"], "force": True},
    )


@pytest.mark.asyncio
async def test_verify_preserves_the_expected_revision_and_corrections(services):
    code, payload = await run_command(
        parse(
            "--user", "bob", "--role", "contract_owner", "--confirm",
            "verify", "acme-msa",
            "--set", "title=ACME MSA",
            "--set", "term.notice_days=60",
            "--set", "governing_law=",
            "--expected-revision", "3",
        ),
        **services,
    )

    assert code == 0
    call = services["service"].calls[-1]
    assert call[0] == "verify_card"
    assert call[1]["fields"] == {
        "title": "ACME MSA",
        "term.notice_days": 60,
        "governing_law": None,
    }
    assert call[1]["expected_revision"] == 3
    assert call[1]["user"] == "bob"
    assert payload["card_verified"] is True


@pytest.mark.asyncio
async def test_queue_and_search_use_the_catalog_behind_the_gate(services):
    code, payload = await run_command(
        parse("--user", "bob", "--role", "contract_reader", "queue"), **services
    )
    assert code == 0
    assert payload["queue"][0]["contract_id"] == "acme-msa"

    code, payload = await run_command(
        parse("--user", "bob", "--role", "contract_reader", "search", "security"), **services
    )
    assert code == 0
    assert payload["results"][0]["contract_id"] == "acme-msa"


# --------------------------------------------------------------------------
# 2. Authorization, confirmation and exit codes
# --------------------------------------------------------------------------


def test_the_confirming_commands_are_the_administrative_ones():
    assert CONFIRMING_COMMANDS == {"verify", "merge-parties", "retire-answer"}


@pytest.mark.asyncio
@pytest.mark.parametrize("command", sorted(CONFIRMING_COMMANDS))
async def test_administrative_commands_refuse_without_confirm(services, command):
    code, payload = await run_command(
        parse("--user", "bob", "--role", "contract_owner", command, *_stub_args(command)),
        **services,
    )
    assert code == 2
    assert "--confirm" in payload["error"]
    assert services["service"].calls == [], "nothing ran"


@pytest.mark.asyncio
async def test_an_unauthorized_operator_exits_nonzero(services):
    code, payload = await run_command(
        parse("--user", "mallory", "--role", "contract_reader", "--confirm",
              "verify", "acme-msa"),
        **services,
    )
    assert code == 3
    assert "denied" in payload["error"]


@pytest.mark.asyncio
async def test_a_read_command_is_denied_without_a_read_role(services):
    code, payload = await run_command(parse("--user", "bob", "queue"), **services)
    assert code == 3
    assert "denied" in payload["error"]


@pytest.mark.asyncio
async def test_confirmation_cannot_be_forged_through_an_argument(services):
    """``--confirm`` is a terminal flag; no command argument sets it."""
    parser = build_parser()
    args = parser.parse_args(
        ["--user", "bob", "--role", "contract_owner", "verify", "acme-msa",
         "--set", "confirmed=true"]
    )
    assert args.confirm is False

    code, _ = await run_command(args, **services)
    assert code == 2, "a field assignment cannot confirm the action"


@pytest.mark.asyncio
async def test_retire_answer_uses_the_shared_gate(services):
    catalog = services["service"].catalog
    await catalog.record_answer(
        AnswerRecord(
            answer_id="ans-1",
            asked_at=FROZEN_NOW,
            user="bob",
            question="q",
            answer_kind="lookup",
            answer="a",
            citations=[
                Citation(
                    contract_id="acme-msa",
                    node_id="0005",
                    quote=CLAUSE,
                    version_n=1,
                    source_sha256="sha-acme-msa",
                )
            ],
            authorization=AuthorizationOutcome(allowed=True),
        )
    )
    code, payload = await run_command(
        parse("--user", "bob", "--role", "contract_owner", "--confirm",
              "retire-answer", "ans-1", "--reason", "wrong clause"),
        **services,
    )

    assert code == 0
    assert payload["retired_by"] == "bob"
    assert await catalog.retired_citations() == {("acme-msa", "0005")}


@pytest.mark.asyncio
async def test_merge_parties_uses_the_shared_gate(services):
    code, payload = await run_command(
        parse("--user", "bob", "--role", "contract_owner", "--confirm",
              "merge-parties", "party-acme", "party-old"),
        **services,
    )
    assert code == 0 and payload["merged"] == {"ok": True}
    assert services["service"].calls[-1][0] == "merge_parties"


@pytest.mark.asyncio
async def test_a_partial_publication_failure_is_not_success(services):
    class Loader:
        async def publish_all(self):
            return type(
                "Report",
                (),
                {
                    "published": False,
                    "contracts": 1,
                    "errors": ["ontology unavailable"],
                    "missing_nodes": [],
                    "missing_edges": [],
                },
            )()

    class Temporal:
        async def drain(self, ctx):
            return type(
                "Drain",
                (),
                {"published": ["acme-msa"], "recovered": [], "failed": [], "errors": [], "unavailable": False},
            )()

    code, payload = await run_command(
        parse("--user", "bob", "--role", "contract_owner", "publish"),
        **services,
        graph_loader=Loader(),
        temporal=Temporal(),
    )
    assert code == 1, "a failed target is not a success"
    assert payload["ontology"]["errors"] == ["ontology unavailable"]
    assert payload["temporal"]["published"] == ["acme-msa"]


@pytest.mark.asyncio
async def test_publish_reports_a_successful_run(services):
    class Loader:
        async def publish_all(self):
            return type(
                "Report",
                (),
                {"published": True, "contracts": 1, "errors": [], "missing_nodes": [], "missing_edges": []},
            )()

    code, payload = await run_command(
        parse("--user", "bob", "--role", "contract_owner", "publish"),
        **services,
        graph_loader=Loader(),
    )
    assert code == 0 and payload["ontology"]["published"] is True


@pytest.mark.asyncio
async def test_an_invalid_field_assignment_is_an_actionable_error(services):
    code, payload = await run_command(
        parse("--user", "bob", "--role", "contract_owner", "--confirm",
              "verify", "acme-msa", "--set", "=novalue"),
        **services,
    )
    assert code == 2
    assert "missing field path" in payload["error"]


# --------------------------------------------------------------------------
# 3. Entrypoint and regressions
# --------------------------------------------------------------------------


def test_the_entrypoint_requires_a_service_factory():
    stream = io.StringIO()
    code = main(["--user", "bob", "queue"], stream=stream)
    assert code == 2
    assert "service factory" in stream.getvalue()


def test_the_entrypoint_wires_the_factory_and_returns_the_exit_code(services):
    stream = io.StringIO()
    code = main(
        ["--user", "bob", "--role", "contract_reader", "--json", "queue"],
        factory=lambda args: services,
        stream=stream,
    )
    assert code == 0
    assert '"contract_id": "acme-msa"' in stream.getvalue()


def test_the_module_entrypoint_exists():
    assert (CLI_DIR / "__main__.py").is_file()
    source = (CLI_DIR / "__main__.py").read_text()
    assert "from .cli import main" in source


def test_the_cli_imports_no_scheduler_or_transport_and_deletes_nothing():
    for name in ("cli.py", "__main__.py"):
        source = (CLI_DIR / name).read_text()
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not any("scheduler" in item for item in imported), imported
        assert not any(
            item.startswith(("aiohttp", "smtplib", "requests", "parrot.server"))
            for item in imported
        )
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        for forbidden in ("unlink", "rmtree", "send", "send_result"):
            assert forbidden not in called, forbidden
