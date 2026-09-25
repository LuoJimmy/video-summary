import re
import threading
from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy import or_

from app.models import Job
from app.schemas import AppSettingsOut, KnowledgeDoc, KnowledgeHit, KnowledgeSearchOut
from app.services.digest import DIGEST_SOURCE_TYPES, is_digest_source
from app.services.domain import DEFAULT_DOMAIN_ID, knowledge_system, pack_by_id, stored_job_domain
from app.services.httpclient import create_chat_completion, openai_client
from app.services.jsonutil import coerce_model_text, loads
from app.services.textnorm import to_simplified

KIND_LABELS = {
    "title": "标题",
    "transcript": "转写",
    "overview": "综述",
    "chapter": "章节",
    "key_point": "要点",
}

MAX_HITS = 40
MAX_CHAT_CHUNKS = 10
MAX_CONTEXT_CHARS = 7000
MAX_INDEX_JOBS = 200  # 切片索引缓存的任务数上限，超出按最久未用淘汰
STOP_CHARS = set("的了是在和与或就都也要这那吗呢啊吧呀么啥着过给被把对从到而及与并或")
STOP_WORDS = {"什么", "怎么", "如何", "哪些", "有没有", "请问", "一下", "这个", "那个", "为啥", "为何"}


class KnowledgeError(RuntimeError):
    pass


@dataclass
class _Chunk:
    job_id: str
    title: str
    kind: str
    text: str
    start: float = 0
    end: float = 0
    segment_id: int | None = None
    locator: str = ""
    hay: str = ""  # 繁简归一化 + casefold 的「标题 正文」，跨请求复用，避免每次检索重算


CHAT_SYSTEM = """你是用户的私人知识库助手。资料全部来自用户自己转写的音视频或导入的文档，只存在本机，回答时不要编造资料之外的内容。
规则：
1. 只根据【资料】回答用户问题。资料不足就直说知识库里没有足够依据，不要用常识编造。
2. 必须使用简体中文。分段书写，关键结论、对象、数字、方法用**加粗**。
3. 提到具体说法时标注来源。音视频用〔标题 · mm:ss〕；文档用〔标题〕或〔标题 · 第N页/第N段〕，必须来自资料。
"""


def jobs_in_domain(jobs: list[Job], domain_id: str | None) -> list[Job]:
    target = stored_job_domain(domain_id)
    return [job for job in jobs if stored_job_domain(job.domain_id) == target]


def knowledge_jobs_filter(query, domain_id: str | None):
    """按领域收窄已有 Job 查询，空值和 custom 与 A 股视为同一领域。"""
    target = stored_job_domain(domain_id)
    if target == DEFAULT_DOMAIN_ID:
        return query.filter(
            or_(
                Job.domain_id == "",
                Job.domain_id == "custom",
                Job.domain_id == DEFAULT_DOMAIN_ID,
                Job.domain_id.is_(None),
            )
        )
    return query.filter(Job.domain_id == target)


def job_has_knowledge_text(job: Job) -> bool:
    if is_digest_source(job.source_type):
        return False
    return bool((job.transcript_json or "").strip())


def knowledge_content_filter(query):
    return query.filter(Job.transcript_json != "").filter(~Job.source_type.in_(DIGEST_SOURCE_TYPES))


def search_knowledge(
    jobs: list[Job],
    query: str = "",
    page: int = 1,
    page_size: int = 20,
    total: int | None = None,
) -> KnowledgeSearchOut:
    query = to_simplified(query).strip()
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))
    if not query:
        documents = [_doc(job) for job in jobs if job_has_knowledge_text(job)]
        count = total if total is not None else len(documents)
        paged = documents if total is not None else _page_items(documents, page, page_size)
        return KnowledgeSearchOut(
            query="",
            job_count=count,
            hit_count=0,
            documents=paged,
            hits=[],
            page=page,
            page_size=page_size,
        )
    hits = retrieve(jobs, query, limit=MAX_HITS)
    known = {job.id: job for job in jobs if job_has_knowledge_text(job)}
    matched: list[KnowledgeDoc] = []
    seen: set[str] = set()
    for hit in hits:
        job = known.get(hit.job_id)
        if job is None or hit.job_id in seen:
            continue
        seen.add(hit.job_id)
        matched.append(_doc(job))
    return KnowledgeSearchOut(
        query=query,
        job_count=len(matched),
        hit_count=len(hits),
        documents=_page_items(matched, page, page_size),
        hits=hits,
        page=page,
        page_size=page_size,
    )


def _page_items(items: list, page: int, page_size: int):
    start = (page - 1) * page_size
    return items[start : start + page_size]


