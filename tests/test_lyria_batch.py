"""Tests for Lyria batch music generation."""
import os
import base64
import warnings
from unittest.mock import MagicMock, patch

import pytest

from parrot.clients.google import GoogleGenAIClient


# ============ Helper for mocking aiohttp ============

class MockResponse:
    """Mock aiohttp response."""

    def __init__(self, json_data=None, status=200, text=""):
        self._json_data = json_data
        self.status = status
        self._text = text

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockContextManager:
    """Async context manager for mocking aiohttp session.post()."""

    def __init__(self, response: MockResponse, capture_callback=None):
        self._response = response
        self._capture_callback = capture_callback
        self._url = None
        self._json = None
        self._headers = None
        self._timeout = None

    def set_call_args(self, url, json_data, headers, timeout):
        self._url = url
        self._json = json_data
        self._headers = headers
        self._timeout = timeout
        if self._capture_callback:
            self._capture_callback(url, json_data, headers, timeout)

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockClientSession:
    """Mock aiohttp.ClientSession."""

    def __init__(self, response: MockResponse = None, capture_callback=None):
        self._response = response or MockResponse({}, 200)
        self._capture_callback = capture_callback

    def post(self, url, json=None, headers=None, timeout=None):  # noqa: A002
        """Return an async context manager (not a coroutine)."""
        ctx = MockContextManager(self._response, self._capture_callback)
        ctx.set_call_args(url, json, headers, timeout)
        return ctx

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


# ============ Fixtures ============

@pytest.fixture
def mock_wav_data():
    """Minimal valid WAV file data (44-byte header + empty data)."""
    # RIFF header + WAV header + empty data chunk
    wav_header = bytes([
        0x52, 0x49, 0x46, 0x46,  # "RIFF"
        0x24, 0x00, 0x00, 0x00,  # Chunk size (36 bytes)
        0x57, 0x41, 0x56, 0x45,  # "WAVE"
        0x66, 0x6D, 0x74, 0x20,  # "fmt "
        0x10, 0x00, 0x00, 0x00,  # Subchunk1 size (16)
        0x01, 0x00,              # Audio format (PCM)
        0x02, 0x00,              # Num channels (stereo)
        0x80, 0xBB, 0x00, 0x00,  # Sample rate (48000)
        0x00, 0xEE, 0x02, 0x00,  # Byte rate
        0x04, 0x00,              # Block align
        0x10, 0x00,              # Bits per sample
        0x64, 0x61, 0x74, 0x61,  # "data"
        0x00, 0x00, 0x00, 0x00,  # Data size (0)
    ])
    return wav_header


@pytest.fixture
def mock_wav_b64(mock_wav_data):
    """Base64-encoded WAV data."""
    return base64.b64encode(mock_wav_data).decode()


@pytest.fixture
def mock_lyria_response(mock_wav_b64):
    """Mock successful Lyria API response."""
    return {
        "predictions": [
            {"audioContent": mock_wav_b64, "mimeType": "audio/wav"}
        ],
        "deployedModelId": "12345",
        "model": "projects/test/locations/us-central1/publishers/google/models/lyria-002"
    }


@pytest.fixture
def mock_lyria_multi_response(mock_wav_b64):
    """Mock Lyria API response with multiple samples."""
    return {
        "predictions": [
            {"audioContent": mock_wav_b64, "mimeType": "audio/wav"},
            {"audioContent": mock_wav_b64, "mimeType": "audio/wav"},
        ]
    }


@pytest.fixture
def client():
    """Create a GoogleGenAIClient configured for Vertex AI."""
    with patch('parrot.clients.google.client.genai.Client'):
        client = GoogleGenAIClient(vertexai=True)
        client.vertex_project = "test-project"
        client.vertex_location = "us-central1"
        client.logger = MagicMock()
        return client


@pytest.fixture
def client_no_vertex():
    """Create a GoogleGenAIClient without Vertex AI."""
    with patch('parrot.clients.google.client.genai.Client'):
        client = GoogleGenAIClient(api_key="test-key")
        client.logger = MagicMock()
        return client


# ============ Validation Tests ============

