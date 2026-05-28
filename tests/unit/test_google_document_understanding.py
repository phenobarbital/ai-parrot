"""Unit tests for GoogleAnalysis.document_understanding() — TASK-1363 (FEAT-203)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from parrot.models import AIMessage, StructuredOutputConfig
from parrot.models.google import GoogleModel


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_mock_response(text: str = "This is a document summary.") -> SimpleNamespace:
    """Build a minimal Gemini API response mock."""
    usage_metadata = SimpleNamespace(
        prompt_token_count=10,
        candidates_token_count=20,
        total_token_count=30,
    )
    return SimpleNamespace(
        text=text,
        usage_metadata=usage_metadata,
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[SimpleNamespace(text=text)]
                ),
                finish_reason="STOP",
            )
        ],
    )


def _make_file_object(
    state: str = "ACTIVE",
    name: str = "files/test-doc",
    mime_type: str = "application/pdf",
) -> SimpleNamespace:
    """Build a Files API file object mock."""
    return SimpleNamespace(
        name=name,
        state=state,
        uri=f"https://generativelanguage.googleapis.com/v1beta/{name}",
        mime_type=mime_type,
    )


def _build_mock_sdk() -> MagicMock:
    """Build a fully-mocked Google GenAI SDK client."""
    mock_sdk = MagicMock()
    mock_sdk.aio = MagicMock()

    # Files API
    mock_sdk.aio.files = MagicMock()
    mock_sdk.aio.files.upload = AsyncMock(return_value=_make_file_object("ACTIVE"))
    mock_sdk.aio.files.get = AsyncMock(return_value=_make_file_object("ACTIVE"))

    # Models API
    mock_sdk.aio.models = MagicMock()
    mock_sdk.aio.models.generate_content = AsyncMock(
        return_value=_make_mock_response()
    )

    # Chats API
    mock_chat = MagicMock()
    mock_chat.send_message = AsyncMock(return_value=_make_mock_response())
    mock_sdk.aio.chats = MagicMock()
    mock_sdk.aio.chats.create = MagicMock(return_value=mock_chat)

    return mock_sdk


def _make_google_client(mock_sdk: MagicMock) -> Any:
    """Create a GoogleGenAIClient instance with injected mock SDK.

    Uses ``get_client`` patching so the loop-local cache is populated
    normally without the deprecated ``client`` setter.
    """
    from parrot.clients.google.client import GoogleGenAIClient

    client = GoogleGenAIClient.__new__(GoogleGenAIClient)
    # Manually initialize attributes that __init__ would normally set.
    client.__name__ = "GoogleGenAIClient"
    client.model = "gemini-2.5-flash"
    client._lightweight_model = "gemini-3-flash-lite"
    client._fallback_model = None
    client.logger = MagicMock()
    client._tool_manager = MagicMock()
    client._tool_manager.get_tool_schemas.return_value = []
    client._tool_manager.tools = {}
    client._clients_by_loop = {}
    client._locks_by_loop = {}
    try:
        from datamodel.parsers.json import JSONContent
        client._json = JSONContent()
    except ImportError:
        client._json = None

    # Inject mock SDK via the supported factory method.
    client._mock_get_client_patcher = patch.object(
        GoogleGenAIClient, "get_client", new=AsyncMock(return_value=mock_sdk)
    )
    client._mock_get_client_patcher.start()
    return client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_sdk() -> MagicMock:
    """Fully mocked Google GenAI SDK."""
    return _build_mock_sdk()


@pytest.fixture
def google_client(mock_sdk: MagicMock):
    """GoogleGenAIClient with injected mock SDK — tear down patch after test."""
    client = _make_google_client(mock_sdk)
    yield client
    # Stop the get_client patcher after each test.
    client._mock_get_client_patcher.stop()


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Create a minimal PDF file for testing."""
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n")
    return pdf


@pytest.fixture
def sample_txt(tmp_path: Path) -> Path:
    """Create a plain text file for testing."""
    txt = tmp_path / "notes.txt"
    txt.write_text("Plain text document for testing.", encoding="utf-8")
    return txt


@pytest.fixture
def large_file(tmp_path: Path) -> Path:
    """Create a file that exceeds the 50 MB guardrail."""
    large = tmp_path / "large.bin"
    large.write_bytes(b"\x00" * (51 * 1024 * 1024))
    return large


# ---------------------------------------------------------------------------
# TestDocumentUnderstanding
# ---------------------------------------------------------------------------


