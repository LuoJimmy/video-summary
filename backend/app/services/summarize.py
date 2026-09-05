import json
import re
from concurrent.futures import ThreadPoolExecutor

from app.config import settings as app_settings
from app.schemas import AppSettingsOut, SummaryChapter, SummaryKeyPoint, SummaryResult, TranscriptSegment
from app.services.domain import ENGINE_CHAPTER_PROMPT as PROMPT
from app.services.domain import chapter_prompt, load_active_pack, overview_prompt
from app.services.cancel import JobCancelled, current_job_id, raise_if_cancelled
from app.services.httpclient import create_chat_completion, openai_client
from app.services.jsonutil import coerce_model_text, looks_like_json_payload, parse_model_json
from app.services.timeline import attach_timestamps, format_video_clock, indexed_transcript


class SummarizeError(RuntimeError):
    pass


class Summarizer:
    def summarize(self, segments: list[TranscriptSegment], settings: AppSettingsOut) -> SummaryResult:
        raise NotImplementedError


RETRY_PROMPT = "上次输出不是合法 JSON，可能被截断。请重新输出完整可解析的 JSON，只要 chapters 和 key_points，不要 title，不要 overview。chapters 1 到 3 个且不能为空；窗口很短时最多 1 章；每个 bullets 3 到 5 条；key_points 不超过 6 条。start_segment/end_segment 必须是已有编号。严格忠于原文，不要编造。"
OVERVIEW_RETRY_PROMPT = "上次输出不是合法 JSON，或 overview 没写完。请重新输出完整可解析的 JSON：只要 title 和 overview。overview 必须含写满的「一句话总结」、主题与核心观点表三行、「论证结构」（顶层 3 到 6 个 ### 板块；相邻同主题合并；一块内容多再拆 2 到 5 个小节）以及「辨立场」。不要输出 chapters 或 key_points。禁止省略号和半截表格。严格忠于原文，不要编造。"
HOLLOW_RETRY_PROMPT = "上次 overview 只剩标题、省略号或半截表格，没有写完。请重新输出完整 JSON：title 加上写满的 overview。必须含一句话总结、主题表三行、论证结构、辨立场。禁止用 ...、……、「格式见下」代替正文。不要把 Markdown 写在 JSON 外面。"

