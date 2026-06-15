"""Unit tests for FEAT-237: SentenceTransformerModel backend/file_name kwargs.

Tests:
  - `_create_embedding` passes backend kwarg to SentenceTransformer constructor.
  - `_create_embedding` passes file_name via model_kwargs.
  - Default behavior (no backend/file_name) is backward-compatible.

Note on mocking: SentenceTransformer is loaded via lazy_import (importlib), not
as a top-level name in huggingface.py. Therefore we patch the class on the
`sentence_transformers` module directly, which is where `_create_embedding`
looks it up at call time.
"""
import pytest
from unittest.mock import patch, MagicMock


def _make_mock_st_instance() -> MagicMock:
    """Return a mock SentenceTransformer instance with required attributes."""
    instance = MagicMock()
    instance.get_embedding_dimension.return_value = 256
    instance.eval.return_value = None
    return instance


class TestSentenceTransformerBackend:
    @patch("sentence_transformers.SentenceTransformer")
    def test_backend_kwarg_forwarded(self, mock_st_class: MagicMock) -> None:
        """_create_embedding passes backend kwarg to SentenceTransformer."""
        mock_st_class.return_value = _make_mock_st_instance()

        from parrot.embeddings.huggingface import SentenceTransformerModel
        model = SentenceTransformerModel("test/model", backend="onnx")
        model._create_embedding("test/model")

        assert mock_st_class.called
        call_kwargs = mock_st_class.call_args.kwargs
        assert call_kwargs.get("backend") == "onnx", (
            f"Expected backend='onnx' in SentenceTransformer kwargs, got: {call_kwargs}"
        )

    @patch("sentence_transformers.SentenceTransformer")
    def test_openvino_backend_forwarded(self, mock_st_class: MagicMock) -> None:
        """_create_embedding passes openvino backend to SentenceTransformer."""
        mock_st_class.return_value = _make_mock_st_instance()

        from parrot.embeddings.huggingface import SentenceTransformerModel
        model = SentenceTransformerModel("test/model", backend="openvino")
        model._create_embedding("test/model")

        call_kwargs = mock_st_class.call_args.kwargs
        assert call_kwargs.get("backend") == "openvino"

    @patch("sentence_transformers.SentenceTransformer")
    def test_file_name_kwarg_forwarded(self, mock_st_class: MagicMock) -> None:
        """_create_embedding passes file_name via model_kwargs."""
        mock_st_class.return_value = _make_mock_st_instance()

        from parrot.embeddings.huggingface import SentenceTransformerModel
        model = SentenceTransformerModel("test/model", file_name="model_quantized.onnx")
        model._create_embedding("test/model")

        call_kwargs = mock_st_class.call_args.kwargs
        model_kwargs = call_kwargs.get("model_kwargs", {})
        assert model_kwargs.get("file_name") == "model_quantized.onnx", (
            f"Expected model_kwargs['file_name']='model_quantized.onnx', got: {call_kwargs}"
        )

    @patch("sentence_transformers.SentenceTransformer")
    def test_no_backend_default_unchanged(self, mock_st_class: MagicMock) -> None:
        """Without backend, SentenceTransformer is called without backend kwarg."""
        mock_st_class.return_value = _make_mock_st_instance()

        from parrot.embeddings.huggingface import SentenceTransformerModel
        model = SentenceTransformerModel("test/model")
        model._create_embedding("test/model")

        call_kwargs = mock_st_class.call_args.kwargs
        assert "backend" not in call_kwargs, (
            f"backend should not appear in SentenceTransformer kwargs when not set: {call_kwargs}"
        )
        assert "model_kwargs" not in call_kwargs, (
            f"model_kwargs should not appear when file_name not set: {call_kwargs}"
        )

    @patch("sentence_transformers.SentenceTransformer")
    def test_backend_and_file_name_combined(self, mock_st_class: MagicMock) -> None:
        """Backend and file_name can be passed together."""
        mock_st_class.return_value = _make_mock_st_instance()

        from parrot.embeddings.huggingface import SentenceTransformerModel
        model = SentenceTransformerModel(
            "test/model",
            backend="onnx",
            file_name="model_quantized.onnx",
        )
        model._create_embedding("test/model")

        call_kwargs = mock_st_class.call_args.kwargs
        assert call_kwargs.get("backend") == "onnx"
        model_kwargs = call_kwargs.get("model_kwargs", {})
        assert model_kwargs.get("file_name") == "model_quantized.onnx"

    def test_backend_attribute_stored(self) -> None:
        """SentenceTransformerModel stores _backend and _file_name attributes."""
        from parrot.embeddings.huggingface import SentenceTransformerModel
        model = SentenceTransformerModel("test/model", backend="onnx", file_name="q.onnx")
        assert model._backend == "onnx"
        assert model._file_name == "q.onnx"

    def test_no_backend_attributes_none(self) -> None:
        """Without kwargs, _backend and _file_name default to None."""
        from parrot.embeddings.huggingface import SentenceTransformerModel
        model = SentenceTransformerModel("test/model")
        assert model._backend is None
        assert model._file_name is None
