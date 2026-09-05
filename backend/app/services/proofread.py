from app.schemas import AppSettingsOut, TranscriptSegment
from app.services.cancel import raise_if_cancelled
from app.services.domain import proofread_system
from app.services.httpclient import create_chat_completion, openai_client
from app.services.jsonutil import coerce_model_text, parse_model_json
from app.services.lexicon import PinyinTermIndex, pinyin_candidates, pinyin_term_index, remember_proofread
from app.services.textnorm import normalize_transcript
from app.services.timeline import indexed_transcript

# 只把「带近音候选」的段送给模型；每批最多这么多段
LLM_PROOFREAD_CHUNK_SIZE = 100
LLM_PROOFREAD_TIMEOUT = 60.0


def proofread_transcript(
    segments: list[TranscriptSegment],
    settings: AppSettingsOut,
    use_llm: bool = False,
) -> list[TranscriptSegment]:
    normalized = [
        item.model_copy(update={"text": normalize_transcript(item.text)})
        for item in segments
    ]
    if not use_llm or not normalized or not settings.summarize_api_key:
        return normalized
    try:
        revised, applied = _llm_proofread(normalized, settings)
        remember_proofread(normalized, revised, pairs=applied)
        return [
            item.model_copy(update={"text": normalize_transcript(item.text)})
            for item in revised
        ]
    except Exception:
        return normalized


def _segment_candidates(text: str, index: PinyinTermIndex, pinyin_cache: dict[str, str]) -> dict[str, list[str]]:
    return {src: dests for src, dests in pinyin_candidates(text, index=index, pinyin_cache=pinyin_cache)}


def _format_chunk(chunk: list[tuple[TranscriptSegment, dict[str, list[str]]]]) -> str:
    parts = [indexed_transcript([item for item, _cands in chunk]), "", "候选（只能从这里选）："]
    for item, cands in chunk:
        listed = "；".join(f"{src} → {' / '.join(dests)}" for src, dests in cands.items())
        parts.append(f"#{item.id} {listed}")
    return "\n".join(parts)


def _apply_allowed_edits(text: str, src: str, dst: str) -> str:
    if not src or not dst or src == dst or src not in text:
        return text
    return text.replace(src, dst)


def _parse_edits(payload: dict) -> list[tuple[int, str, str]]:
    rows: list[tuple[int, str, str]] = []
    for item in payload.get("edits") or []:
        if not isinstance(item, dict):
            continue
        try:
            seg_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        src = str(item.get("from") or "").strip()
        dst = str(item.get("to") or "").strip()
        if src and dst:
            rows.append((seg_id, src, dst))
    return rows


def _llm_proofread(segments: list[TranscriptSegment], settings: AppSettingsOut) -> tuple[list[TranscriptSegment], list[tuple[str, str]]]:
    client = openai_client(settings.summarize_api_key, settings.summarize_base_url, timeout=LLM_PROOFREAD_TIMEOUT)
    by_id = {item.id: item for item in segments}
    index = pinyin_term_index()
    pinyin_cache: dict[str, str] = {}
    pending: list[tuple[TranscriptSegment, dict[str, list[str]]]] = []
    for item in segments:
        cands = _segment_candidates(item.text, index, pinyin_cache)
        if cands:
            pending.append((item, cands))
    applied: list[tuple[str, str]] = []
    for start in range(0, len(pending), LLM_PROOFREAD_CHUNK_SIZE):
        raise_if_cancelled()
        chunk = pending[start : start + LLM_PROOFREAD_CHUNK_SIZE]
        allowed = {item.id: cands for item, cands in chunk}
        kwargs: dict = {
            "model": settings.summarize_model or "deepseek-v4-flash",
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": proofread_system()},
                {"role": "user", "content": _format_chunk(chunk)},
            ],
            "response_format": {"type": "json_object"},
        }
        response = create_chat_completion(client, **kwargs)
        payload = parse_model_json(coerce_model_text(response.choices[0].message.content))
        for seg_id, src, dst in _parse_edits(payload):
            dests = allowed.get(seg_id, {}).get(src) or []
            if dst not in dests:
                continue
            original = by_id.get(seg_id)
            if original is None:
                continue
            updated = _apply_allowed_edits(original.text, src, dst)
            if updated == original.text:
                continue
            by_id[seg_id] = original.model_copy(update={"text": updated})
            applied.append((src, dst))
    return [by_id[item.id] for item in segments], applied