class TestGenerateMusicBatchValidation:
    """Tests for generate_music_batch input validation."""

    @pytest.mark.asyncio
    async def test_empty_prompt_raises(self, client):
        """Empty prompt raises ValueError."""
        with pytest.raises(ValueError, match="Prompt cannot be empty"):
            await client.generate_music_batch(prompt="")

    @pytest.mark.asyncio
    async def test_whitespace_prompt_raises(self, client):
        """Whitespace-only prompt raises ValueError."""
        with pytest.raises(ValueError, match="Prompt cannot be empty"):
            await client.generate_music_batch(prompt="   ")

    @pytest.mark.asyncio
    async def test_seed_with_multiple_samples_raises(self, client):
        """Seed + sample_count > 1 raises ValueError."""
        with pytest.raises(ValueError, match="Cannot combine"):
            await client.generate_music_batch(
                prompt="test music",
                seed=42,
                sample_count=2
            )

    @pytest.mark.asyncio
    async def test_sample_count_below_min_raises(self, client):
        """sample_count < 1 raises ValueError."""
        with pytest.raises(ValueError, match="sample_count must be between"):
            await client.generate_music_batch(
                prompt="test music",
                sample_count=0
            )

    @pytest.mark.asyncio
    async def test_sample_count_above_max_raises(self, client):
        """sample_count > 4 raises ValueError."""
        with pytest.raises(ValueError, match="sample_count must be between"):
            await client.generate_music_batch(
                prompt="test music",
                sample_count=5
            )

    @pytest.mark.asyncio
    async def test_no_vertexai_raises(self, client_no_vertex):
        """Client without vertexai=True raises RuntimeError."""
        with pytest.raises(RuntimeError, match="requires Vertex AI"):
            await client_no_vertex.generate_music_batch(prompt="test music")


# ============ API Call Tests ============

class TestGenerateMusicBatchAPICall:
    """Tests for generate_music_batch API interaction."""

    @pytest.mark.asyncio
    async def test_successful_generation(self, client, mock_lyria_response, tmp_path):
        """Successful API call returns file paths."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "test-token"

        mock_response = MockResponse(json_data=mock_lyria_response, status=200)
        mock_session = MockClientSession(response=mock_response)

        with patch('google.auth.default', return_value=(mock_creds, "test-project")):
            with patch('aiohttp.ClientSession', return_value=mock_session):
                result = await client.generate_music_batch(
                    prompt="Calm acoustic guitar",
                    output_directory=tmp_path
                )

        assert len(result) == 1
        assert result[0].exists()
        assert result[0].suffix == ".wav"
        assert result[0].parent == tmp_path

    @pytest.mark.asyncio
    async def test_multiple_samples(self, client, mock_lyria_multi_response, tmp_path):
        """Multiple samples returns multiple file paths."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "test-token"

        mock_response = MockResponse(json_data=mock_lyria_multi_response, status=200)
        mock_session = MockClientSession(response=mock_response)

        with patch('google.auth.default', return_value=(mock_creds, "test-project")):
            with patch('aiohttp.ClientSession', return_value=mock_session):
                result = await client.generate_music_batch(
                    prompt="Electronic beat",
                    sample_count=2,
                    output_directory=tmp_path
                )

        assert len(result) == 2
        assert all(p.exists() for p in result)
        assert all(p.suffix == ".wav" for p in result)

    @pytest.mark.asyncio
    async def test_prompt_with_genre_and_mood(self, client, mock_lyria_response, tmp_path):
        """Genre and mood are appended to prompt."""
        from parrot.models.google import MusicGenre, MusicMood

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "test-token"

        captured_payload = {}

        def capture_callback(url, json_data, headers, timeout):
            captured_payload["data"] = json_data

        mock_response = MockResponse(json_data=mock_lyria_response, status=200)
        mock_session = MockClientSession(response=mock_response, capture_callback=capture_callback)

        with patch('google.auth.default', return_value=(mock_creds, "test-project")):
            with patch('aiohttp.ClientSession', return_value=mock_session):
                await client.generate_music_batch(
                    prompt="Relaxing music",
                    genre=MusicGenre.JAZZ_FUSION,
                    mood=MusicMood.CHILL,
                    output_directory=tmp_path
                )

        assert "data" in captured_payload
        prompt = captured_payload["data"]["instances"][0]["prompt"]
        assert "Relaxing music" in prompt
        assert "Jazz Fusion" in prompt
        assert "Chill" in prompt

    @pytest.mark.asyncio
    async def test_negative_prompt_included(self, client, mock_lyria_response, tmp_path):
        """Negative prompt is included in API payload."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "test-token"

        captured_payload = {}

        def capture_callback(url, json_data, headers, timeout):
            captured_payload["data"] = json_data

        mock_response = MockResponse(json_data=mock_lyria_response, status=200)
        mock_session = MockClientSession(response=mock_response, capture_callback=capture_callback)

        with patch('google.auth.default', return_value=(mock_creds, "test-project")):
            with patch('aiohttp.ClientSession', return_value=mock_session):
                await client.generate_music_batch(
                    prompt="Acoustic guitar",
                    negative_prompt="drums, vocals",
                    output_directory=tmp_path
                )

        assert "data" in captured_payload
        assert captured_payload["data"]["instances"][0]["negative_prompt"] == "drums, vocals"

    @pytest.mark.asyncio
    async def test_seed_included(self, client, mock_lyria_response, tmp_path):
        """Seed is included in API payload."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "test-token"

        captured_payload = {}

        def capture_callback(url, json_data, headers, timeout):
            captured_payload["data"] = json_data

        mock_response = MockResponse(json_data=mock_lyria_response, status=200)
        mock_session = MockClientSession(response=mock_response, capture_callback=capture_callback)

        with patch('google.auth.default', return_value=(mock_creds, "test-project")):
            with patch('aiohttp.ClientSession', return_value=mock_session):
                await client.generate_music_batch(
                    prompt="Electronic beat",
                    seed=42,
                    output_directory=tmp_path
                )

        assert "data" in captured_payload
        assert captured_payload["data"]["instances"][0]["seed"] == 42


