"""Unit tests for the render request/response models and dataset decoding
(FEAT-327, Module 2: ``handlers/infographic_render.py``).

Multipart bodies are built with a real ``aiohttp.MultipartWriter`` and fed
through ``aiohttp.test_utils.make_mocked_request`` + ``request.multipart()``
— exercising the actual aiohttp wire format without running a live server.
"""
from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import pytest
from aiohttp import MultipartWriter
from aiohttp.base_protocol import BaseProtocol
from aiohttp.streams import StreamReader
from aiohttp.test_utils import make_mocked_request
from pydantic import ValidationError

from parrot.handlers.infographic_render import (
    InlineDataset,
    RenderBodyTooLargeError,
    RenderJob,
    RenderPayloadError,
    RenderRequest,
    RenderResponse,
    decode_inline_datasets,
    parse_json_render_request,
    parse_multipart_render_request,
)
from parrot.tools.infographic_sections import SectionDescriptor

# NOTE: this package's pytest.ini_options sets `asyncio_mode = "auto"`, so
# async test functions are detected automatically — no blanket `pytestmark`
# needed (and none is applied, since this module mixes sync and async tests).


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _descriptor() -> SectionDescriptor:
    return SectionDescriptor(template="tpl", mode="data-splice", sections=[])


def _valid_request_kwargs(**overrides: Any) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "datasets": {},
        "template": "budget_variance",
        "descriptor": _descriptor(),
    }
    kwargs.update(overrides)
    return kwargs


async def _build_multipart_request(
    parts: List[Tuple[str, bytes, Optional[str]]],
):
    """Build a real aiohttp multipart request from ``(name, data, content_type)`` parts."""
    writer = MultipartWriter("form-data")
    for name, data, content_type in parts:
        headers = {"Content-Type": content_type} if content_type else None
        payload = writer.append(data, headers)
        payload.set_content_disposition("form-data", name=name)
    body = await writer.as_bytes()

    loop = asyncio.get_event_loop()
    protocol = BaseProtocol(loop=loop)
    stream = StreamReader(protocol, limit=2**20, loop=loop)
    stream.feed_data(body)
    stream.feed_eof()
    return make_mocked_request(
        "POST", "/render", headers={"Content-Type": writer.content_type}, payload=stream
    )


def _request_json_bytes(**overrides: Any) -> bytes:
    req = RenderRequest(**_valid_request_kwargs(**overrides))
    return req.model_dump_json(by_alias=True).encode("utf-8")


async def _build_json_request(data: bytes):
    """Build a real aiohttp request with a plain (non-multipart) JSON body.

    Used to test :func:`parse_json_render_request`'s capped-chunk reading
    against ``request.content`` — the same real ``StreamReader`` plumbing
    ``_build_multipart_request`` uses for the multipart transport.
    """
    loop = asyncio.get_event_loop()
    protocol = BaseProtocol(loop=loop)
    stream = StreamReader(protocol, limit=2**20, loop=loop)
    stream.feed_data(data)
    stream.feed_eof()
    return make_mocked_request(
        "POST", "/render", headers={"Content-Type": "application/json"}, payload=stream
    )


# ---------------------------------------------------------------------------
# RenderRequest / RenderResponse / RenderJob models
# ---------------------------------------------------------------------------

class TestRenderRequestModel:
    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            RenderRequest(**_valid_request_kwargs(bogus="nope"))

    def test_async_alias(self):
        payload = _valid_request_kwargs()
        payload["async"] = True
        req = RenderRequest.model_validate(payload)
        assert req.async_ is True

        # populate_by_name: constructing with the Python-safe field name also works.
        req2 = RenderRequest(**_valid_request_kwargs(async_=True))
        assert req2.async_ is True

        # Default is False when omitted.
        req3 = RenderRequest(**_valid_request_kwargs())
        assert req3.async_ is False

    def test_descriptor_is_feat326_model(self):
        req = RenderRequest(**_valid_request_kwargs())
        assert isinstance(req.descriptor, SectionDescriptor)

    def test_datasets_entry_may_be_none_for_multipart_hydration(self):
        req = RenderRequest(**_valid_request_kwargs(datasets={"revenue": None}))
        assert req.datasets["revenue"] is None

    def test_inline_dataset_orient_literal_enforced(self):
        with pytest.raises(ValidationError):
            InlineDataset(orient="csv", data=[])  # not a valid Literal


