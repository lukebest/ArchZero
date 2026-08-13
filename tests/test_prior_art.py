"""Prior-art retrieval: parsing, dedup, caching, and offline degradation.

Never touches the real network — every httpx call goes through a fake client.
"""

from __future__ import annotations

import json

import pytest

from archzero.llm.fake import FakeLLM
from archzero.models import Candidate
from archzero.patent import prior_art as pa

pytestmark = pytest.mark.patent

ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <published>2024-01-02T00:00:00Z</published>
    <title>Dead-Block   Filtered
      Prefetching</title>
    <summary>We filter prefetches using dead-block prediction.</summary>
    <author><name>A Author</name></author>
    <author><name>B Author</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2301.00002v1</id>
    <published>2023-05-02T00:00:00Z</published>
    <title>Irrelevant Work</title>
    <summary>Something else.</summary>
    <author><name>C Author</name></author>
  </entry>
</feed>
"""

S2_JSON = {
    "data": [
        {
            "title": "Dead-Block Filtered Prefetching",
            "abstract": "Duplicate of the arXiv entry, found via DOI.",
            "year": 2024,
            "authors": [{"name": "A Author"}],
            "externalIds": {"ArXiv": "2401.00001"},
            "url": "https://s2/paper/1",
            "venue": "ISCA",
        },
        {
            "title": "Cache Partitioning by Auction",
            "abstract": "Bidding for cache ways.",
            "year": 2022,
            "authors": [{"name": "D Author"}],
            "externalIds": {"DOI": "10.1145/xyz"},
            "url": "https://s2/paper/2",
            "venue": "MICRO",
        },
    ]
}


class FakeResponse:
    def __init__(self, *, text: str = "", payload=None, status_code: int = 200) -> None:
        self.text = text
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    """Routes by URL so one client can serve both sources."""

    def __init__(self, *, arxiv=None, s2=None) -> None:
        self._arxiv = arxiv
        self._s2 = s2
        self.urls: list[str] = []

    async def get(self, url: str):
        self.urls.append(url)
        handler = self._arxiv if "arxiv.org" in url else self._s2
        if handler is None:
            raise RuntimeError("connection refused")
        if isinstance(handler, Exception):
            raise handler
        return handler

    async def aclose(self) -> None:
        pass


@pytest.fixture
def candidate() -> Candidate:
    return Candidate(
        problem_id="pp-demo",
        title="死块过滤预取",
        mechanism="用死块预测过滤 L2 预取请求。",
        family="prefetch",
    )


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(pa, "_S2_MIN_INTERVAL", 0.0)


@pytest.fixture
def force_offline(monkeypatch):
    """Make the sources unreachable regardless of the host's connectivity."""

    async def _boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(pa, "search_arxiv", _boom)
    monkeypatch.setattr(pa, "search_semantic_scholar", _boom)


@pytest.mark.asyncio
async def test_arxiv_parses_and_normalizes_whitespace(tmp_cfg):
    client = FakeClient(arxiv=FakeResponse(text=ARXIV_XML))
    hits = await pa.search_arxiv(tmp_cfg, "prefetch filtering", client=client)

    assert [h.title for h in hits] == [
        "Dead-Block Filtered Prefetching",
        "Irrelevant Work",
    ]
    assert hits[0].year == 2024
    assert hits[0].external_id == "2401.00001v1"
    assert hits[0].citation().startswith("A Author et al. (2024)")


@pytest.mark.asyncio
async def test_semantic_scholar_extracts_external_ids(tmp_cfg):
    client = FakeClient(s2=FakeResponse(payload=S2_JSON))
    hits = await pa.search_semantic_scholar(tmp_cfg, "cache auction", client=client)

    assert [h.external_id for h in hits] == ["2401.00001", "10.1145/xyz"]
    assert hits[1].venue == "MICRO"


@pytest.mark.asyncio
async def test_results_are_cached_by_query_hash(tmp_cfg):
    client = FakeClient(arxiv=FakeResponse(text=ARXIV_XML))
    await pa.search_arxiv(tmp_cfg, "same query", client=client)
    assert len(client.urls) == 1

    cached = await pa.search_arxiv(tmp_cfg, "same query", client=client)
    assert len(client.urls) == 1  # served from .archzero/prior_art
    assert cached[0].title == "Dead-Block Filtered Prefetching"


