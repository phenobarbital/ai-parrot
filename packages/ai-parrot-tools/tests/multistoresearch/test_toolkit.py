"""Unit tests for MultiStoreSearchToolkit (FEAT-379)."""
import asyncio

from parrot.models import MultiSearch, OriginHit, SearchOriginKind
from parrot_tools.multistoresearch import MultiStoreSearchToolkit
from parrot_tools.multistoresearch.origins.base import SearchOrigin


class FakeOrigin(SearchOrigin):
    def __init__(
        self,
        name,
        hits,
        kind=SearchOriginKind.VECTOR,
        supports_fts=False,
        delay=0.0,
        timeout=None,
        fail=False,
        fail_fts=False,
    ):
        self.name = name
        self.kind = kind
        self.description = f"{name} description"
        self.supports_fts = supports_fts
        self.timeout = timeout
        self._hits = hits
        self._delay = delay
        self._fail = fail
        self._fail_fts = fail_fts

    async def search(self, query, k):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail:
            raise RuntimeError("boom")
        return self._hits

    async def fts_search(self, query, k):
        if self._fail_fts:
            raise RuntimeError("fts boom")
        return self._hits


def _hit(origin, kind, content, hit_id=None, native_rank=1, score=None):
    return OriginHit(
        id=hit_id,
        content=content,
        score=score,
        metadata={},
        origin=origin,
        origin_kind=kind,
        native_rank=native_rank,
    )


def make_origin(name, hits, **kw):
    return FakeOrigin(name, hits, **kw)


async def test_store_search_grouped_and_merged():
    tk = MultiStoreSearchToolkit(
        origins=[
            make_origin("a", [_hit("a", SearchOriginKind.VECTOR, "apple pie recipe")]),
            make_origin(
                "b", [_hit("b", SearchOriginKind.WIKI, "banana bread recipe")]
            ),
        ]
    )
    resp = await tk.store_search("recipe")
    assert {s.origin for s in resp.sections} == {"a", "b"}
    assert all(s.status == "ok" for s in resp.sections)
    assert resp.merged_top_k
    assert resp.notes


async def test_timeout_isolated():
    tk = MultiStoreSearchToolkit(
        origins=[
            make_origin(
                "slow",
                [_hit("slow", SearchOriginKind.VECTOR, "slow content")],
                delay=1.0,
            ),
            make_origin(
                "fast", [_hit("fast", SearchOriginKind.VECTOR, "fast content")]
            ),
        ],
        default_timeout=0.05,
    )
    resp = await tk.store_search("q")
    by = {s.origin: s for s in resp.sections}
    assert by["slow"].status == "timeout"
    assert by["fast"].status == "ok"
    assert by["slow"].note is not None


async def test_error_isolated():
    tk = MultiStoreSearchToolkit(
        origins=[
            make_origin("boom", [], fail=True),
            make_origin(
                "ok", [_hit("ok", SearchOriginKind.VECTOR, "fine content")]
            ),
        ]
    )
    resp = await tk.store_search("q")
    by = {s.origin: s for s in resp.sections}
    assert by["boom"].status == "error"
    assert "RuntimeError" in by["boom"].note
    assert by["ok"].status == "ok"


async def test_protocol_satisfied():
    tk = MultiStoreSearchToolkit(origins=[])
    assert isinstance(tk, MultiSearch)


async def test_fts_skips_non_capable():
    tk = MultiStoreSearchToolkit(
        origins=[
            make_origin(
                "vec", [_hit("vec", SearchOriginKind.VECTOR, "vector content")]
            ),
            make_origin(
                "wiki",
                [_hit("wiki", SearchOriginKind.WIKI, "wiki content")],
                supports_fts=True,
            ),
        ]
    )
    resp = await tk.fts_search("q")
    by = {s.origin: s for s in resp.sections}
    assert by["vec"].status == "skipped"
    assert by["wiki"].status == "ok"


async def test_fts_search_zero_capable_returns_notes_only():
    tk = MultiStoreSearchToolkit(
        origins=[
            make_origin(
                "vec", [_hit("vec", SearchOriginKind.VECTOR, "vector content")]
            )
        ]
    )
    resp = await tk.fts_search("q")
    assert resp.merged_top_k == []
    assert resp.sections[0].status == "skipped"
    assert resp.notes


async def test_batch_search_empty_list():
    tk = MultiStoreSearchToolkit(origins=[make_origin("a", [])])
    assert await tk.batch_search([]) == []


async def test_batch_search_gather_shape():
    tk = MultiStoreSearchToolkit(
        origins=[
            make_origin("a", [_hit("a", SearchOriginKind.VECTOR, "content a")]),
            make_origin("b", [_hit("b", SearchOriginKind.VECTOR, "content b")]),
        ]
    )
    responses = await tk.batch_search(["q1", "q2"])
    assert len(responses) == 2
    assert responses[0].query == "q1"
    assert responses[1].query == "q2"
    for resp in responses:
        assert {s.origin for s in resp.sections} == {"a", "b"}


async def test_no_origins_configured():
    tk = MultiStoreSearchToolkit(origins=[])
    resp = await tk.store_search("q")
    assert resp.sections == []
    assert resp.merged_top_k == []
    assert resp.notes


async def test_no_origins_configured_batch():
    tk = MultiStoreSearchToolkit(origins=[])
    responses = await tk.batch_search(["q1", "q2"])
    assert len(responses) == 2
    assert all(r.sections == [] and r.merged_top_k == [] for r in responses)


async def test_list_search_origins():
    tk = MultiStoreSearchToolkit(
        origins=[
            make_origin(
                "wiki",
                [],
                kind=SearchOriginKind.WIKI,
                supports_fts=True,
                timeout=5.0,
            )
        ]
    )
    listing = await tk.list_search_origins()
    assert listing == [
        {
            "name": "wiki",
            "kind": "wiki",
            "description": "wiki description",
            "supports_fts": True,
            "timeout": 5.0,
        }
    ]


async def test_list_search_origins_surfaces_mode_attribute():
    origin = make_origin("pageindex", [], kind=SearchOriginKind.PAGEINDEX)
    origin.mode = "hybrid"
    tk = MultiStoreSearchToolkit(origins=[origin])
    listing = await tk.list_search_origins()
    assert listing[0]["mode"] == "hybrid"


async def test_merged_top_k_deduplicates_by_id():
    dup_hit_a = _hit("a", SearchOriginKind.VECTOR, "same content here", hit_id="dup")
    dup_hit_b = _hit("b", SearchOriginKind.WIKI, "same content here", hit_id="dup")
    tk = MultiStoreSearchToolkit(
        origins=[make_origin("a", [dup_hit_a]), make_origin("b", [dup_hit_b])]
    )
    resp = await tk.store_search("same content")
    ids = [h.id for h in resp.merged_top_k]
    assert ids.count("dup") == 1


async def test_merged_top_k_respects_k():
    hits = [
        _hit("a", SearchOriginKind.VECTOR, f"unique content number {i}", hit_id=str(i))
        for i in range(5)
    ]
    tk = MultiStoreSearchToolkit(origins=[make_origin("a", hits)], k=2)
    resp = await tk.store_search("unique content")
    assert len(resp.merged_top_k) == 2