class TestRenderResponseAndJob:
    def test_render_response_forbids_extra(self):
        with pytest.raises(ValidationError):
            RenderResponse(
                artifact_id="a1",
                url=None,
                template="tpl",
                sections_validated=1,
                persisted=True,
                timings={},
                bogus="x",
            )

    def test_render_job_status_literal(self):
        with pytest.raises(ValidationError):
            RenderJob(
                job_id="j1",
                status="unknown",
                created_at="2026-07-24T00:00:00+00:00",
                deadline="2026-07-24T00:10:00+00:00",
            )


# ---------------------------------------------------------------------------
# Inline (JSON) dataset decoding
# ---------------------------------------------------------------------------

class TestInlineDatasetDecoding:
    def test_records_orient(self):
        req = RenderRequest(
            **_valid_request_kwargs(
                datasets={
                    "revenue": InlineDataset(
                        orient="records", data=[{"a": 1, "b": 2}, {"a": 3, "b": 4}]
                    )
                }
            )
        )
        frames = decode_inline_datasets(req)
        assert list(frames["revenue"].columns) == ["a", "b"]
        assert len(frames["revenue"]) == 2

    def test_split_orient(self):
        req = RenderRequest(
            **_valid_request_kwargs(
                datasets={
                    "revenue": InlineDataset(
                        orient="split",
                        data={"columns": ["a", "b"], "data": [[1, 2], [3, 4]]},
                    )
                }
            )
        )
        frames = decode_inline_datasets(req)
        assert list(frames["revenue"].columns) == ["a", "b"]
        assert frames["revenue"].iloc[0].tolist() == [1, 2]

    def test_none_entries_skipped(self):
        req = RenderRequest(**_valid_request_kwargs(datasets={"revenue": None}))
        frames = decode_inline_datasets(req)
        assert frames == {}

    def test_malformed_records_raises_payload_error(self):
        req = RenderRequest(
            **_valid_request_kwargs(
                datasets={"revenue": InlineDataset(orient="records", data={"not": "a list"})}
            )
        )
        with pytest.raises(RenderPayloadError) as exc:
            decode_inline_datasets(req)
        assert exc.value.part_name == "revenue"

    def test_malformed_split_raises_payload_error(self):
        req = RenderRequest(
            **_valid_request_kwargs(
                datasets={"revenue": InlineDataset(orient="split", data={"columns": ["a"]})}
            )
        )
        with pytest.raises(RenderPayloadError):
            decode_inline_datasets(req)


# ---------------------------------------------------------------------------
# Multipart decoding
# ---------------------------------------------------------------------------