def retrieve(jobs: list[Job], query: str, limit: int = MAX_CHAT_CHUNKS) -> list[KnowledgeHit]:
    query = to_simplified(query).strip()
    if not query:
        return []
    lowered = query.casefold()
    terms = [term.casefold() for term in _terms(query)]
    ranked: list[tuple[float, _Chunk]] = []
    for job in jobs:
        if not job_has_knowledge_text(job):
            continue
        for chunk in chunk_index(job):
            score = _score(chunk, lowered, terms)
            if score > 0:
                ranked.append((score, chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    hits: list[KnowledgeHit] = []
    for _rank, chunk in ranked[:limit]:
        kind_label = KIND_LABELS.get(chunk.kind, chunk.kind)
        if chunk.kind == "transcript" and chunk.locator:
            kind_label = "正文"
        hits.append(
            KnowledgeHit(
                job_id=chunk.job_id,
                title=chunk.title,
                kind=chunk.kind,
                kind_label=kind_label,
                text=chunk.text,
                snippet=_snippet(chunk.text, query, terms),
                start=chunk.start,
                end=chunk.end,
                segment_id=chunk.segment_id,
                locator=chunk.locator,
            )
        )
    return hits


def answer_from_knowledge(
    jobs: list[Job],
    messages: list[dict],
    settings: AppSettingsOut,
    completer=None,
    domain_id: str | None = None,
) -> tuple[str, list[KnowledgeHit]]:
    if not settings.summarize_api_key:
        raise KnowledgeError("未配置总结 API Key。知识库对话复用设置里的总结模型，请先到设置页填写。")
    cleaned: list[dict] = []
    for item in messages[-12:]:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            cleaned.append({"role": role, "content": content})
    if not cleaned or cleaned[-1]["role"] != "user":
        raise KnowledgeError("请输入要问的问题")
    question = cleaned[-1]["content"]
    prior = " ".join(item["content"] for item in cleaned[-3:] if item["role"] == "user")
    scoped = jobs_in_domain(jobs, domain_id)
    citations = retrieve(scoped, prior or question, limit=MAX_CHAT_CHUNKS)
    if not citations:
        return "知识库里没有找到和这个问题相关的转写或文档。可以换个问法，或先完成更多任务。", []
    context = _format_context(citations)
    payload = [
        {
            "role": "system",
            "content": knowledge_system(pack_by_id(domain_id)) + "\n\n【资料】\n" + context,
        },
        *cleaned,
    ]
    fn = completer or complete_knowledge_answer
    answer = fn(settings, payload)
    return answer.strip(), citations


def complete_knowledge_answer(settings: AppSettingsOut, messages: list[dict]) -> str:
    client = openai_client(settings.summarize_api_key, settings.summarize_base_url)
    kwargs: dict = {
        "model": settings.summarize_model or "deepseek-v4-flash",
        "temperature": 0.3,
        "messages": messages,
    }
    try:
        response = create_chat_completion(client, **kwargs)
    except Exception as exc:
        raise KnowledgeError(f"知识库对话调用失败：{exc}") from exc
    return coerce_model_text(response.choices[0].message.content)


def _doc(job: Job) -> KnowledgeDoc:
    segments = loads(job.transcript_json, [])
    preview_parts: list[str] = []
    for item in segments:
        text = str(item.get("text") or "").strip()
        if text:
            preview_parts.append(text)
        if sum(len(part) for part in preview_parts) >= 80:
            break
    preview = "".join(preview_parts)
    if len(preview) > 80:
        preview = preview[:80] + "…"
    return KnowledgeDoc(
        job_id=job.id,
        title=job.title or "未命名任务",
        source_url=job.source_url or "",
        status=job.status,
        segment_count=len(segments) if isinstance(segments, list) else 0,
        updated_at=job.updated_at,
        preview=preview,
    )


def _chunks_for_job(job: Job) -> list[_Chunk]:
    title = job.title or "未命名任务"
    chunks: list[_Chunk] = [
        _Chunk(job_id=job.id, title=title, kind="title", text=title),
    ]
    segments = loads(job.transcript_json, [])
    window: list[dict] = []
    chars = 0
    for item in segments:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        window.append(item)
        chars += len(text)
        if chars >= 180 or len(window) >= 5:
            chunks.append(_window_chunk(job.id, title, window))
            window = window[-1:]
            chars = len(str(window[0].get("text") or ""))
    if window:
        chunks.append(_window_chunk(job.id, title, window))
    summary = loads(job.summary_json, {}) if job.summary_json else {}
    if isinstance(summary, dict):
        overview = str(summary.get("overview") or "").strip()
        if overview:
            chunks.append(_Chunk(job_id=job.id, title=title, kind="overview", text=overview))
        for chapter in summary.get("chapters") or []:
            bullets = chapter.get("bullets") or []
            body = " ".join([str(chapter.get("title") or ""), *[str(item) for item in bullets]]).strip()
            if body:
                chunks.append(
                    _Chunk(
                        job_id=job.id,
                        title=title,
                        kind="chapter",
                        text=body,
                        start=float(chapter.get("start") or 0),
                        end=float(chapter.get("end") or 0),
                        locator=str(chapter.get("locator") or ""),
                    )
                )
        for point in summary.get("key_points") or []:
            text = str(point.get("text") or "").strip()
            if text:
                chunks.append(
                    _Chunk(
                        job_id=job.id,
                        title=title,
                        kind="key_point",
                        text=text,
                        start=float(point.get("start") or 0),
                        end=float(point.get("end") or 0),
                        locator=str(point.get("locator") or ""),
                    )
                )
    return chunks


def _window_chunk(job_id: str, title: str, window: list[dict]) -> _Chunk:
    text = "".join(str(item.get("text") or "") for item in window).strip()
    return _Chunk(
        job_id=job_id,
        title=title,
        kind="transcript",
        text=text,
        start=float(window[0].get("start") or 0),
        end=float(window[-1].get("end") or 0),
        segment_id=window[0].get("id"),
        locator=str(window[0].get("locator") or ""),
    )


_INDEX_CACHE: OrderedDict[tuple, list[_Chunk]] = OrderedDict()
_INDEX_LOCK = threading.Lock()


def clear_chunk_index() -> None:
    """丢开切片索引缓存（内容变更后重建，测试之间隔离）。"""
    with _INDEX_LOCK:
        _INDEX_CACHE.clear()


def _index_key(job: Job) -> tuple:
    """缓存键：任务 ID + 更新时间 + 正文长度 + 标题，任一变化就重建索引。"""
    return (
        job.id,
        job.updated_at,
        len(job.transcript_json or ""),
        len(job.summary_json or ""),
        job.title or "",
    )


def _hay(chunk: _Chunk) -> str:
    return to_simplified(f"{chunk.title} {chunk.text}").casefold()


def chunk_index(job: Job) -> list[_Chunk]:
    """整场共用一份切片索引：命中缓存后不再重复解析 JSON、重复做繁简归一化。"""
    key = _index_key(job)
    with _INDEX_LOCK:
        cached = _INDEX_CACHE.get(key)
        if cached is not None:
            _INDEX_CACHE.move_to_end(key)
            return cached
    chunks = _chunks_for_job(job)
    for chunk in chunks:
        chunk.hay = _hay(chunk)
    with _INDEX_LOCK:
        _INDEX_CACHE[key] = chunks
        while len(_INDEX_CACHE) > MAX_INDEX_JOBS:
            _INDEX_CACHE.popitem(last=False)
    return chunks


def _terms(query: str) -> list[str]:
    terms: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9]{2,}|[\u4e00-\u9fff]+", query):
        if raw in STOP_WORDS:
            continue
        cleaned = "".join(ch for ch in raw if ch not in STOP_CHARS)
        if cleaned in STOP_WORDS or len(cleaned) < 2:
            continue
        terms.append(cleaned)
        if len(cleaned) >= 4:
            for index in range(len(cleaned) - 1):
                gram = cleaned[index : index + 2]
                if gram not in STOP_WORDS:
                    terms.append(gram)
    seen: set[str] = set()
    ordered: list[str] = []
    for item in terms:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _score(chunk: _Chunk, query: str, terms: list[str]) -> float:
    """只做子串命中统计；`query`、`terms` 与 `chunk.hay` 都已经是 casefold 后的形式。"""
    hay = chunk.hay or _hay(chunk)
    score = 0.0
    if query in hay:
        score += 8
    for term in terms:
        if term in hay:
            score += 2.5 if len(term) >= 3 else 1.2
    return score


def _snippet(text: str, query: str, terms: list[str], radius: int = 42) -> str:
    haystack = to_simplified(text)
    lowered = haystack.casefold()
    index = lowered.find(query.casefold())
    if index < 0:
        for term in sorted(terms, key=len, reverse=True):
            index = lowered.find(term.casefold())
            if index >= 0:
                break
    if index < 0:
        compact = text.replace("\n", " ").strip()
        return compact[: radius * 2] + ("…" if len(compact) > radius * 2 else "")
    start = max(0, index - radius)
    end = min(len(text), index + max(len(query), 2) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end].replace("\n", " ") + suffix


def _format_context(hits: list[KnowledgeHit]) -> str:
    parts: list[str] = []
    used = 0
    for index, hit in enumerate(hits, start=1):
        start = _place(hit)
        label = f"{hit.title} · {hit.kind_label}"
        if start:
            label = f"{label} · {start}"
        block = f"[{index}] {label}\n{hit.text.strip()}"
        if used + len(block) > MAX_CONTEXT_CHARS:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


def _place(hit: KnowledgeHit) -> str:
    if (hit.locator or "").strip():
        return hit.locator.strip()
    if hit.start or hit.end:
        return _clock(hit.start)
    return ""


def _clock(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
