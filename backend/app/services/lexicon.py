import json
import re
from pathlib import Path

from app.config import settings

# 只收正确词，不收错法。拼音对齐用这张表去靠。用户可在设置里改，改完以本地文件为准。
SEED_TERMS = (
    # 情绪与周期
    "负反馈",
    "正反馈",
    "情绪周期",
    "情绪冰点",
    "冰点",
    "核按钮",
    "分歧",
    "一致",
    "加速",
    "退潮",
    "高潮",
    "修复",
    "卡位",
    "抱团",
    "抱团股",
    "踩踏",
    "预期差",
    "证伪",
    "证实",
    "真空期",
    "窗口期",
    # 打板与连板
    "打板",
    "炸板",
    "回封",
    "连板",
    "首板",
    "二板",
    "三板",
    "四板",
    "五板",
    "高度板",
    "天地板",
    "地天板",
    "一字板",
    "一字涨停",
    "一字跌停",
    "开板",
    "封板",
    "排板",
    "晋级",
    "断板",
    "烂板",
    "弱转强",
    "卡位板",
    "反包",
    "反包板",
    "缩量板",
    "放量板",
    "换手板",
    "回封板",
    "实体板",
    "黄金坑",
    "晋级溢价",
    "断板溢价",
    "一字溢价",
    # 龙头主线
    "龙头",
    "总龙头",
    "日内龙",
    "空间龙",
    "中军",
    "旗手",
    "补涨",
    "跟风",
    "辨识度",
    "主线",
    "支线",
    "杂毛",
    "题材龙",
    "周期龙",
    "高标",
    "最高标",
    "前排",
    "后排",
    "中位",
    "中气",
    # 竞价盘口
    "竞价",
    "集合竞价",
    "高开",
    "低开",
    "平开",
    "高开低走",
    "低开高走",
    "开盘",
    "尾盘",
    "早盘",
    "午盘",
    "盘中",
    "盘面",
    "量能",
    "缩量",
    "放量",
    "天量",
    "地量",
    "换手",
    "换手率",
    "委比",
    "量比",
    "外盘",
    "内盘",
    "大单",
    "散户",
    "主力",
    "游资",
    "机构",
    "砸盘",
    "对倒",
    "洗盘",
    "出货",
    "吸筹",
    "封单",
    "封死",
    # 涨跌停与仓位
    "涨停",
    "跌停",
    "涨停板",
    "跌停板",
    "冲击涨停",
    "打开涨停",
    "回封涨停",
    "低吸",
    "高抛",
    "追高",
    "抄底",
    "左侧",
    "右侧",
    "接力",
    "套利",
    "做T",
    "超短",
    "短线",
    "波段",
    "中线",
    "长线",
    "反抽",
    "反弹",
    "反转",
    "回调",
    "调整",
    "回踩",
    "回撤",
    "复盘",
    "建仓",
    "加仓",
    "减仓",
    "清仓",
    "满仓",
    "空仓",
    "半仓",
    "底仓",
    "保底仓",
    "仓位",
    "割肉",
    "套牢",
    "解套",
    "止盈",
    "止损",
    "筹码",
    "成本区",
    # 形态与量价
    "突破",
    "假突破",
    "箱体",
    "震荡",
    "阴跌",
    "挖坑",
    "深水区",
    "浅水区",
    "水位",
    "溢价",
    "折价",
    "支撑",
    "压力位",
    "均线",
    "五日线",
    "十日线",
    "年线",
    "量价",
    "地量地价",
    "天量天价",
    # 风格题材
    "题材",
    "概念",
    "风口",
    "风格",
    "小票",
    "大票",
    "微盘股",
    "权重股",
    "白马股",
    "黑马",
    "妖股",
    "庄股",
    "次新",
    "次新股",
    "股性",
    "板块轮动",
    "热点",
    "核心资产",
    "中特估",
    "中字头",
    "国企改革",
    "并购重组",
    # 指数资金与制度
    "大盘",
    "沪指",
    "上证",
    "创业板",
    "科创板",
    "北交所",
    "两市",
    "成交额",
    "北向资金",
    "南向资金",
    "北向",
    "南向",
    "外资",
    "国家队",
    "两融",
    "融资",
    "融券",
    "杠杆",
    "配资",
    "量化",
    # 事件与黑话
    "利好",
    "利空",
    "利好出尽",
    "利空出尽",
    "超预期",
    "不及预期",
    "解禁",
    "减持",
    "增持",
    "回购",
    "定增",
    "重组",
    "借壳",
    "爆雷",
    "暴雷",
    "爆仓",
    "杀跌",
    "杀估值",
    "杀逻辑",
    "杀业绩",
    "博傻",
    "接盘",
    "接盘侠",
    "诱多",
    "诱空",
    "逼空",
    "多杀多",
    "龙虎榜",
    "席位",
    "一线游资",
    "涨停敢死队",
    "主战场",
    "大基金",
    # 常见板块与个股简称
    "白酒",
    "新能源",
    "光伏",
    "储能",
    "锂电",
    "算力",
    "人工智能",
    "机器人",
    "低空经济",
    "华为链",
    "军工",
    "有色",
    "煤炭",
    "券商",
    "地产",
    "中药",
    "创新药",
    "传媒",
    "游戏",
    "免税",
    "航运",
    "船舶",
    "哈药",
    "东百",
    "航天",
    "宝鼎",
    "茅台",
    "宁德",
    "比亚迪",
)