@pytest.mark.asyncio
async def test_collect_hits_dedups_across_sources(tmp_cfg):
    client = FakeClient(
        arxiv=FakeResponse(text=ARXIV_XML), s2=FakeResponse(payload=S2_JSON)
    )
    hits, status, notes = await pa.collect_hits(
        tmp_cfg, ["prefetch"], max_hits=10, client=client
    )

    assert status == pa.STATUS_OK
    assert notes == []
    # arXiv 2401.00001v1 and S2 ArXiv:2401.00001 are different ids, but the two
    # "Irrelevant Work" / "Cache Partitioning" entries must all survive.
    titles = [h.title for h in hits]
    assert "Cache Partitioning by Auction" in titles
    assert len(titles) == len(set(titles))


@pytest.mark.asyncio
async def test_partial_when_one_source_fails(tmp_cfg):
    client = FakeClient(arxiv=FakeResponse(text=ARXIV_XML), s2=None)
    hits, status, notes = await pa.collect_hits(
        tmp_cfg, ["prefetch"], max_hits=10, client=client
    )

    assert status == pa.STATUS_PARTIAL
    assert hits
    assert any("semantic_scholar" in n for n in notes)


@pytest.mark.asyncio
async def test_offline_when_all_sources_fail(tmp_cfg):
    client = FakeClient()
    hits, status, notes = await pa.collect_hits(
        tmp_cfg, ["prefetch"], max_hits=10, client=client
    )

    assert status == pa.STATUS_OFFLINE
    assert hits == []
    assert len(notes) == 2


@pytest.mark.asyncio
async def test_run_prior_art_degrades_without_inventing_hits(
    tmp_cfg, candidate, force_offline
):
    """Offline must not silently produce a comparison table."""
    llm = FakeLLM(responses={"prior_art": json.dumps({"queries": ["prefetch filter"]})})
    result = await pa.run_prior_art(tmp_cfg, candidate, llm=llm, search=True)

    assert result.retrieval_status == pa.STATUS_OFFLINE
    assert result.hits == []
    assert result.comparisons == []
    assert not result.verified
    assert "待人工核实" in result.caveat()


@pytest.mark.asyncio
async def test_search_disabled_short_circuits(tmp_cfg, candidate):
    llm = FakeLLM()
    result = await pa.run_prior_art(tmp_cfg, candidate, llm=llm, search=False)

    assert result.retrieval_status == pa.STATUS_OFFLINE
    assert result.queries == []
    assert llm.calls == []


@pytest.mark.asyncio
async def test_compare_maps_rows_back_to_hits(tmp_cfg, candidate):
    hits = pa._parse_arxiv(ARXIV_XML, "prefetch")
    llm = FakeLLM(
        responses={
            "prior_art": json.dumps(
                {
                    "comparisons": [
                        {
                            "title": "Dead-Block Filtered Prefetching",
                            "same_points": "同样使用死块预测",
                            "diff_points": "未做带宽约束",
                            "distinguishing_features": "本方案增加带宽预算反馈",
                            "threat": "HIGH",
                        },
                        {"title": "查无此文", "threat": "bogus"},
                    ]
                },
                ensure_ascii=False,
            )
        }
    )
    rows = await pa.compare(llm, candidate, hits)

    assert rows[0].threat == "high"
    assert rows[0].citation.startswith("A Author et al. (2024)")
    assert rows[1].threat == "low"  # unknown enum falls back
    assert rows[1].citation == ""


def test_markdown_flags_unverified_retrieval():
    result = pa.PriorArtResult(
        retrieval_status=pa.STATUS_OFFLINE,
        notes=["arxiv 检索失败"],
        patent_suggestion=pa.PatentQuerySuggestion(ipc=["G06F12/08"]),
    )
    md = pa.prior_art_markdown(result)

    assert "检索源全部不可达" in md
    assert "未自动检索" in md
    assert "G06F12/08" in md
    assert "arxiv 检索失败" in md