_HEADING_LINE = re.compile(r"^#{1,4}\s+.*$", flags=re.M)
_ELLIPSIS = re.compile(r"(?:\.{2,}|…+)")
_TABLE_SEP = re.compile(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?$")
_TABLE_HEADER = re.compile(r"^\|\s*(?:维度\s*\|\s*内容|事件时间\s*\|\s*关键事件\s*\|\s*含义)\s*\|$")
_THINKING_MARKERS = (
    "构建 overview",
    "这是 JSON 对象",
    "需要把整段作为 JSON",
    "这样字符串内包含",
    "这个 overview 相当长",
)
_OVERVIEW_START = "## 一句话总结"
_OVERVIEW_STANCE = "## 辨立场"


def title_is_blank(title: str) -> bool:
    raw = (title or "").strip()
    if not raw:
        return True
    if raw in {".", "..", "...", "……"}:
        return True
    return bool(_ELLIPSIS.fullmatch(raw))


def extract_overview_document(text: str) -> str:
    raw = (text or "").replace("\\n", "\n").strip()
    if not raw:
        return ""
    start = raw.find(_OVERVIEW_START)
    if start < 0:
        return raw
    body = raw[start:]
    stance = body.find(_OVERVIEW_STANCE)
    if stance < 0:
        return body.strip()
    rest = body[stance + len(_OVERVIEW_STANCE) :]
    cut = len(rest)
    for marker in _THINKING_MARKERS:
        idx = rest.find(marker)
        if 0 <= idx < cut:
            cut = idx
    return (body[: stance + len(_OVERVIEW_STANCE)] + rest[:cut]).strip()


def overview_is_hollow(text: str) -> bool:
    source = text or ""
    raw = extract_overview_document(source)
    if any(marker in source for marker in _THINKING_MARKERS) and not raw.startswith(_OVERVIEW_START):
        return True
    if len(raw) < 80:
        return True
    body = _HEADING_LINE.sub("", raw)
    lines = []
    for line in body.splitlines():
        trimmed = line.strip()
        if _TABLE_SEP.match(trimmed) or _TABLE_HEADER.match(trimmed):
            continue
        lines.append(trimmed)
    body = "\n".join(lines)
    cjk = re.findall(r"[\u4e00-\u9fff]", body)
    if len(cjk) < 80:
        return True
    leftover_cjk = re.findall(r"[\u4e00-\u9fff]", _ELLIPSIS.sub("", body))
    return len(leftover_cjk) < 80


def _table_row_filled(text: str, label: str) -> bool:
    match = re.search(rf"\|\s*{re.escape(label)}\s*\|([^|\n]*)\|", text)
    if not match:
        return False
    cell = _ELLIPSIS.sub("", (match.group(1) or "").strip())
    return len(re.findall(r"[\u4e00-\u9fff]", cell)) >= 2


def overview_is_incomplete(text: str) -> bool:
    """综述缺结构或主题表没写完，包括截断在「核心观点」处的残稿。"""
    if overview_is_hollow(text):
        return True
    raw = extract_overview_document(text)
    if "## 论证结构" not in raw or _OVERVIEW_STANCE not in raw:
        return True
    if "## 主题与核心观点" not in raw:
        return True
    if not (_table_row_filled(raw, "主题") and _table_row_filled(raw, "核心观点") and _table_row_filled(raw, "手段")):
        return True
    stance = raw.split(_OVERVIEW_STANCE, 1)[-1]
    return len(re.findall(r"[\u4e00-\u9fff]", stance)) < 30


def title_from_overview(overview: str) -> str:
    raw = extract_overview_document(overview)
    match = re.search(r"一句话总结\s*\n+\*\*(.+?)\*\*", raw, flags=re.S)
    if not match:
        return ""
    text = re.sub(r"\s+", "", match.group(1))
    if title_is_blank(text):
        return ""
    return text[:40]


_HEAD_CHATTER = re.compile(
    r"(听得到|听得见|进不去直播|直播间|能看到我|晚上好|大家好|稍等一下|麦克风)",
    flags=re.I,
)
_TAIL_CHATTER = re.compile(r"(再见|拜拜|bye\b|周三见)", flags=re.I)


def _content_hint_pattern():
    words = [item.strip() for item in load_active_pack().content_keywords if item and item.strip()]
    if not words:
        return None
    return re.compile("(" + "|".join(re.escape(word) for word in words) + ")")


def _is_head_chatter(text: str) -> bool:
    raw = (text or "").strip()
    if bullet_is_hollow(raw):
        return True
    hint = _content_hint_pattern()
    if hint and hint.search(raw):
        return False
    return bool(_HEAD_CHATTER.search(raw))


def _is_tail_chatter(text: str) -> bool:
    raw = (text or "").strip()
    if bullet_is_hollow(raw):
        return True
    hint = _content_hint_pattern()
    if hint and hint.search(raw):
        return False
    return bool(_TAIL_CHATTER.search(raw))


def segments_for_summarize(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """送给总结模型用：丢掉纯语气词，裁掉片头寒暄和片尾道别。库内原文不动。"""
    items = [item for item in segments if not bullet_is_hollow(item.text)]
    while items and _is_head_chatter(items[0].text):
        items = items[1:]
    while items and _is_tail_chatter(items[-1].text):
        items = items[:-1]
    return items


def fallback_overview(
    chapters: list[SummaryChapter],
    points: list[SummaryKeyPoint],
    segments: list[TranscriptSegment],
) -> str:
    timed = attach_timestamps(SummaryResult(chapters=chapters, key_points=points), segments)
    one = ""
    if timed.key_points:
        one = timed.key_points[0].text.strip()
    if not one:
        for chapter in timed.chapters:
            if chapter.bullets:
                one = chapter.bullets[0].strip()
                break
    if not one:
        one = "本场按转写章节归纳，未另写综述。"
    theme = "；".join(item.title for item in timed.chapters[:5]) or "未注明"
    view = "；".join(item.text.strip() for item in timed.key_points[:3] if item.text.strip()) or "未注明"
    lines = [
        "## 一句话总结",
        f"**{one}**",
        "",
        "## 主题与核心观点",
        "| 维度 | 内容 |",
        "|---|---|",
        f"| 主题 | {theme} |",
        f"| 核心观点 | {view} |",
        "| 手段 | 未注明 |",
        "",
        "## 论证结构",
    ]
    if not timed.chapters:
        lines.append("未注明。")
    elif len(timed.chapters) <= 5:
        numerals = "一二三四五"
        for index, chapter in enumerate(timed.chapters):
            start = format_video_clock(chapter.start)
            end = format_video_clock(chapter.end)
            lines.append(f"### {numerals[index]}、{chapter.title}（约 {start}–{end}）")
            for bullet in chapter.bullets[:4]:
                lines.append(f"- {bullet}")
            if chapter.bullets:
                lines.append(f"核心结论：**{chapter.bullets[-1]}**")
            lines.append("")
    else:
        group_count = 4
        size = max(1, (len(timed.chapters) + group_count - 1) // group_count)
        numerals = "一二三四"
        for group_index, offset in enumerate(range(0, len(timed.chapters), size)):
            group = timed.chapters[offset : offset + size]
            start = format_video_clock(group[0].start)
            end = format_video_clock(group[-1].end)
            title = group[0].title if len(group) == 1 else f"{group[0].title}至{group[-1].title}"
            lines.append(f"### {numerals[group_index]}、{title}（约 {start}–{end}）")
            for nested, chapter in enumerate(group, start=1):
                nested_start = format_video_clock(chapter.start)
                nested_end = format_video_clock(chapter.end)
                lines.append(f"#### {nested}. {chapter.title}（约 {nested_start}–{nested_end}）")
                for bullet in chapter.bullets[:3]:
                    lines.append(f"- {bullet}")
                if chapter.bullets:
                    lines.append(f"该小节结论：**{chapter.bullets[-1]}**")
            lines.append("")
    stance = load_active_pack().disclaimer.strip() or "以上归纳仅来自本场转写，未引入外部资料。"
    extras = [item.text.strip() for item in timed.key_points[-2:] if item.text.strip()]
    if extras:
        stance = f"{'；'.join(extras)} {stance}"
    lines.extend(["## 辨立场", stance])
    return "\n".join(lines).strip()


def _chunk_segments(
    segments: list[TranscriptSegment],
    max_chars: int = 3500,
    max_seconds: float = 600,
) -> list[list[TranscriptSegment]]:
    chunks: list[list[TranscriptSegment]] = []
    current: list[TranscriptSegment] = []
    size = 0
    for segment in segments:
        text_len = len(segment.text)
        span = (segment.end - current[0].start) if current else 0
        too_long = current and (size + text_len > max_chars or span > max_seconds)
        if too_long:
            chunks.append(current)
            current = [segment]
            size = text_len
        else:
            current.append(segment)
            size += text_len
    if current:
        chunks.append(current)
    return chunks


def _summary_from_payload(payload: dict) -> SummaryResult:
    chapters: list[SummaryChapter] = []
    for item in payload.get("chapters") or []:
        if not isinstance(item, dict):
            continue
        bullets = item.get("bullets") or []
        if isinstance(bullets, str):
            bullets = [bullets]
        try:
            start_segment = int(item.get("start_segment") or 0)
            end_segment = int(item.get("end_segment") if item.get("end_segment") is not None else start_segment)
        except (TypeError, ValueError):
            continue
        chapters.append(
            SummaryChapter(
                title=str(item.get("title") or "章节").strip() or "章节",
                start_segment=start_segment,
                end_segment=end_segment,
                bullets=[str(bullet).strip() for bullet in bullets if str(bullet).strip()],
            )
        )
    points: list[SummaryKeyPoint] = []
    for item in payload.get("key_points") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        try:
            start_segment = int(item.get("start_segment") or 0)
            end_segment = int(item.get("end_segment") if item.get("end_segment") is not None else start_segment)
        except (TypeError, ValueError):
            continue
        points.append(SummaryKeyPoint(text=text, start_segment=start_segment, end_segment=end_segment))
    title = str(payload.get("title") or "").strip()
    if title_is_blank(title):
        title = ""
    overview = extract_overview_document(str(payload.get("overview") or ""))
    return SummaryResult(
        title=title,
        overview=overview,
        chapters=chapters,
        key_points=points,
    )


def stitch_partials(partials: list[SummaryResult]) -> tuple[list[SummaryChapter], list[SummaryKeyPoint]]:
    chapters: list[SummaryChapter] = []
    points: list[SummaryKeyPoint] = []
    for item in partials:
        chapters.extend(item.chapters)
        points.extend(item.key_points)
    chapters.sort(key=lambda item: (item.start_segment, item.end_segment))
    points.sort(key=lambda item: (item.start_segment, item.end_segment))
    return chapters, points


_FILLER_LINE = re.compile(
    r"^(嗯+|啊+|哦+|好+|讲|对吧|对不对|是不是|yes|yeah|oh)[。.?？!！]*$",
    flags=re.IGNORECASE,
)


def bullet_is_hollow(text: str) -> bool:
    raw = (text or "").strip()
    if not raw or _FILLER_LINE.match(raw):
        return True
    return len(re.findall(r"[\u4e00-\u9fff]", raw)) < 8


def _segments_in_range(segments: list[TranscriptSegment], start_id: int, end_id: int) -> list[TranscriptSegment]:
    lo, hi = min(start_id, end_id), max(start_id, end_id)
    return [item for item in segments if lo <= item.id <= hi]


def bullets_from_segments(segments: list[TranscriptSegment], max_bullets: int = 5) -> list[str]:
    packed: list[str] = []
    buf = ""
    for item in segments:
        piece = re.sub(r"\s+", "", (item.text or "").strip())
        if not piece or _FILLER_LINE.match(piece):
            continue
        buf += piece
        cjk = len(re.findall(r"[\u4e00-\u9fff]", buf))
        if buf.endswith(("。", "！", "？", "?", "!")) or cjk >= 36:
            if cjk >= 8:
                packed.append(buf)
            buf = ""
    if len(re.findall(r"[\u4e00-\u9fff]", buf)) >= 8:
        packed.append(buf)
    if not packed:
        return []
    while len(packed) > max_bullets and len(re.findall(r"[\u4e00-\u9fff]", packed[0])) < 18:
        packed = packed[1:]
    return packed[:max_bullets]


def repair_chapters(chapters: list[SummaryChapter], segments: list[TranscriptSegment]) -> list[SummaryChapter]:
    if not segments:
        return chapters
    filled: list[SummaryChapter] = []
    for chapter in chapters:
        bullets = [item for item in chapter.bullets if not bullet_is_hollow(item)]
        if not bullets:
            window = _segments_in_range(segments, chapter.start_segment, chapter.end_segment)
            bullets = bullets_from_segments(window)
        if not bullets:
            continue
        filled.append(chapter.model_copy(update={"bullets": bullets}))
    filled.sort(key=lambda item: (item.start_segment, item.end_segment))
    return filled


def local_partial(segments: list[TranscriptSegment]) -> SummaryResult:
    if not segments:
        return SummaryResult()
    chapters: list[SummaryChapter] = []
    points: list[SummaryKeyPoint] = []
    bucket: list[TranscriptSegment] = []
    start_id = 0
    for segment in segments:
        if not bucket:
            start_id = segment.id
        bucket.append(segment)
        span = segment.end - bucket[0].start
        last = segment.id == segments[-1].id
        if span >= 45 or last:
            usable = [item for item in bucket if not bullet_is_hollow(item.text)]
            bullets = [item.text.strip() for item in usable[:5]]
            if not bullets:
                bullets = bullets_from_segments(bucket)
            if bullets:
                title = re.sub(r"\s+", "", bullets[0])[:18] or f"片段 {start_id}"
                chapters.append(
                    SummaryChapter(
                        title=title,
                        start_segment=start_id,
                        end_segment=bucket[-1].id,
                        bullets=bullets,
                    )
                )
                longest = max(usable or bucket, key=lambda item: len(item.text or ""))
                if not bullet_is_hollow(longest.text):
                    points.append(
                        SummaryKeyPoint(
                            text=longest.text.strip(),
                            start_segment=longest.id,
                            end_segment=longest.id,
                        )
                    )
            bucket = []
    return SummaryResult(chapters=chapters, key_points=points[:8])


def _summarize_concurrency(settings: AppSettingsOut | None = None) -> int:
    raw = getattr(settings, "summarize_concurrency", None) if settings is not None else None
    if raw is None:
        raw = getattr(app_settings, "summarize_concurrency", 3)
    try:
        value = int(raw or 3)
    except (TypeError, ValueError):
        value = 3
    return max(1, min(value, 8))


_MAX_OVERVIEW_POINTS = 12


def _overview_context(
    chapters: list[SummaryChapter],
    points: list[SummaryKeyPoint],
    segments: list[TranscriptSegment],
) -> str:
    timed = attach_timestamps(SummaryResult(chapters=chapters, key_points=points), segments)
    clocks: list[str] = []
    for item in timed.chapters:
        clocks.append(format_video_clock(item.start))
        clocks.append(format_video_clock(item.end))
    for item in timed.key_points[:_MAX_OVERVIEW_POINTS]:
        clocks.append(format_video_clock(item.start))
    allowed = list(dict.fromkeys(clocks))
    return json.dumps(
        {
            "clock_note": "start/end 是音视频播放位置，格式 hh:mm:ss。00:09:29 表示片子第 9 分 29 秒，不是开盘 9:29。",
            "allowed_video_clocks": allowed,
            "chapters": [
                {
                    "title": item.title,
                    "start": format_video_clock(item.start),
                    "end": format_video_clock(item.end),
                    "start_segment": item.start_segment,
                    "end_segment": item.end_segment,
                    "bullets": item.bullets[:3],
                }
                for item in timed.chapters
            ],
            "key_points": [
                {
                    "text": item.text,
                    "start": format_video_clock(item.start),
                    "start_segment": item.start_segment,
                    "end_segment": item.end_segment,
                }
                for item in timed.key_points[:_MAX_OVERVIEW_POINTS]
            ],
        },
        ensure_ascii=False,
    )


class OpenAICompatibleSummarizer(Summarizer):
    def summarize(self, segments: list[TranscriptSegment], settings: AppSettingsOut) -> SummaryResult:
        if not settings.summarize_api_key:
            raise SummarizeError("未配置总结 API Key")
        if not segments:
            raise SummarizeError("没有可总结的转写分段")

        usable = segments_for_summarize(segments) or segments
        chunks = _chunk_segments(usable)
        job_id = current_job_id()
        partials = self._summarize_chunks(chunks, settings, job_id)
        chapters, points = stitch_partials(partials)
        chapters = repair_chapters(chapters, segments)
        overview_input = _overview_context(chapters, points, segments)
        raise_if_cancelled(job_id)
        title = ""
        overview = ""
        client = openai_client(settings.summarize_api_key, settings.summarize_base_url)
        try:
            meta = self._complete(client, settings, overview_prompt(), overview_input, require_filled_overview=True)
            title = meta.title
            overview = meta.overview
        except SummarizeError:
            overview = fallback_overview(chapters, points, segments)
        if title_is_blank(title):
            title = title_from_overview(overview) or "本场总结"
        if overview_is_incomplete(overview):
            overview = fallback_overview(chapters, points, segments)
            if title_is_blank(title) or title == "本场总结":
                title = title_from_overview(overview) or "本场总结"
        summary = SummaryResult(
            title=title,
            overview=overview,
            chapters=chapters,
            key_points=points,
        )
        return attach_timestamps(summary, segments)

    def _summarize_chunks(
        self,
        chunks: list[list[TranscriptSegment]],
        settings: AppSettingsOut,
        job_id: str | None,
    ) -> list[SummaryResult]:
        workers = min(_summarize_concurrency(settings), len(chunks))

        def run_one(chunk: list[TranscriptSegment]) -> SummaryResult:
            raise_if_cancelled(job_id)
            client = openai_client(settings.summarize_api_key, settings.summarize_base_url)
            try:
                return self._complete(client, settings, chapter_prompt(), indexed_transcript(chunk), require_chapters=True)
            except JobCancelled:
                raise
            except SummarizeError:
                return local_partial(chunk)

        if workers == 1:
            return [run_one(chunk) for chunk in chunks]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(run_one, chunk) for chunk in chunks]
            partials: list[SummaryResult] = []
            for future in futures:
                raise_if_cancelled(job_id)
                partials.append(future.result())
            return partials

    def _parse_summary(self, content: str) -> SummaryResult | None:
        try:
            return _summary_from_payload(parse_model_json(content))
        except Exception:
            return None

    def _accept_summary(
        self,
        summary: SummaryResult | None,
        require_chapters: bool,
        require_filled_overview: bool = False,
    ) -> SummaryResult | None:
        if summary is None:
            return None
        if require_chapters and not summary.chapters:
            return None
        if require_filled_overview and overview_is_incomplete(summary.overview):
            return None
        return summary

    def _complete(
        self,
        client,
        settings: AppSettingsOut,
        system: str,
        user_content: str,
        require_filled_overview: bool = False,
        require_chapters: bool = False,
    ) -> SummaryResult:
        if require_filled_overview:
            retry_hint = OVERVIEW_RETRY_PROMPT
        else:
            retry_hint = RETRY_PROMPT
        content = self._chat(client, settings, system, user_content)
        summary = self._accept_summary(self._parse_summary(content), require_chapters, require_filled_overview)
        if summary is not None:
            return summary
        content = self._chat(client, settings, system, f"{user_content}\n\n{retry_hint}")
        retried = self._accept_summary(self._parse_summary(content), require_chapters, require_filled_overview)
        if retried is not None:
            return retried
        if not (content or "").strip():
            raise SummarizeError("总结模型返回空内容，请稍后重试")
        preview = re.sub(r"\s+", " ", (content or "")[:80]).strip()
        hint = f"；原文开头：{preview}" if preview else ""
        if require_chapters:
            raise SummarizeError(f"分段总结缺少 chapters{hint}")
        if require_filled_overview:
            raise SummarizeError(f"综述未写完{hint}")
        raise SummarizeError(f"总结结果不是合法 JSON{hint}")

    def _message_text(self, message) -> str:
        content = coerce_model_text(getattr(message, "content", None))
        reasoning = coerce_model_text(getattr(message, "reasoning_content", None))
        if content:
            try:
                parse_model_json(content)
                return content
            except Exception:
                if looks_like_json_payload(content):
                    return content
        if reasoning:
            try:
                parse_model_json(reasoning)
                return reasoning
            except Exception:
                pass
        return content or reasoning

    def _chat(self, client, settings: AppSettingsOut, system: str, user_content: str) -> str:
        kwargs: dict = {
            "model": settings.summarize_model or "deepseek-v4-flash",
            "temperature": 0.2,
            "max_tokens": 8192,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            response = create_chat_completion(client, **kwargs)
        except JobCancelled:
            raise
        except Exception as exc:
            raise SummarizeError(f"总结接口调用失败：{exc}") from exc
        return self._message_text(response.choices[0].message)


class LocalFallbackSummarizer(Summarizer):
    def summarize(self, segments: list[TranscriptSegment], settings: AppSettingsOut) -> SummaryResult:
        if not segments:
            raise SummarizeError("没有可总结的转写分段")
        partial = local_partial(segments)
        overview = fallback_overview(partial.chapters, partial.key_points, segments)
        if overview_is_hollow(overview):
            overview = "。".join(item.text for item in segments[:4])[:200]
        summary = SummaryResult(
            title="本地提纲（未配置总结 API）",
            overview=overview,
            chapters=partial.chapters,
            key_points=partial.key_points[:6],
        )
        return attach_timestamps(summary, segments)


class AutoSummarizer(Summarizer):
    def summarize(self, segments: list[TranscriptSegment], settings: AppSettingsOut) -> SummaryResult:
        if settings.summarize_api_key:
            return OpenAICompatibleSummarizer().summarize(segments, settings)
        return LocalFallbackSummarizer().summarize(segments, settings)


def default_summarizer() -> Summarizer:
    return AutoSummarizer()