# 已知高频整句/整词，先做精确替换
SEED_FIXES = (
    ("覆反会不扩大", "负反馈不会太大"),
    ("负反馈不扩大", "负反馈不会太大"),
    ("每一次挑准", "每一次调整"),
    ("挑准都可以", "调整都可以"),
    ("覆反会", "负反馈"),
    ("负反会", "负反馈"),
    ("覆反馈", "负反馈"),
    ("正反会", "正反馈"),
    ("打版", "打板"),
    ("炸版", "炸板"),
    ("连版", "连板"),
    ("首版", "首板"),
    ("二版", "二板"),
    ("三版", "三板"),
    ("封版", "封板"),
    ("开版", "开板"),
    ("烂版", "烂板"),
    ("涨停版", "涨停板"),
    ("跌停版", "跌停板"),
    ("一字版", "一字板"),
    ("天地版", "天地板"),
    ("地天版", "地天板"),
    ("排面", "盘面"),
    ("覆盘", "复盘"),
    ("挑准", "调整"),
    ("笼头", "龙头"),
    ("棋手", "旗手"),
    ("低西", "低吸"),
    ("抄低", "抄底"),
    ("超底", "抄底"),
    ("套劳", "套牢"),
    ("止赢", "止盈"),
    ("筹马", "筹码"),
    ("弱转墙", "弱转强"),
    ("反苞", "反包"),
    ("高报", "高标"),
    ("和按钮", "核按钮"),
    ("核按纽", "核按钮"),
    ("核按键", "核按钮"),
    ("北乡资金", "北向资金"),
    ("南乡资金", "南向资金"),
    ("融卷", "融券"),
    ("哈亚", "哈药"),
    ("哈呀", "哈药"),
    ("韩天", "航天"),
    ("韩发", "航天"),
    ("东板", "东百"),
    ("好险", "好像"),
    ("交吸", "交易"),
)

FILLER_BAODING = re.compile(r"[啊阿AaａＡ]\s*保底")
NORTHEAST_STOCK = re.compile(r"东北(?!板块|振兴|三省|地区|经济|证券|制药|有色|虎|人|菜|话)")
CJK_CHAR = re.compile(r"[\u4e00-\u9fff]")
CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")

# 这些字面不宜做成全局精确替换
UNSAFE_SOURCES = {"东北", "保底"}

# 来源是日常词时，不要用拼音硬改成词表里的专名
COMMON_WORDS = {
    "这个",
    "那个",
    "我们",
    "可以",
    "不是",
    "就是",
    "还是",
    "因为",
    "所以",
    "如果",
    "但是",
    "然后",
    "今天",
    "明天",
    "现在",
    "市场",
    "资金",
    "情绪",
    "指数",
    "方向",
    "排版",
    "柚子",
    "腰鼓",
    "操作",
    "风险",
    "调整",
    "复盘",
    "盘面",
    "细微",
    "二十",
    "十八",
    "万物",
    "一直",
    "好像",
    "交易",
}

