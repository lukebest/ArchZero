"""Prior-art retrieval and comparison for patent disclosures.

Uses only ``httpx`` (already a core dependency), so this layer works without
the ``patent`` extra — it emits JSON/Markdown and never touches python-pptx.

Honesty contract, mirroring how Tier5/Tier6 report UNAVAILABLE rather than a
fake PASS: when the network is down we mark ``retrieval_status="offline"`` and
say so on the slide. We never present unverified recall as a real search.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote_plus

from pydantic import BaseModel, Field

from archzero.config import FactoryConfig
from archzero.generation.cleanroom import _parse_json
from archzero.llm.client import CursorLLM
from archzero.models import Candidate, ProblemPackage, TaskClass

log = logging.getLogger("archzero.patent.prior_art")

ARXIV_API = "http://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = "title,abstract,year,authors,externalIds,url,venue"

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_OFFLINE = "offline"

_ATOM = "{http://www.w3.org/2005/Atom}"

# Semantic Scholar's unauthenticated tier is ~1 rps; going faster earns 429s.
_S2_MIN_INTERVAL = 1.1
_s2_lock = asyncio.Lock()
_s2_last = 0.0


class PriorArtHit(BaseModel):
    source: str  # arxiv | semantic_scholar
    title: str
    abstract: str = ""
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    url: str = ""
    external_id: str = ""
    venue: str = ""
    query: str = ""

    def citation(self) -> str:
        who = self.authors[0] + (" et al." if len(self.authors) > 1 else "")
        when = str(self.year) if self.year else "n.d."
        where = f", {self.venue}" if self.venue else ""
        return f"{who or '佚名'} ({when}){where}"


class PriorArtComparison(BaseModel):
    title: str
    citation: str = ""
    url: str = ""
    same_points: str = ""
    diff_points: str = ""
    distinguishing_features: str = ""
    threat: str = "low"  # high | medium | low


class PatentQuerySuggestion(BaseModel):
    ipc: list[str] = Field(default_factory=list)
    queries_cn: list[str] = Field(default_factory=list)
    queries_en: list[str] = Field(default_factory=list)


class PriorArtResult(BaseModel):
    retrieval_status: str = STATUS_OFFLINE
    queries: list[str] = Field(default_factory=list)
    hits: list[PriorArtHit] = Field(default_factory=list)
    comparisons: list[PriorArtComparison] = Field(default_factory=list)
    patent_suggestion: PatentQuerySuggestion = Field(
        default_factory=PatentQuerySuggestion
    )
    notes: list[str] = Field(default_factory=list)

    @property
    def verified(self) -> bool:
        return self.retrieval_status == STATUS_OK

    def caveat(self) -> str:
        if self.retrieval_status == STATUS_OK:
            return "本节结果来自 arXiv / Semantic Scholar 实时检索。专利库未自动检索，需人工执行。"
        if self.retrieval_status == STATUS_PARTIAL:
            return "部分检索源不可达，本节结果不完整，需人工补充核实。"
        return "检索源全部不可达，本节未执行真实检索，全部内容待人工核实。"


QUERY_PERSONA = """你把一个中文的计算机体系结构机制方案，转成用于英文文献检索的检索式。

要求：
1. 检索式必须是英文，使用该领域论文实际会用的术语，而不是中文直译。
2. 覆盖不同抽象层次：机制名、所解决的瓶颈、所属结构部件。
3. 每条 3-8 个词，不要用布尔运算符，不要加引号。

只返回 JSON：{"queries": ["...", "..."]}"""

COMPARE_PERSONA = """你是专利审查员，正在做检索对比。

给你本方案与一批已公开文献，逐条判断：
- same_points: 与本方案相同或高度相似之处
- diff_points: 该文献没有做到而本方案做到的
- distinguishing_features: 本方案相对该文献的区别性技术特征（用于撰写权利要求）
- threat: 该文献对本方案新颖性的威胁等级，取值 high | medium | low

判断要保守：只要文献摘要没有明确公开某特征，就不要臆断它公开了。
若摘要信息不足以判断，在 diff_points 中写明「摘要信息不足，需查全文」。

只返回 JSON：
{"comparisons": [
  {"title": "原文标题", "same_points": "...", "diff_points": "...",
   "distinguishing_features": "...", "threat": "low"}
]}

same_points、diff_points、distinguishing_features 用简体中文；threat 保持英文枚举值。"""

PATENT_QUERY_PERSONA = """你为一个计算机体系结构方案设计专利库检索策略。

