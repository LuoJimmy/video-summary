import re

_LETTER_RE = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LEVEL_TAIL = re.compile(r"[ⅠⅡⅢⅣⅤⅥ]+$")
_SCREEN_RE = re.compile(r"中报|年报|季报|预增|预减|扭亏|首亏")
_BOARD_SUFFIX = re.compile(r"(?:概念|板块)$")


def ashare_short_name(name: str) -> str:
    """证券简称：去掉字母后，三个汉字保留，超过三个字取前两字。不足两字则空串。"""
    chars = _CJK_RE.findall(_LETTER_RE.sub("", name or ""))
    size = len(chars)
    if size >= 4:
        return "".join(chars[:2])
    if size >= 2:
        return "".join(chars)
    return ""


def unique_ashare_short_names(names: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for name in names:
        short = ashare_short_name(name)
        if short:
            seen[short] = None
    return tuple(seen)


def _usable_board(name: str) -> bool:
    if not name or _SCREEN_RE.search(name):
        return False
    return len(_CJK_RE.findall(name)) >= 2


def board_lexicon_terms(name: str) -> tuple[str, ...]:
    """板块/题材名：去掉申万层级记号，保留全称；带「概念」「板块」后缀时再收词干。"""
    cleaned = _LEVEL_TAIL.sub("", (name or "").strip()).replace("_", "")
    terms: dict[str, None] = {}
    if _usable_board(cleaned):
        terms[cleaned] = None
    stem = _BOARD_SUFFIX.sub("", cleaned)
    if stem != cleaned and _usable_board(stem):
        terms[stem] = None
    return tuple(terms)


def unique_board_names(names: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for name in names:
        for term in board_lexicon_terms(name):
            seen[term] = None
    return tuple(seen)