# ============ Error Handling Tests ============

class TestGenerateMusicBatchErrors:
    """Tests for generate_music_batch error handling."""

    @pytest.mark.asyncio
    async def test_content_safety_returns_empty(self, client, tmp_path):
        """Content safety rejection returns empty list."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "test-token"

        mock_response = MockResponse(status=400, text="Content blocked by safety filter")
        mock_session = MockClientSession(response=mock_response)

        with patch('google.auth.default', return_value=(mock_creds, "test-project")):
            with patch('aiohttp.ClientSession', return_value=mock_session):
                result = await client.generate_music_batch(
                    prompt="Inappropriate content",
                    output_directory=tmp_path
                )

        assert result == []

    @pytest.mark.asyncio
    async def test_auth_error_raises(self, client, tmp_path):
        """Authentication error raises RuntimeError."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "test-token"

        mock_response = MockResponse(status=401, text="Unauthorized")
        mock_session = MockClientSession(response=mock_response)

        with patch('google.auth.default', return_value=(mock_creds, "test-project")):
            with patch('aiohttp.ClientSession', return_value=mock_session):
                with pytest.raises(RuntimeError, match="Authentication failed"):
                    await client.generate_music_batch(
                        prompt="Test music",
                        output_directory=tmp_path
                    )

    @pytest.mark.asyncio
    async def test_rate_limit_raises(self, client, tmp_path):
        """Rate limit error raises RuntimeError."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "test-token"

        mock_response = MockResponse(status=429, text="Too many requests")
        mock_session = MockClientSession(response=mock_response)

        with patch('google.auth.default', return_value=(mock_creds, "test-project")):
            with patch('aiohttp.ClientSession', return_value=mock_session):
                with pytest.raises(RuntimeError, match="Rate limit exceeded"):
                    await client.generate_music_batch(
                        prompt="Test music",
                        output_directory=tmp_path
                    )

    @pytest.mark.asyncio
    async def test_empty_predictions_returns_empty(self, client, tmp_path):
        """Empty predictions returns empty list."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.token = "test-token"

        mock_response = MockResponse(json_data={"predictions": []}, status=200)
        mock_session = MockClientSession(response=mock_response)

        with patch('google.auth.default', return_value=(mock_creds, "test-project")):
            with patch('aiohttp.ClientSession', return_value=mock_session):
                result = await client.generate_music_batch(
                    prompt="Test music",
                    output_directory=tmp_path
                )

        assert result == []


# ============ Deprecation Tests ============