class TestMultipartDecoding:
    async def test_records_and_split_via_json_part_only(self):
        request_json = _request_json_bytes()
        request = await _build_multipart_request([("request", request_json, "application/json")])
        reader = await request.multipart()
        parsed, frames = await parse_multipart_render_request(reader)
        assert parsed.template == "budget_variance"
        assert frames == {}

    async def test_parquet_part_preserves_dtypes(self):
        df = pd.DataFrame(
            {
                "amount": [1.5, 2.5],
                "day": pd.to_datetime(["2026-01-01", "2026-01-02"]),
                "category": pd.Categorical(["a", "b"]),
            }
        )
        buf = BytesIO()
        df.to_parquet(buf, engine="pyarrow")

        request_json = _request_json_bytes(datasets={"sales": None})
        request = await _build_multipart_request(
            [
                ("request", request_json, "application/json"),
                ("dataset:sales", buf.getvalue(), "application/vnd.apache.parquet"),
            ]
        )
        reader = await request.multipart()
        _, frames = await parse_multipart_render_request(reader)

        decoded = frames["sales"]
        assert str(decoded["day"].dtype).startswith("datetime64")
        assert str(decoded["category"].dtype) == "category"
        assert decoded["amount"].tolist() == [1.5, 2.5]

    async def test_csv_part(self):
        request_json = _request_json_bytes(datasets={"sales": None})
        request = await _build_multipart_request(
            [
                ("request", request_json, "application/json"),
                ("dataset:sales", b"a,b\n1,2\n3,4\n", "text/csv"),
            ]
        )
        reader = await request.multipart()
        _, frames = await parse_multipart_render_request(reader)
        assert list(frames["sales"].columns) == ["a", "b"]
        assert len(frames["sales"]) == 2

    async def test_missing_declared_part_400(self):
        request_json = _request_json_bytes(datasets={"sales": None})
        request = await _build_multipart_request([("request", request_json, "application/json")])
        reader = await request.multipart()
        with pytest.raises(RenderPayloadError) as exc:
            await parse_multipart_render_request(reader)
        assert exc.value.part_name == "dataset:sales"

    async def test_malformed_parquet_400_names_part(self):
        request_json = _request_json_bytes(datasets={"sales": None})
        request = await _build_multipart_request(
            [
                ("request", request_json, "application/json"),
                ("dataset:sales", b"not-a-real-parquet-file", "application/vnd.apache.parquet"),
            ]
        )
        reader = await request.multipart()
        with pytest.raises(RenderPayloadError) as exc:
            await parse_multipart_render_request(reader)
        assert exc.value.part_name == "dataset:sales"

    async def test_missing_request_part_400(self):
        request = await _build_multipart_request(
            [("dataset:sales", b"a,b\n1,2\n", "text/csv")]
        )
        reader = await request.multipart()
        with pytest.raises(RenderPayloadError) as exc:
            await parse_multipart_render_request(reader)
        assert exc.value.part_name == "request"

    async def test_body_cap_413(self):
        request_json = _request_json_bytes(datasets={"sales": None})
        large_csv = b"a,b\n" + b"1,2\n" * 10_000  # a few dozen KB
        request = await _build_multipart_request(
            [
                ("request", request_json, "application/json"),
                ("dataset:sales", large_csv, "text/csv"),
            ]
        )
        reader = await request.multipart()
        with pytest.raises(RenderBodyTooLargeError):
            await parse_multipart_render_request(reader, max_body_size=len(request_json) + 10)


# ---------------------------------------------------------------------------
# JSON (non-multipart) body decoding — same pre-buffering size cap as
# multipart (code-review fix: this transport was previously UNCAPPED at
# the application level, relying only on the framework's much larger
# app-wide client_max_size).
# ---------------------------------------------------------------------------

class TestJsonBodyDecoding:
    async def test_parses_plain_json_body(self):
        data = _request_json_bytes()
        request = await _build_json_request(data)
        parsed, frames = await parse_json_render_request(request)
        assert parsed.template == "budget_variance"
        assert frames == {}

    async def test_body_cap_413(self):
        data = _request_json_bytes(datasets={"a": None, "b": None, "c": None})
        request = await _build_json_request(data)
        with pytest.raises(RenderBodyTooLargeError):
            await parse_json_render_request(request, max_body_size=len(data) - 10)

    async def test_body_under_cap_succeeds(self):
        data = _request_json_bytes()
        request = await _build_json_request(data)
        parsed, _ = await parse_json_render_request(request, max_body_size=len(data) + 10)
        assert parsed.template == "budget_variance"

    async def test_malformed_json_raises_payload_error(self):
        request = await _build_json_request(b"{not valid json")
        with pytest.raises(RenderPayloadError) as exc:
            await parse_json_render_request(request)
        assert exc.value.part_name == "request"

    async def test_null_dataset_without_multipart_raises_payload_error(self):
        data = _request_json_bytes(datasets={"revenue": None})
        request = await _build_json_request(data)
        with pytest.raises(RenderPayloadError) as exc:
            await parse_json_render_request(request)
        assert exc.value.part_name == "dataset:revenue"
