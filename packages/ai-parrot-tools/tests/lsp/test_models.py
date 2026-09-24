"""Unit tests for FEAT-580 M1 LSP evidence/configuration models.

All tests are pure in-memory Pydantic validation: no file is opened, no
process is started, and no executable is probed anywhere in this module.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot_tools.lsp.models import (
    DiagnosticBatch,
    DiagnosticSnapshot,
    EvidenceMeta,
    LSPConfig,
    LSPDiagnostic,
    LSPFailure,
    LSPLocation,
    LSPResult,
    OPERATOR_UNCONFIGURED_ENVIRONMENT_ID,
    RawDiagnostic,
    SourcePosition,
    SourceRange,
    SourceState,
    WorkspaceSnapshot,
)

VALID_SHA = "a" * 64
OTHER_SHA = "b" * 64


def _range(path: str = "pkg/mod.py") -> SourceRange:
    return SourceRange(path=path, start_line=1, start_column=1, end_line=1, end_column=5)


def _evidence(**overrides: object) -> EvidenceMeta:
    fields: dict[str, object] = dict(
        repo_root=Path("/repo"),
        workspace_id="ws-1",
        generation=0,
        workspace_digest="digest-1",
        environment_id="env-1",
        server_version="1.1.414",
        config_digest="cfg-1",
        observed_at=datetime.now(timezone.utc),
        elapsed_ms=10,
        cold_start=True,
        coverage="selected_files",
    )
    fields.update(overrides)
    return EvidenceMeta(**fields)


class TestLSPConfig:
    def test_valid_round_trip(self):
        config = LSPConfig(repo_root=Path("/repo"), environment_id="env-123")
        assert config.repo_root == Path("/repo")
        assert config.server_command == ["pyright-langserver", "--stdio"]
        assert config.version_command == ["pyright", "--version"]
        assert config.expected_server_version == "1.1.414"
        assert config.startup_timeout_s == 20.0
        assert config.idle_timeout_s == 120.0
        assert config.node_heap_mb == 1024

    def test_operator_unconfigured_sentinel_is_a_plain_valid_string(self):
        config = LSPConfig(repo_root=Path("/repo"), environment_id=OPERATOR_UNCONFIGURED_ENVIRONMENT_ID)
        assert config.environment_id == OPERATOR_UNCONFIGURED_ENVIRONMENT_ID

    def test_repo_root_must_be_absolute(self):
        with pytest.raises(ValidationError):
            LSPConfig(repo_root=Path("relative/path"), environment_id="env-1")

    def test_environment_id_required_and_non_empty(self):
        with pytest.raises(ValidationError):
            LSPConfig(repo_root=Path("/repo"), environment_id="")

    def test_source_roots_must_be_absolute_and_in_root(self):
        with pytest.raises(ValidationError):
            LSPConfig(
                repo_root=Path("/repo"),
                environment_id="env-1",
                source_roots=[Path("relative/src")],
            )
        with pytest.raises(ValidationError):
            LSPConfig(
                repo_root=Path("/repo"),
                environment_id="env-1",
                source_roots=[Path("/other/src")],
            )
        config = LSPConfig(
            repo_root=Path("/repo"),
            environment_id="env-1",
            source_roots=[Path("/repo/src")],
        )
        assert config.source_roots == [Path("/repo/src")]

    def test_empty_argv_rejected(self):
        with pytest.raises(ValidationError):
            LSPConfig(repo_root=Path("/repo"), environment_id="env-1", server_command=[])


class TestModelsRejectExtraFieldsAndInvalidLimits:
    def test_models_reject_extra_fields_and_invalid_limits(self):
        with pytest.raises(ValidationError):
            LSPConfig(repo_root=Path("/repo"), environment_id="env-1", unexpected="nope")
        with pytest.raises(ValidationError):
            SourcePosition(path="a.py", line=1, column=1, expected_sha256=VALID_SHA, extra_field=1)
        with pytest.raises(ValidationError):
            LSPResult(status="ok", operation="lsp_definition", extra_field=1)

        # Configurable caps: the configured maxima from spec §2 are rejected once exceeded.
        with pytest.raises(ValidationError):
            LSPConfig(repo_root=Path("/repo"), environment_id="env-1", startup_timeout_s=61.0)
        with pytest.raises(ValidationError):
            LSPConfig(repo_root=Path("/repo"), environment_id="env-1", request_timeout_s=31.0)
        with pytest.raises(ValidationError):
            LSPConfig(repo_root=Path("/repo"), environment_id="env-1", diagnostics_timeout_s=61.0)
        with pytest.raises(ValidationError):
            LSPConfig(repo_root=Path("/repo"), environment_id="env-1", idle_timeout_s=29.0)
        with pytest.raises(ValidationError):
            LSPConfig(repo_root=Path("/repo"), environment_id="env-1", idle_timeout_s=601.0)
        with pytest.raises(ValidationError):
            LSPConfig(repo_root=Path("/repo"), environment_id="env-1", node_heap_mb=2049)

        # At the maxima, construction succeeds.
        config = LSPConfig(
            repo_root=Path("/repo"),
            environment_id="env-1",
            startup_timeout_s=60.0,
            request_timeout_s=30.0,
            diagnostics_timeout_s=60.0,
            idle_timeout_s=600.0,
            node_heap_mb=2048,
        )
        assert config.node_heap_mb == 2048


class TestSourceHashCoordinateAndRangeValidation:
    def test_source_hash_coordinate_and_range_validation(self):
        # Valid position round trip.
        pos = SourcePosition(path="pkg/mod.py", line=1, column=1, expected_sha256=VALID_SHA)
        assert pos.expected_sha256 == VALID_SHA

        # Hash shape: exactly 64 lowercase hex characters.
        with pytest.raises(ValidationError):
            SourcePosition(path="pkg/mod.py", line=1, column=1, expected_sha256="A" * 64)
        with pytest.raises(ValidationError):
            SourcePosition(path="pkg/mod.py", line=1, column=1, expected_sha256="a" * 63)
        with pytest.raises(ValidationError):
            SourcePosition(path="pkg/mod.py", line=1, column=1, expected_sha256="z" * 64)

        # Coordinates are 1-based; 0 and negative values are rejected.
        with pytest.raises(ValidationError):
            SourcePosition(path="pkg/mod.py", line=0, column=1, expected_sha256=VALID_SHA)
        with pytest.raises(ValidationError):
            SourcePosition(path="pkg/mod.py", line=1, column=-1, expected_sha256=VALID_SHA)

        # Path shape: repository-relative POSIX only.
        with pytest.raises(ValidationError):
            SourcePosition(path="/abs/path.py", line=1, column=1, expected_sha256=VALID_SHA)
        with pytest.raises(ValidationError):
            SourcePosition(path="../escape.py", line=1, column=1, expected_sha256=VALID_SHA)
        with pytest.raises(ValidationError):
            SourcePosition(path="win\\style.py", line=1, column=1, expected_sha256=VALID_SHA)

        # SourceRange: valid round trip, end-exclusive, end must not precede start.
        rng = SourceRange(path="pkg/mod.py", start_line=2, start_column=1, end_line=2, end_column=10)
        assert rng.end_column == 10
        with pytest.raises(ValidationError):
            SourceRange(path="pkg/mod.py", start_line=5, start_column=1, end_line=3, end_column=1)

        # A range collapsed to a single point (end == start) is valid (empty range).
        point = SourceRange(path="pkg/mod.py", start_line=1, start_column=1, end_line=1, end_column=1)
        assert point.start_column == point.end_column

        # SourceState hash/version bounds.
        state = SourceState(path="pkg/mod.py", sha256=VALID_SHA, document_version=1)
        assert state.document_version == 1
        with pytest.raises(ValidationError):
            SourceState(path="pkg/mod.py", sha256=VALID_SHA, document_version=0)

        # LSPLocation carries a validated range + hash, no source body field.
        location = LSPLocation(range=rng, sha256=VALID_SHA)
        assert location.range == rng


class TestUnknownAndEmptySuccessAreDistinct:
    def test_unknown_and_empty_success_are_distinct(self):
        # Empty successful locations: ok status, empty list, no missing paths.
        ok_result = LSPResult(
            status="ok",
            operation="lsp_references",
            evidence=_evidence(),
            locations=[],
            checked_paths=["pkg/mod.py"],
        )
        assert ok_result.status == "ok"
        assert ok_result.locations == []
        assert ok_result.missing_paths == []

        # Unavailable status carries an explicit code, distinct from an empty ok.
        unavailable_result = LSPResult(
            status="unavailable",
            operation="lsp_definition",
            code="invalid_request",
            message="environment_id is unconfigured",
        )
        assert unavailable_result.status == "unavailable"
        assert unavailable_result.code == "invalid_request"
        assert unavailable_result.locations == []

        # code must be one of the fixed operational codes (or None).
        with pytest.raises(ValidationError):
            LSPResult(status="error", operation="lsp_definition", code="not_a_real_code")

        # DiagnosticBatch: a batch with missing/unversioned coverage cannot claim complete=True.
        with pytest.raises(ValidationError):
            DiagnosticBatch(
                diagnostics={},
                matched_versions={},
                missing_paths=["pkg/mod.py"],
                unversioned_paths=[],
                complete=True,
            )
        with pytest.raises(ValidationError):
            DiagnosticBatch(
                diagnostics={},
                matched_versions={},
                missing_paths=[],
                unversioned_paths=["pkg/other.py"],
                complete=True,
            )

        # A genuinely complete, empty-diagnostics batch is a distinct, valid state.
        complete_empty = DiagnosticBatch(
            diagnostics={"pkg/mod.py": []},
            matched_versions={"pkg/mod.py": 1},
            missing_paths=[],
            unversioned_paths=[],
            complete=True,
        )
        assert complete_empty.complete is True
        assert complete_empty.diagnostics["pkg/mod.py"] == []

        # An incomplete batch (missing coverage) must never be conflated with "clean".
        incomplete = DiagnosticBatch(
            diagnostics={},
            matched_versions={},
            missing_paths=["pkg/mod.py"],
            unversioned_paths=[],
            complete=False,
        )
        assert incomplete.complete is False

    def test_lspdiagnostic_severity_default_and_message_cap(self):
        # Missing severity defaults to 3 and marks severity_defaulted=True.
        diagnostic = LSPDiagnostic(range=_range(), message="boom")
        assert diagnostic.severity == 3
        assert diagnostic.severity_defaulted is True

        # An explicitly provided severity is preserved and not marked defaulted.
        explicit = LSPDiagnostic(range=_range(), severity=1, message="boom")
        assert explicit.severity == 1
        assert explicit.severity_defaulted is False

        with pytest.raises(ValidationError):
            LSPDiagnostic(range=_range(), severity=5, message="boom")
        with pytest.raises(ValidationError):
            LSPDiagnostic(range=_range(), message="x" * 1001)

        # RawDiagnostic preserves the complete, uncropped message internally.
        long_message = "x" * 5000
        raw = RawDiagnostic(range=_range(), full_message=long_message)
        assert raw.full_message == long_message
        assert len(raw.full_message) > 1000

    def test_lspfailure_fixed_code_and_bounded_detail(self):
        failure = LSPFailure(code="server_missing", detail="x" * 5000)
        assert failure.code == "server_missing"
        assert len(failure.detail) == 1000

        with pytest.raises(ValueError):
            LSPFailure(code="not_a_real_code")


class TestImportAndConstructionHaveNoIo:
    def test_import_and_construction_have_no_io(self, monkeypatch: pytest.MonkeyPatch):
        """Constructing every model must never touch the filesystem or spawn a process."""

        def _forbidden(*args: object, **kwargs: object) -> None:
            raise AssertionError("model construction must not touch the filesystem/process")

        monkeypatch.setattr("builtins.open", _forbidden)
        monkeypatch.setattr("subprocess.Popen", _forbidden)
        monkeypatch.setattr("asyncio.create_subprocess_exec", _forbidden, raising=False)

        config = LSPConfig(repo_root=Path("/repo"), environment_id="env-1", source_roots=[Path("/repo/src")])
        assert config.repo_root == Path("/repo")

        evidence = _evidence()
        assert evidence.coverage == "selected_files"

        rng = _range()
        location = LSPLocation(range=rng, sha256=VALID_SHA)
        diagnostic = LSPDiagnostic(range=rng, message="hi")
        result = LSPResult(
            status="ok",
            operation="lsp_definition",
            evidence=evidence,
            locations=[location],
            diagnostics=[diagnostic],
        )
        assert result.locations[0] is location

        workspace_snapshot = WorkspaceSnapshot(
            digest="d1",
            file_hashes={"pkg/mod.py": VALID_SHA},
            requested_text={"pkg/mod.py": "print(1)\n"},
            config_digest="cfg-1",
        )
        assert workspace_snapshot.file_hashes["pkg/mod.py"] == VALID_SHA

        snapshot = DiagnosticSnapshot(
            paths=("pkg/a.py", "pkg/b.py"),
            environment_id="env-1",
            config_digest="cfg-1",
            server_version="1.1.414",
            generation=0,
        )
        assert snapshot.paths == ("pkg/a.py", "pkg/b.py")
        assert snapshot.created_at.tzinfo is not None

    def test_diagnostic_snapshot_paths_must_be_sorted_unique(self):
        with pytest.raises(ValidationError):
            DiagnosticSnapshot(
                paths=("pkg/b.py", "pkg/a.py"),
                environment_id="env-1",
                config_digest="cfg-1",
                server_version="1.1.414",
                generation=0,
            )
        with pytest.raises(ValidationError):
            DiagnosticSnapshot(
                paths=("pkg/a.py", "pkg/a.py"),
                environment_id="env-1",
                config_digest="cfg-1",
                server_version="1.1.414",
                generation=0,
            )

    def test_evidence_meta_requires_utc_observed_at(self):
        naive = datetime.now()
        with pytest.raises(ValidationError):
            _evidence(observed_at=naive)

        non_utc = datetime.now(timezone(timedelta(hours=2)))
        with pytest.raises(ValidationError):
            _evidence(observed_at=non_utc)
