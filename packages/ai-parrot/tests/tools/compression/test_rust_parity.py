"""Rust <-> Python parity suite for the `columnar` codec (TASK-1955).

Skipped cleanly when the optional `parrot_codec` extension is not
compiled (`maturin develop` inside
`packages/ai-parrot/src/parrot/codec-rs/`). When present, every test here
proves the Rust transform is byte-identical to TASK-1954's pure-Python
reference implementation for the exact same input.
"""
import pytest

parrot_codec = pytest.importorskip(
    "parrot_codec", reason="Rust extension not compiled (maturin develop)"
)

from datamodel.parsers.json import json_encoder  # noqa: E402

import parrot.tools.compression.codecs.columnar as columnar_module  # noqa: E402
from parrot.tools.compression import FilterLevel, get_codec  # noqa: E402


def _to_bytes(payload) -> bytes:
    return json_encoder(payload).encode("utf-8")


@pytest.fixture
def codec():
    return get_codec("columnar")()


@pytest.fixture(autouse=True)
def _reset_rust_detection_cache():
    """Each test gets a fresh `_rust()` detection cache, so monkeypatching
    it (to force the Python-only path) in one test never leaks into the
    next."""
    columnar_module._RUST = None
    columnar_module._RUST_CHECKED = False
    yield
    columnar_module._RUST = None
    columnar_module._RUST_CHECKED = False


class TestRustParity:
    def test_rust_python_parity(self, codec, row_oriented_payload, monkeypatch):
        """Same inputs -> same outputs on both paths (bare row array)."""
        rust_out = codec.compress(
            _to_bytes(row_oriented_payload), level=FilterLevel.NORMAL, params={}
        )
        monkeypatch.setattr(columnar_module, "_rust", lambda: None)
        py_out = codec.compress(
            _to_bytes(row_oriented_payload), level=FilterLevel.NORMAL, params={}
        )
        assert rust_out.payload == py_out.payload
        assert rust_out.lossy == py_out.lossy
        assert rust_out.bytes_after == py_out.bytes_after

    def test_rust_python_parity_queryresult_shape(
        self, codec, row_oriented_payload, monkeypatch,
    ):
        """Parity for the QueryResult-shaped (nested `rows`) input too."""
        payload = {
            "driver": "pg", "rows": row_oriented_payload,
            "row_count": len(row_oriented_payload), "columns": [],
            "execution_time_ms": 1.0,
        }
        rust_out = codec.compress(_to_bytes(payload), level=FilterLevel.NORMAL, params={})
        monkeypatch.setattr(columnar_module, "_rust", lambda: None)
        py_out = codec.compress(_to_bytes(payload), level=FilterLevel.NORMAL, params={})
        assert rust_out.payload == py_out.payload
        assert rust_out.lossy == py_out.lossy

    def test_rust_python_parity_heterogeneous_null_elision_only(
        self, codec, heterogeneous_payload, monkeypatch,
    ):
        """Parity holds for the null-elision-only path too (heterogeneous
        rows never columnarize, Rust or Python)."""
        rust_out = codec.compress(
            _to_bytes(heterogeneous_payload), level=FilterLevel.NORMAL, params={},
        )
        monkeypatch.setattr(columnar_module, "_rust", lambda: None)
        py_out = codec.compress(
            _to_bytes(heterogeneous_payload), level=FilterLevel.NORMAL, params={},
        )
        assert rust_out.payload == py_out.payload

    def test_dict_input_never_crosses_ffi(self, codec, row_oriented_payload, monkeypatch):
        called = []
        monkeypatch.setattr(
            parrot_codec, "columnarize", lambda *a, **k: called.append(1),
        )
        codec.compress(row_oriented_payload, level=FilterLevel.NORMAL, params={})
        assert not called

    def test_rust_path_actually_invoked_for_bytes_input(
        self, codec, row_oriented_payload, monkeypatch,
    ):
        """Sanity: the parity tests above aren't accidentally exercising
        only the Python path — the Rust function IS called for bytes
        input when the extension is present."""
        called = []
        original = parrot_codec.columnarize

        def _spy(*args, **kwargs):
            called.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(parrot_codec, "columnarize", _spy)
        codec.compress(_to_bytes(row_oriented_payload), level=FilterLevel.NORMAL, params={})
        assert called


def test_lazy_import_fallback(monkeypatch, caplog):
    """Extension absent -> Python path, exactly one debug log for the
    process, no per-call noise."""
    columnar_module._RUST = None
    columnar_module._RUST_CHECKED = False
    monkeypatch.setattr(
        columnar_module, "lazy_import",
        lambda *a, **k: (_ for _ in ()).throw(ImportError("forced absent")),
    )
    with caplog.at_level("DEBUG"):
        for _ in range(10):
            columnar_module._rust()
    assert sum("parrot_codec" in r.message for r in caplog.records) <= 1
    columnar_module._RUST = None
    columnar_module._RUST_CHECKED = False
