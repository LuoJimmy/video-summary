from app.services.domain import asr_hint_prefix
from app.services.lexicon import apply_lexicon, known_terms, known_terms_hint


def whisper_hint(max_terms: int = 80) -> str:
    terms = known_terms_hint() if max_terms <= 0 else "、".join(known_terms()[:max_terms])
    prefix = asr_hint_prefix()
    if not terms:
        return prefix
    return prefix + "用词包括" + terms + "。"


def to_simplified(text: str) -> str:
    if not text:
        return ""
    try:
        from zhconv import convert

        return convert(text, "zh-cn")
    except Exception:
        return text


def fix_asr_glossary(text: str) -> str:
    return apply_lexicon(text)


def normalize_transcript(text: str) -> str:
    return apply_lexicon(to_simplified(text))