class TestDocumentUnderstanding:
    """Tests for GoogleAnalysis.document_understanding()."""

    async def test_single_pdf_returns_aimessage(
        self, google_client: Any, sample_pdf: Path
    ) -> None:
        """Single PDF, stateless mode — returns AIMessage with correct provider."""
        result = await google_client.document_understanding(
            prompt="Summarize this document",
            documents=sample_pdf,
        )

        assert isinstance(result, AIMessage)
        assert result.provider == "google_genai"
        assert result.output is not None

    async def test_multiple_files_all_uploaded(
        self,
        google_client: Any,
        mock_sdk: MagicMock,
        sample_pdf: Path,
        sample_txt: Path,
    ) -> None:
        """Multiple documents — each uploaded via the Files API."""
        result = await google_client.document_understanding(
            prompt="Compare these documents",
            documents=[sample_pdf, sample_txt],
        )

        assert isinstance(result, AIMessage)
        # Two uploads expected, one per document
        assert mock_sdk.aio.files.upload.call_count == 2

    async def test_string_path_accepted(
        self, google_client: Any, sample_pdf: Path
    ) -> None:
        """A string path is accepted (not just Path objects)."""
        result = await google_client.document_understanding(
            prompt="What is this?",
            documents=str(sample_pdf),
        )

        assert isinstance(result, AIMessage)

    async def test_file_too_large_raises_value_error(
        self, google_client: Any, large_file: Path
    ) -> None:
        """A file exceeding 50 MB raises ValueError before any upload."""
        with pytest.raises(ValueError, match="50 MB"):
            await google_client.document_understanding(
                prompt="Summarize",
                documents=large_file,
            )

    async def test_file_not_found_raises_error(self, google_client: Any) -> None:
        """A non-existent file path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await google_client.document_understanding(
                prompt="Summarize",
                documents="/nonexistent/path/document.pdf",
            )

    async def test_structured_output_config_populates_ai_message(
        self, google_client: Any, sample_pdf: Path
    ) -> None:
        """StructuredOutputConfig causes structured_output to be set on AIMessage."""

        class Summary(BaseModel):
            title: str
            content: str

        output_config = StructuredOutputConfig(output_type=Summary)
        parsed_summary = Summary(title="Test Doc", content="A brief summary.")

        with (
            patch.object(
                google_client,
                "_parse_structured_output",
                new=AsyncMock(return_value=parsed_summary),
            ),
            patch.object(
                google_client,
                "_apply_structured_output_schema",
                return_value=None,
            ),
        ):
            result = await google_client.document_understanding(
                prompt="Extract summary",
                documents=sample_pdf,
                structured_output=output_config,
            )

        assert isinstance(result, AIMessage)
        assert result.structured_output == parsed_summary

    async def test_structured_output_pydantic_class_auto_wrapped(
        self, google_client: Any, sample_pdf: Path
    ) -> None:
        """A bare Pydantic class is auto-wrapped via _get_structured_config()."""

        class DocInfo(BaseModel):
            topic: str
            pages: int

        parsed_info = DocInfo(topic="Testing", pages=5)

        with (
            patch.object(
                google_client,
                "_parse_structured_output",
                new=AsyncMock(return_value=parsed_info),
            ),
            patch.object(
                google_client,
                "_apply_structured_output_schema",
                return_value=None,
            ),
        ):
            result = await google_client.document_understanding(
                prompt="Extract doc info",
                documents=sample_pdf,
                structured_output=DocInfo,
            )

        assert isinstance(result, AIMessage)
        assert result.structured_output == parsed_info

    async def test_stateful_mode_calls_prepare_context(
        self, google_client: Any, sample_pdf: Path
    ) -> None:
        """Stateful mode invokes _prepare_conversation_context."""
        conversation_history = MagicMock()
        conversation_history.turns = []

        with (
            patch.object(
                google_client,
                "_prepare_conversation_context",
                new=AsyncMock(
                    return_value=(
                        [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                        conversation_history,
                        None,
                    )
                ),
            ) as mock_prepare,
            patch.object(
                google_client,
                "_update_conversation_memory",
                new=AsyncMock(),
            ),
        ):
            result = await google_client.document_understanding(
                prompt="Analyze this document",
                documents=sample_pdf,
                stateless=False,
                user_id="user-1",
                session_id="session-1",
            )

        assert isinstance(result, AIMessage)
        mock_prepare.assert_called_once()

    async def test_default_temperature_is_zero(
        self, google_client: Any, mock_sdk: MagicMock, sample_pdf: Path
    ) -> None:
        """Default temperature is 0.0 for deterministic document analysis."""
        captured_config: list = []

        async def capture_generate(**kwargs):
            captured_config.append(kwargs.get("config"))
            return _make_mock_response()

        mock_sdk.aio.models.generate_content = AsyncMock(side_effect=capture_generate)

        await google_client.document_understanding(
            prompt="Summarize",
            documents=sample_pdf,
        )

        assert len(captured_config) == 1
        assert captured_config[0].temperature == 0.0

    async def test_custom_temperature_respected(
        self, google_client: Any, mock_sdk: MagicMock, sample_pdf: Path
    ) -> None:
        """Explicit temperature override is passed to the model config."""
        captured_config: list = []

        async def capture_generate(**kwargs):
            captured_config.append(kwargs.get("config"))
            return _make_mock_response()

        mock_sdk.aio.models.generate_content = AsyncMock(side_effect=capture_generate)

        await google_client.document_understanding(
            prompt="Summarize",
            documents=sample_pdf,
            temperature=0.7,
        )

        assert captured_config[0].temperature == 0.7

    async def test_returns_provider_google_genai(
        self, google_client: Any, sample_pdf: Path
    ) -> None:
        """AIMessage.provider is always 'google_genai'."""
        result = await google_client.document_understanding(
            prompt="What is this document about?",
            documents=sample_pdf,
        )

        assert result.provider == "google_genai"

    async def test_model_enum_accepted(
        self, google_client: Any, sample_pdf: Path
    ) -> None:
        """GoogleModel enum values are accepted for the model parameter."""
        result = await google_client.document_understanding(
            prompt="Summarize",
            documents=sample_pdf,
            model=GoogleModel.GEMINI_2_5_FLASH,
        )

        assert isinstance(result, AIMessage)


# ---------------------------------------------------------------------------
# TestUploadDocument
# ---------------------------------------------------------------------------


class TestUploadDocument:
    """Tests for GoogleAnalysis._upload_document().

    Each test must call ``await google_client._ensure_client()`` before
    invoking ``_upload_document()`` directly, because the loop-local SDK
    client is only stored after ``_ensure_client()`` runs.
    """

    async def test_upload_returns_part(
        self, google_client: Any, sample_pdf: Path
    ) -> None:
        """_upload_document() returns a types.Part with populated file_data."""
        try:
            from google.genai import types as genai_types  # noqa: F401
        except ImportError:
            pytest.skip("google-genai not installed")

        await google_client._ensure_client()
        part = await google_client._upload_document(sample_pdf)
        assert part is not None
        assert part.file_data is not None
        assert part.file_data.file_uri is not None

    async def test_upload_polls_processing_to_active(
        self, google_client: Any, mock_sdk: MagicMock, sample_pdf: Path
    ) -> None:
        """_upload_document() polls until the file transitions PROCESSING → ACTIVE."""
        processing_file = _make_file_object("PROCESSING", "files/proc-doc")
        active_file = _make_file_object("ACTIVE", "files/proc-doc")

        mock_sdk.aio.files.upload = AsyncMock(return_value=processing_file)
        # First get() still PROCESSING; second get() returns ACTIVE.
        mock_sdk.aio.files.get = AsyncMock(
            side_effect=[processing_file, active_file]
        )

        await google_client._ensure_client()
        with patch("asyncio.sleep", new=AsyncMock()):
            part = await google_client._upload_document(sample_pdf)

        assert part is not None
        assert part.file_data.file_uri == active_file.uri
        assert mock_sdk.aio.files.get.call_count >= 1

    async def test_upload_failed_state_raises_value_error(
        self, google_client: Any, mock_sdk: MagicMock, sample_pdf: Path
    ) -> None:
        """_upload_document() raises ValueError when state becomes FAILED."""
        processing_file = _make_file_object("PROCESSING", "files/fail-doc")
        failed_file = _make_file_object("FAILED", "files/fail-doc")

        mock_sdk.aio.files.upload = AsyncMock(return_value=processing_file)
        mock_sdk.aio.files.get = AsyncMock(return_value=failed_file)

        await google_client._ensure_client()
        with (
            patch("asyncio.sleep", new=AsyncMock()),
            pytest.raises(ValueError, match="FAILED"),
        ):
            await google_client._upload_document(sample_pdf)

    async def test_upload_mime_type_detection_pdf(
        self, google_client: Any, sample_pdf: Path
    ) -> None:
        """_upload_document() correctly propagates the PDF MIME type from the Files API."""
        await google_client._ensure_client()
        part = await google_client._upload_document(sample_pdf)
        # The mock returns 'application/pdf' via _make_file_object
        assert part.file_data.mime_type == "application/pdf"

    async def test_upload_mime_type_detection_txt(
        self, google_client: Any, mock_sdk: MagicMock, sample_txt: Path
    ) -> None:
        """_upload_document() propagates text/plain MIME type from the Files API."""
        txt_file = _make_file_object("ACTIVE", "files/test-txt", "text/plain")
        mock_sdk.aio.files.upload = AsyncMock(return_value=txt_file)

        await google_client._ensure_client()
        part = await google_client._upload_document(sample_txt)
        assert part.file_data.mime_type == "text/plain"

    async def test_upload_active_immediately_skips_polling(
        self, google_client: Any, mock_sdk: MagicMock, sample_pdf: Path
    ) -> None:
        """No polling is needed when the file is immediately ACTIVE after upload."""
        active_file = _make_file_object("ACTIVE")
        mock_sdk.aio.files.upload = AsyncMock(return_value=active_file)

        await google_client._ensure_client()
        with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            part = await google_client._upload_document(sample_pdf)

        mock_sleep.assert_not_called()
        assert part is not None

    async def test_upload_string_path_resolved(
        self, google_client: Any, sample_pdf: Path
    ) -> None:
        """_upload_document() accepts a string path (not only Path objects)."""
        await google_client._ensure_client()
        part = await google_client._upload_document(str(sample_pdf))
        assert part is not None
        assert part.file_data is not None