只返回 JSON：
{"ipc": ["G06F12/08"], "queries_cn": ["..."], "queries_en": ["..."]}

ipc 给 2-5 个最相关的 IPC/CPC 分类号。
queries_cn / queries_en 各给 3-5 条检索式，可使用 AND / OR 布尔运算符。"""


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def _norm_id(external_id: str) -> str:
    """arXiv reports ``2401.00001v1``, Semantic Scholar reports ``2401.00001``."""
    ident = (external_id or "").lower().strip()
    ident = re.sub(r"^(arxiv:|doi:)", "", ident)
    return re.sub(r"v\d+$", "", ident)


def _cache_path(cfg: FactoryConfig, kind: str, query: str):
    digest = hashlib.sha256(f"{kind}\n{query}".encode()).hexdigest()[:20]
    cfg.prior_art_dir.mkdir(parents=True, exist_ok=True)
    return cfg.prior_art_dir / f"{kind}-{digest}.json"


def _read_cache(cfg: FactoryConfig, kind: str, query: str) -> list[dict] | None:
    path = _cache_path(cfg, kind, query)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(cfg: FactoryConfig, kind: str, query: str, rows: list[dict]) -> None:
    try:
        _cache_path(cfg, kind, query).write_text(
            json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as exc:  # noqa: BLE001
        log.debug("prior_art cache write failed: %s", exc)


def _parse_arxiv(xml_text: str, query: str) -> list[PriorArtHit]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out: list[PriorArtHit] = []
    for entry in root.findall(f"{_ATOM}entry"):
        title = (entry.findtext(f"{_ATOM}title") or "").strip()
        if not title:
            continue
        summary = (entry.findtext(f"{_ATOM}summary") or "").strip()
        raw_id = (entry.findtext(f"{_ATOM}id") or "").strip()
        published = (entry.findtext(f"{_ATOM}published") or "").strip()
        year: int | None = None
        if len(published) >= 4 and published[:4].isdigit():
            year = int(published[:4])
        authors = [
            (a.findtext(f"{_ATOM}name") or "").strip()
            for a in entry.findall(f"{_ATOM}author")
        ]
        out.append(
            PriorArtHit(
                source="arxiv",
                title=re.sub(r"\s+", " ", title),
                abstract=re.sub(r"\s+", " ", summary),
                year=year,
                authors=[a for a in authors if a],
                url=raw_id,
                external_id=raw_id.rsplit("/", 1)[-1] if raw_id else "",
                query=query,
            )
        )
    return out


async def search_arxiv(
    cfg: FactoryConfig,
    query: str,
    *,
    limit: int = 10,
    client: Any | None = None,
) -> list[PriorArtHit]:
    cached = _read_cache(cfg, "arxiv", query)
    if cached is not None:
        return [PriorArtHit(**row) for row in cached]

    import httpx

    url = (
        f"{ARXIV_API}?search_query=all:{quote_plus(query)}"
        f"&start=0&max_results={limit}&sortBy=relevance"
    )
    own = client is None
    client = client or httpx.AsyncClient(timeout=cfg.patent.request_timeout_s)
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        hits = _parse_arxiv(resp.text, query)
    finally:
        if own:
            await client.aclose()
    _write_cache(cfg, "arxiv", query, [h.model_dump(mode="json") for h in hits])
    return hits


async def search_semantic_scholar(
    cfg: FactoryConfig,
    query: str,
    *,
    limit: int = 10,
    client: Any | None = None,
) -> list[PriorArtHit]:
    cached = _read_cache(cfg, "s2", query)
    if cached is not None:
        return [PriorArtHit(**row) for row in cached]

    import httpx

    global _s2_last
    async with _s2_lock:
        wait = _S2_MIN_INTERVAL - (time.monotonic() - _s2_last)
        if wait > 0:
            await asyncio.sleep(wait)
        _s2_last = time.monotonic()

    url = f"{S2_API}?query={quote_plus(query)}&limit={limit}&fields={S2_FIELDS}"
    own = client is None
    client = client or httpx.AsyncClient(timeout=cfg.patent.request_timeout_s)
    try:
        resp = await client.get(url)
        if resp.status_code == 429:
            await asyncio.sleep(3.0)
            resp = await client.get(url)
        resp.raise_for_status()
        payload = resp.json()
    finally:
        if own:
            await client.aclose()

    hits: list[PriorArtHit] = []
    for row in payload.get("data") or []:
        title = (row.get("title") or "").strip()
        if not title:
            continue
        ext = row.get("externalIds") or {}
        hits.append(
            PriorArtHit(
                source="semantic_scholar",
                title=title,
                abstract=(row.get("abstract") or "").strip(),
                year=row.get("year"),
                authors=[
                    a.get("name", "") for a in (row.get("authors") or []) if a.get("name")
                ],
                url=row.get("url") or "",
                external_id=str(ext.get("DOI") or ext.get("ArXiv") or ""),
                venue=(row.get("venue") or "").strip(),
                query=query,
            )
        )
    _write_cache(cfg, "s2", query, [h.model_dump(mode="json") for h in hits])
    return hits


async def generate_queries(
    llm: CursorLLM,
    candidate: Candidate,
    problem: ProblemPackage | None = None,
    *,
    max_queries: int = 6,
) -> list[str]:
    ctx = f"方案标题：{candidate.title}\n\n机制描述：\n{candidate.mechanism[:4000]}"
    if problem is not None:
        ctx += f"\n\n所属问题：{problem.title}"
    ctx += f"\n\n请给出至多 {max_queries} 条英文检索式。"
    data = _parse_json(
        await llm.complete(QUERY_PERSONA, ctx, TaskClass.PRIOR_ART, expect_json=True)
    )
    queries = [str(q).strip() for q in (data.get("queries") or []) if str(q).strip()]
    return queries[:max_queries]


async def collect_hits(
    cfg: FactoryConfig,
    queries: list[str],
    *,
    max_hits: int = 15,
    client: Any | None = None,
) -> tuple[list[PriorArtHit], str, list[str]]:
    """Query both sources; return (hits, retrieval_status, notes)."""
    per_query = max(3, max_hits // max(1, len(queries)))
    notes: list[str] = []
    ok_sources: set[str] = set()
    failed_sources: set[str] = set()
    merged: list[PriorArtHit] = []
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()

    for query in queries:
        for name, fn in (
            ("arxiv", search_arxiv),
            ("semantic_scholar", search_semantic_scholar),
        ):
            try:
                hits = await fn(cfg, query, limit=per_query, client=client)
                ok_sources.add(name)
            except Exception as exc:  # noqa: BLE001
                failed_sources.add(name)
                notes.append(f"{name} 检索失败（{query}）：{exc}")
                continue
            for hit in hits:
                # The same paper reaches us under different ids from each
                # source, so title is a necessary second key.
                ident = _norm_id(hit.external_id)
                title = _norm_title(hit.title)
                if (ident and ident in seen_ids) or (title and title in seen_titles):
                    continue
                if ident:
                    seen_ids.add(ident)
                if title:
                    seen_titles.add(title)
                merged.append(hit)

    if ok_sources and not failed_sources:
        status = STATUS_OK
    elif ok_sources:
        status = STATUS_PARTIAL
    else:
        status = STATUS_OFFLINE

    ranked = sorted(
        merged,
        key=lambda h: (h.year or 0, len(h.abstract)),
        reverse=True,
    )
    return ranked[:max_hits], status, notes


async def compare(
    llm: CursorLLM,
    candidate: Candidate,
    hits: list[PriorArtHit],
) -> list[PriorArtComparison]:
    if not hits:
        return []
    listing = "\n\n".join(
        f"[{i + 1}] {h.title} ({h.year or 'n.d.'})\n摘要：{h.abstract[:1200] or '（无摘要）'}"
        for i, h in enumerate(hits)
    )
    ctx = (
        f"本方案标题：{candidate.title}\n\n"
        f"本方案机制：\n{candidate.mechanism[:4000]}\n\n"
        f"已检索到的文献：\n{listing}"
    )
    data = _parse_json(
        await llm.complete(COMPARE_PERSONA, ctx, TaskClass.PRIOR_ART, expect_json=True)
    )
    by_title = {_norm_title(h.title): h for h in hits}
    out: list[PriorArtComparison] = []
    for row in data.get("comparisons") or []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        hit = by_title.get(_norm_title(title))
        threat = str(row.get("threat") or "low").lower()
        out.append(
            PriorArtComparison(
                title=title or (hit.title if hit else "未命名文献"),
                citation=hit.citation() if hit else "",
                url=hit.url if hit else "",
                same_points=str(row.get("same_points") or ""),
                diff_points=str(row.get("diff_points") or ""),
                distinguishing_features=str(row.get("distinguishing_features") or ""),
                threat=threat if threat in {"high", "medium", "low"} else "low",
            )
        )
    return out


async def suggest_patent_queries(
    llm: CursorLLM,
    candidate: Candidate,
) -> PatentQuerySuggestion:
    ctx = f"方案标题：{candidate.title}\n\n机制描述：\n{candidate.mechanism[:4000]}"
    data = _parse_json(
        await llm.complete(
            PATENT_QUERY_PERSONA, ctx, TaskClass.PRIOR_ART, expect_json=True
        )
    )
    return PatentQuerySuggestion(
        ipc=[str(x) for x in (data.get("ipc") or [])],
        queries_cn=[str(x) for x in (data.get("queries_cn") or [])],
        queries_en=[str(x) for x in (data.get("queries_en") or [])],
    )


async def run_prior_art(
    cfg: FactoryConfig,
    candidate: Candidate,
    *,
    problem: ProblemPackage | None = None,
    llm: CursorLLM | None = None,
    search: bool = True,
) -> PriorArtResult:
    """Full section-6 pipeline: queries -> retrieval -> comparison.

    Any stage may fail without aborting the disclosure; the result carries the
    degradation in ``retrieval_status`` and ``notes``.
    """
    if not search or not cfg.patent.search_enabled:
        return PriorArtResult(
            retrieval_status=STATUS_OFFLINE,
            notes=["检索已被显式关闭（--no-search 或 patent.search_enabled=false）"],
        )

    own = llm is None
    llm = llm or CursorLLM(cfg)
    if own:
        await llm.setup()

    result = PriorArtResult()
    try:
        try:
            result.queries = await generate_queries(
                llm, candidate, problem, max_queries=cfg.patent.max_queries
            )
        except Exception as exc:  # noqa: BLE001
            result.notes.append(f"检索式生成失败，回退到标题检索：{exc}")
            result.queries = [candidate.title[:120]]

        hits, status, notes = await collect_hits(
            cfg, result.queries, max_hits=cfg.patent.max_hits
        )
        result.hits = hits
        result.retrieval_status = status
        result.notes.extend(notes)

        if hits:
            try:
                result.comparisons = await compare(llm, candidate, hits)
            except Exception as exc:  # noqa: BLE001
                result.notes.append(f"逐条对比失败：{exc}")

        try:
            result.patent_suggestion = await suggest_patent_queries(llm, candidate)
        except Exception as exc:  # noqa: BLE001
            result.notes.append(f"专利检索式建议生成失败：{exc}")
    finally:
        if own:
            await llm.aclose()

    return result


def prior_art_markdown(result: PriorArtResult) -> str:
    lines = ["## 六、与现有公开的专利/论文的检索与对比", ""]
    lines.append(f"> {result.caveat()}")
    lines.append("")
    lines.append(f"- 检索状态: `{result.retrieval_status}`")
    if result.queries:
        lines.append(f"- 检索式: {', '.join(f'`{q}`' for q in result.queries)}")
    lines.append(f"- 命中文献: {len(result.hits)} 篇")
    lines.append("")

    if result.comparisons:
        lines.append("| 对比文献 | 相同点 | 不同点 | 区别性技术特征 | 威胁 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for c in result.comparisons:
            cells = [
                c.title.replace("|", "/"),
                c.same_points.replace("|", "/") or "-",
                c.diff_points.replace("|", "/") or "-",
                c.distinguishing_features.replace("|", "/") or "-",
                c.threat,
            ]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    elif result.hits:
        lines.append("命中文献（未完成逐条对比）：")
        lines.append("")
        for h in result.hits:
            lines.append(f"- {h.title} — {h.citation()} {h.url}")
        lines.append("")
    else:
        lines.append("_未检索到文献_")
        lines.append("")

    sug = result.patent_suggestion
    if sug.ipc or sug.queries_cn or sug.queries_en:
        lines.append("### 专利库检索建议（未自动检索，需在内部专利库执行）")
        lines.append("")
        if sug.ipc:
            lines.append(f"- IPC/CPC: {', '.join(sug.ipc)}")
        for q in sug.queries_cn:
            lines.append(f"- 中文检索式: `{q}`")
        for q in sug.queries_en:
            lines.append(f"- 英文检索式: `{q}`")
        lines.append("")

    if result.notes:
        lines.append("### 检索备注")
        lines.append("")
        for n in result.notes:
            lines.append(f"- {n}")
        lines.append("")
    return "\n".join(lines)
