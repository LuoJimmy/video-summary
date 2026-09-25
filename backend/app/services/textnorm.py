from app.services.domain import asr_hint_prefix
from app.services.lexicon import apply_lexicon, known_terms, known_terms_hint

YAO_CHAR = "幺"
MO_CHAR = "么"


def whisper_hint(max_terms: int = 80) -> str:
    terms = known_terms_hint() if max_terms <= 0 else "、".join(known_terms()[:max_terms])
    prefix = asr_hint_prefix()
    if not terms:
        return prefix
    return prefix + "用词包括" + terms + "。"


def _convert_once(text: str) -> str:
    """单趟繁简转换。zhconv 的短语表会把「么半」这类词误转成「幺半」，这里按位还原成「么」。"""
    from zhconv import convert

    out = convert(text, "zh-cn")
    if YAO_CHAR not in out or len(out) != len(text):
        return out
    return "".join(
        MO_CHAR if before == MO_CHAR and after == YAO_CHAR else after for before, after in zip(text, out)
    )


def to_simplified(text: str) -> str:
    """繁简归一化，迭代到不动点。

    zhconv 单趟转换不幂等（「為什麼」先变「为什么」、再变「为什幺」），于是「為什麼半年」和
    「为什么半年」会得到两种写法。这里反复转换到稳定，保证同一句话的繁简写法结果一致，
    也更适合做检索键（可以反复调用）。
    """
    if not text:
        return ""
    try:
        out = _convert_once(text)
        if out == text:
            return out  # 已经是简体，不必再转一趟（正文占绝大多数，省掉一半开销）
        for _ in range(2):
            again = _convert_once(out)
            if again == out:
                break
            out = again
        return out
    except Exception:
        return text


def match_key(text: str) -> str:
    """检索用的归一化键：繁简收敛 + 统一「幺/么」+ 小写。

    早期版本把「那么半年」写成了「那幺半年」，统一「幺/么」后老数据不必清洗也能被搜到。
    """
    return to_simplified(text).replace(YAO_CHAR, MO_CHAR).casefold()


def fix_asr_glossary(text: str) -> str:
    return apply_lexicon(text)


def normalize_transcript(text: str) -> str:
    return apply_lexicon(to_simplified(text))