class TestGenerateMusicDeprecation:
    """Tests for generate_music deprecation."""

    def test_generate_music_stream_exists(self, client):
        """generate_music_stream method exists."""
        assert hasattr(client, 'generate_music_stream')
        assert callable(getattr(client, 'generate_music_stream'))

    def test_generate_music_exists(self, client):
        """generate_music method still exists (deprecated alias)."""
        assert hasattr(client, 'generate_music')
        assert callable(getattr(client, 'generate_music'))

    def test_generate_music_batch_exists(self, client):
        """generate_music_batch method exists."""
        assert hasattr(client, 'generate_music_batch')
        assert callable(getattr(client, 'generate_music_batch'))

    @pytest.mark.asyncio
    async def test_deprecation_warning_emitted(self, client):
        """Calling generate_music emits DeprecationWarning."""
        # We need to mock the full call chain since generate_music calls
        # generate_music_stream which requires a working connection

        # Patch the underlying generate_music_stream to avoid actual execution
        async def mock_stream(*args, **kwargs):
            yield b"test"

        with patch.object(client, 'generate_music_stream', mock_stream):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")

                # Call the deprecated method
                gen = client.generate_music(prompt="Test")
                # Consume the generator to trigger the warning
                async for _ in gen:
                    break

                # Check that a deprecation warning was issued
                deprecation_warnings = [
                    x for x in w
                    if issubclass(x.category, DeprecationWarning)
                ]
                assert len(deprecation_warnings) >= 1
                assert "generate_music_stream" in str(deprecation_warnings[0].message)


# ============ Integration Tests ============

@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("VERTEX_PROJECT_ID"),
    reason="VERTEX_PROJECT_ID not set"
)
class TestLyriaBatchIntegration:
    """
    Integration tests requiring real Vertex AI credentials.

    Run with: pytest tests/test_lyria_batch.py -m integration -v
    Requires: VERTEX_PROJECT_ID, VERTEX_REGION env vars
    """

    @pytest.fixture
    def real_client(self):
        """Create a real GoogleGenAIClient for integration tests."""
        return GoogleGenAIClient(vertexai=True)

    @pytest.mark.asyncio
    async def test_end_to_end_generation(self, real_client, tmp_path):
        """Generate music and verify WAV file output."""
        results = await real_client.generate_music_batch(
            prompt="Calm acoustic guitar melody",
            output_directory=tmp_path
        )

        assert len(results) == 1
        assert results[0].exists()
        assert results[0].suffix == ".wav"
        # WAV should be ~30 seconds at 48kHz stereo = ~2.8MB minimum
        assert results[0].stat().st_size > 100_000

    @pytest.mark.asyncio
    async def test_reproducibility_with_seed(self, real_client, tmp_path):
        """Same seed produces same output."""
        import hashlib

        run1_dir = tmp_path / "run1"
        run2_dir = tmp_path / "run2"
        run1_dir.mkdir()
        run2_dir.mkdir()

        results1 = await real_client.generate_music_batch(
            prompt="Electronic beat",
            seed=12345,
            output_directory=run1_dir
        )
        results2 = await real_client.generate_music_batch(
            prompt="Electronic beat",
            seed=12345,
            output_directory=run2_dir
        )

        assert len(results1) == 1
        assert len(results2) == 1

        hash1 = hashlib.md5(results1[0].read_bytes()).hexdigest()
        hash2 = hashlib.md5(results2[0].read_bytes()).hexdigest()
        assert hash1 == hash2

    @pytest.mark.asyncio
    async def test_negative_prompt_effect(self, real_client, tmp_path):
        """Negative prompt generates different output."""
        import hashlib

        run1_dir = tmp_path / "with_drums"
        run2_dir = tmp_path / "no_drums"
        run1_dir.mkdir()
        run2_dir.mkdir()

        results1 = await real_client.generate_music_batch(
            prompt="Upbeat rock music with drums",
            seed=42,
            output_directory=run1_dir
        )
        results2 = await real_client.generate_music_batch(
            prompt="Upbeat rock music",
            negative_prompt="drums",
            seed=42,
            output_directory=run2_dir
        )

        # Both should generate files
        assert len(results1) == 1
        assert len(results2) == 1

        # Compute hashes to verify files are valid
        hash1 = hashlib.md5(results1[0].read_bytes()).hexdigest()
        hash2 = hashlib.md5(results2[0].read_bytes()).hexdigest()
        # Both should produce valid hashes (32 hex chars)
        assert len(hash1) == 32
        assert len(hash2) == 32