# 自动拼音只改「词缀是语气词」的窗口，避免「天地万物」被吃成「天地板」
CJK_PARTICLES = set("的了呢吗啊呀吧嘛有在是和与把被就都也还不很这那个又所让给到从对")

_path_override: Path | None = None
_root_override: Path | None = None


def set_lexicon_path(path: Path | None) -> None:
    global _path_override
    _path_override = path


def set_lexicon_root(path: Path | None) -> None:
    global _root_override
    _root_override = path


def _legacy_lexicon_path() -> Path:
    root = _root_override if _root_override is not None else settings.data_dir
    return root / "asr_lexicon.json"


def _preset_key(preset: str | None = None) -> str:
    from app.services.domain import lexicon_preset

    return lexicon_preset(preset)


def lexicon_path(preset: str | None = None) -> Path:
    if _path_override is not None:
        return _path_override
    target = _preset_key(preset)
    folder = (_root_override if _root_override is not None else settings.data_dir) / "domains" / target
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / "asr_lexicon.json"
    legacy = _legacy_lexicon_path()
    if target == "a-share" and not dest.exists() and legacy.exists():
        try:
            dest.write_bytes(legacy.read_bytes())
        except OSError:
            return legacy
    return dest


def _seed_terms(preset: str | None = None) -> tuple[str, ...]:
    from app.services.domain import uses_ashare_lexicon

    return SEED_TERMS if uses_ashare_lexicon(preset=preset) else ()


def _seed_fixes(preset: str | None = None) -> tuple[tuple[str, str], ...]:
    from app.services.domain import uses_ashare_lexicon

    return SEED_FIXES if uses_ashare_lexicon(preset=preset) else ()


def _pinyin(text: str) -> str:
    from pypinyin import Style, lazy_pinyin

    return "".join(lazy_pinyin(text, style=Style.NORMAL))


_index_cache: tuple[tuple[str, ...], "PinyinTermIndex"] | None = None


def _pinyin_dist_at_most(left: str, right: str, limit: int) -> int | None:
    """只算插入/删除/替换，不含换位；超过 limit 则返回 None。"""
    if left == right:
        return 0
    if limit <= 0:
        return None
    left_len, right_len = len(left), len(right)
    if abs(left_len - right_len) > limit:
        return None
    if left_len == right_len:
        dist = 0
        for a, b in zip(left, right):
            if a == b:
                continue
            dist += 1
            if dist > limit:
                return None
        return dist
    if left_len > right_len:
        left, right = right, left
    i = j = skipped = 0
    while i < len(left) and j < len(right):
        if left[i] == right[j]:
            i += 1
            j += 1
            continue
        skipped += 1
        if skipped > limit:
            return None
        j += 1
    skipped += len(right) - j
    if skipped > limit:
        return None
    return skipped


def _is_cjk_char(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def _is_cjk_text(text: str) -> bool:
    return bool(text) and all("\u4e00" <= ch <= "\u9fff" for ch in text)


class PinyinTermIndex:
    """词表按字数和全拼倒排，供近音查找复用。"""

    __slots__ = ("term_set", "by_len_set", "lengths", "by_pinyin", "by_prefix", "prefixes")

    def __init__(self, terms: list[str] | tuple[str, ...]):
        self.term_set = set(terms)
        self.by_len_set: dict[int, set[str]] = {}
        self.by_pinyin: dict[int, dict[str, list[str]]] = {}
        lengths: set[int] = set()
        for term in terms:
            if not (2 <= len(term) <= 6 and _is_cjk_text(term)):
                continue
            bucket = self.by_pinyin.setdefault(len(term), {})
            bucket.setdefault(_pinyin(term), []).append(term)
            self.by_len_set.setdefault(len(term), set()).add(term)
            lengths.add(len(term))
        self.lengths = sorted(lengths, reverse=True)
        self.by_prefix: dict[int, dict[str, tuple[str, ...]]] = {}
        self.prefixes: dict[int, tuple[str, ...]] = {}
        for size, bucket in self.by_pinyin.items():
            grouped: dict[str, list[str]] = {}
            for key in bucket:
                grouped.setdefault(key[:2], []).append(key)
            self.by_prefix[size] = {prefix: tuple(keys) for prefix, keys in grouped.items()}
            self.prefixes[size] = tuple(grouped)


def pinyin_term_index(terms: list[str] | None = None) -> PinyinTermIndex:
    """整场校对共用一份倒排；词表没变就复用。"""
    global _index_cache
    pool = tuple(terms if terms is not None else known_terms())
    if _index_cache is not None and _index_cache[0] == pool:
        return _index_cache[1]
    index = PinyinTermIndex(pool)
    _index_cache = (pool, index)
    return index


def _parse_terms(raw) -> list[str]:
    seen: dict[str, None] = {}
    for item in raw or []:
        term = str(item).strip()
        if term:
            seen[term] = None
    return list(seen)


def _parse_fixes(raw) -> list[tuple[str, str]]:
    fixes: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in raw or []:
        wrong = right = ""
        if isinstance(item, dict):
            wrong, right = str(item.get("wrong") or "").strip(), str(item.get("right") or "").strip()
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            wrong, right = str(item[0]).strip(), str(item[1]).strip()
        if not wrong or not right or wrong == right or wrong in seen or wrong in UNSAFE_SOURCES:
            continue
        fixes.append((wrong, right))
        seen.add(wrong)
    return fixes


def _load_store(preset: str | None = None) -> dict:
    path = lexicon_path(preset)
    if not path.exists():
        return {"version": 0, "terms": [], "fixes": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 0, "terms": [], "fixes": []}
    if not isinstance(payload, dict):
        return {"version": 0, "terms": [], "fixes": []}
    try:
        version = int(payload.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    return {
        "version": version,
        "terms": _parse_terms(payload.get("terms")),
        "fixes": _parse_fixes(payload.get("fixes")),
    }


def _save_store(store: dict, preset: str | None = None) -> None:
    path = lexicon_path(preset)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _merged_terms(store: dict, preset: str | None = None) -> list[str]:
    seen: dict[str, None] = {}
    for term in (*_seed_terms(preset), *store["terms"]):
        if term:
            seen[term] = None
    return list(seen)


def _merged_fixes(store: dict, *, sort_long_first: bool, preset: str | None = None) -> list[tuple[str, str]]:
    seeds = _seed_fixes(preset)
    merged = list(seeds)
    seen = {item[0] for item in seeds}
    for wrong, right in store["fixes"]:
        if wrong in seen or wrong in UNSAFE_SOURCES:
            continue
        merged.append((wrong, right))
        seen.add(wrong)
    if sort_long_first:
        merged.sort(key=lambda item: len(item[0]), reverse=True)
    return merged


def _versioned(store: dict) -> bool:
    return int(store.get("version") or 0) >= 1


def known_terms(preset: str | None = None) -> list[str]:
    store = _load_store(preset)
    if _versioned(store):
        return list(store["terms"])
    return _merged_terms(store, preset)


def known_terms_hint() -> str:
    return "、".join(known_terms())


def all_fixes(preset: str | None = None) -> list[tuple[str, str]]:
    store = _load_store(preset)
    if _versioned(store):
        merged = [item for item in store["fixes"] if item[0] not in UNSAFE_SOURCES]
        merged.sort(key=lambda item: len(item[0]), reverse=True)
        return merged
    return _merged_fixes(store, sort_long_first=True, preset=preset)


def editable_fixes(preset: str | None = None) -> list[tuple[str, str]]:
    store = _load_store(preset)
    if _versioned(store):
        return [item for item in store["fixes"] if item[0] not in UNSAFE_SOURCES]
    return _merged_fixes(store, sort_long_first=False, preset=preset)


def lexicon_payload(preset: str | None = None) -> dict:
    target = _preset_key(preset)
    store = _load_store(target)
    return {
        "terms": known_terms(target),
        "fixes": [{"wrong": wrong, "right": right} for wrong, right in editable_fixes(target)],
        "customized": _versioned(store),
        "preset": target,
    }


def save_user_lexicon(terms, fixes, preset: str | None = None) -> dict:
    target = _preset_key(preset)
    clean_terms = _parse_terms(terms)
    clean_fixes = _parse_fixes(fixes)
    _save_store({"version": 1, "terms": clean_terms, "fixes": [list(item) for item in clean_fixes]}, target)
    return lexicon_payload(target)


def reset_user_lexicon(preset: str | None = None) -> dict:
    target = _preset_key(preset)
    path = lexicon_path(target)
    if path.exists():
        path.unlink()
    return lexicon_payload(target)


def _protected_window(text: str, start: int, length: int) -> bool:
    window = text[start : start + length]
    if window == "东北":
        rest = text[start + length :]
        return bool(re.match(r"板块|振兴|三省|地区|经济|证券|制药|有色|虎|人|菜|话", rest))
    return False


def _pinyin_limit(window: str, source_py: str) -> int:
    # 两字词只接受全拼一致，避免「节要/解套」「要负/妖股」这类误替换
    if len(window) <= 2 or len(source_py) <= 3:
        return 0
    return 1


def _near_terms(
    window: str,
    index: PinyinTermIndex,
    pinyin_cache: dict[str, str],
) -> list[str]:
    same_len = index.by_len_set.get(len(window))
    if window in COMMON_WORDS or (same_len and window in same_len):
        return []
    source_py = pinyin_cache.setdefault(window, _pinyin(window))
    if len(source_py) < 3:
        return []
    limit = _pinyin_limit(window, source_py)
    bucket = index.by_pinyin.get(len(window)) or {}
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    if limit <= 0:
        keys = ((source_py, 0),) if source_py in bucket else ()
    else:
        keys = []
        src_prefix = source_py[:2]
        for prefix in index.prefixes.get(len(window), ()):
            if _pinyin_dist_at_most(src_prefix, prefix, 1) is None:
                continue
            for key in index.by_prefix[len(window)][prefix]:
                dist = _pinyin_dist_at_most(source_py, key, limit)
                if dist is not None:
                    keys.append((key, dist))
    for key, dist in keys:
        for term in bucket.get(key) or ():
            if term == window or term in seen:
                continue
            seen.add(term)
            scored.append((dist, term))
    scored.sort()
    return [term for _dist, term in scored[:8]]


def _best_term(window: str, index: PinyinTermIndex, pinyin_cache: dict[str, str]) -> str | None:
    matches = _near_terms(window, index, pinyin_cache)
    if len(matches) != 1:
        return None
    return matches[0]


def _cjk_run_span(text: str, index: int) -> tuple[int, int]:
    start = index
    while start > 0 and CJK_CHAR.match(text[start - 1]):
        start -= 1
    end = index
    while end < len(text) and CJK_CHAR.match(text[end]):
        end += 1
    return start, end


def _affix_ok(chunk: str) -> bool:
    return (not chunk) or all(ch in CJK_PARTICLES for ch in chunk)


def _window_isolated(text: str, start: int, length: int) -> bool:
    run_start, run_end = _cjk_run_span(text, start)
    prefix = text[run_start:start]
    suffix = text[start + length : run_end]
    return _affix_ok(prefix) and _affix_ok(suffix)


def _apply_pinyin(text: str, terms: list[str]) -> str:
    index = pinyin_term_index(terms)
    if not index.lengths:
        return text
    cache: dict[str, str] = {}
    out: list[str] = []
    cursor = 0
    while cursor < len(text):
        matched = False
        for length in index.lengths:
            if cursor + length > len(text):
                continue
            window = text[cursor : cursor + length]
            if window in index.term_set:
                out.append(window)
                cursor += length
                matched = True
                break
        if matched:
            continue
        for length in index.lengths:
            # 两字近音太容易撞日常词（细微/席位、二十/而是），只留给精确词表和云端候选
            if length < 3 or cursor + length > len(text):
                continue
            window = text[cursor : cursor + length]
            if not _is_cjk_text(window):
                continue
            if _protected_window(text, cursor, length):
                continue
            if not _window_isolated(text, cursor, length):
                continue
            target = _best_term(window, index, cache)
            if not target:
                continue
            out.append(target)
            cursor += length
            matched = True
            break
        if not matched:
            out.append(text[cursor])
            cursor += 1
    return "".join(out)


def pinyin_candidates(
    text: str,
    terms: list[str] | None = None,
    *,
    index: PinyinTermIndex | None = None,
    pinyin_cache: dict[str, str] | None = None,
) -> list[tuple[str, list[str]]]:
    """找出原文窗口里拼音接近词表、但本机还没敢自动改掉的候选。"""
    if not text:
        return []
    lookup = index or pinyin_term_index(terms)
    if not lookup.lengths:
        return []
    cache = pinyin_cache if pinyin_cache is not None else {}
    seen: dict[str, list[str]] = {}
    order: list[str] = []
    for cursor in range(len(text)):
        if not _is_cjk_char(text[cursor]):
            continue
        for length in lookup.lengths:
            if cursor + length > len(text):
                continue
            window = text[cursor : cursor + length]
            if window in seen:
                break
            if window in COMMON_WORDS or window in lookup.term_set:
                continue
            if not _is_cjk_text(window):
                continue
            if _protected_window(text, cursor, length):
                continue
            dests = _near_terms(window, lookup, cache)
            if not dests:
                continue
            seen[window] = dests
            order.append(window)
            break
    return [(src, seen[src]) for src in order]


def apply_lexicon(text: str) -> str:
    if not text:
        return ""
    for wrong, right in all_fixes():
        if wrong in text:
            text = text.replace(wrong, right)
    from app.services.domain import uses_ashare_lexicon

    if uses_ashare_lexicon():
        text = FILLER_BAODING.sub("宝鼎", text)
        text = NORTHEAST_STOCK.sub("东百", text)
    return _apply_pinyin(text, known_terms())


def _align_run(before: str, after: str) -> list[tuple[str, str]]:
    if before == after:
        return []
    start = 0
    while start < min(len(before), len(after)) and before[start] == after[start]:
        start += 1
    end = 0
    while (
        end < min(len(before), len(after)) - start
        and before[len(before) - 1 - end] == after[len(after) - 1 - end]
    ):
        end += 1
    src = before[start : len(before) - end if end else None]
    dst = after[start : len(after) - end if end else None]
    if start and (len(dst) < 2 or len(src) < 2):
        src = before[start - 1 : len(before) - end if end else None]
        dst = after[start - 1 : len(after) - end if end else None]
    if dst and 2 <= len(dst) <= 6 and src != dst:
        return [(src, dst)]
    return []


def replacements_from_pair(before: str, after: str) -> list[tuple[str, str]]:
    if not before or not after or before == after:
        return []
    left = CJK_RUN.findall(before)
    right = CJK_RUN.findall(after)
    pairs: list[tuple[str, str]] = []
    if len(left) == len(right):
        for src, dst in zip(left, right):
            pairs.extend(_align_run(src, dst))
    return [(src, dst) for src, dst in pairs if dst and src != dst]


def remember_replacements(pairs: list[tuple[str, str]]) -> None:
    usable = [
        (src.strip(), dst.strip())
        for src, dst in pairs
        if src.strip()
        and dst.strip()
        and src.strip() != dst.strip()
        and src.strip() not in UNSAFE_SOURCES
        and 2 <= len(dst.strip()) <= 6
    ]
    if not usable:
        return
    store = _load_store()
    versioned = _versioned(store)
    terms = list(store["terms"])
    fixes = list(store["fixes"])
    known = set(terms if versioned else (*_seed_terms(), *terms))
    seen_wrong = {item[0] for item in (fixes if versioned else (*_seed_fixes(), *fixes))}
    changed = False
    for src, dst in usable:
        if dst not in known:
            terms.append(dst)
            known.add(dst)
            changed = True
        if src not in seen_wrong and 2 <= len(src) <= 6:
            fixes.append((src, dst))
            seen_wrong.add(src)
            changed = True
    if changed:
        payload = {"terms": terms, "fixes": [list(item) for item in fixes]}
        if versioned:
            payload["version"] = int(store["version"])
        _save_store(payload)


def remember_proofread(before: list, after: list, pairs: list[tuple[str, str]] | None = None) -> None:
    if pairs is None:
        collected: list[tuple[str, str]] = []
        by_id = {item.id: item.text for item in before}
        for item in after:
            old = by_id.get(item.id)
            if old:
                collected.extend(replacements_from_pair(old, item.text))
        pairs = collected
    remember_replacements(pairs)
