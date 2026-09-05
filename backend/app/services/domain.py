import json
import shutil
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.schemas import DomainPack

A_SHARE_PACK = DomainPack(
    id="a-share",
    base_preset="a-share",
    name="A股盘面课",
    asr_hint="以下是简体中文A股盘面课。",
    chapter_focus="转写里出现的案例、个股、板块、方法步骤写入章节或要点，不要逐句摘录。",
    term_aliases=(
        "个股用盘面课简称：哈药、东百、航天、宝鼎。不要写哈亚、韩天、A保底；"
        "「东北」若是个股案例写东百，东北板块除外。"
    ),
    overview_role="你是一位善于阅读和总结的助手，能把整场盘面课理解透并浓缩成结构化摘要。",
    overview_stance=(
        "辨立场：区分客观盘面事实、讲者交易纪律、修辞/类比包装，以及讲者自己承认的边界。"
        "不要编造外部资料，不要另写一套荐股或行情预测。"
    ),
    disclaimer="以上归纳仅来自本场转写，未引入外部资料。不能当作荐股或确定性行情预测。",
    knowledge_role="你是用户的私人知识库助手。",
    knowledge_guardrails=(
        "资料不足就直说知识库里没有足够依据，不要用常识补全交易建议。"
        "这是用户的个人学习笔记，不是实时行情，也不构成投资建议。"
    ),
    example_questions=["卖票方法是什么", "低吸的条件有哪些"],
    content_keywords=[
        "加息",
        "板块",
        "主线",
        "行情",
        "纪律",
        "低吸",
        "仓位",
        "财报",
        "复盘",
        "趋势",
        "流动性",
        "课程",
    ],
    highlight_phrases=[
        "不看空不做空",
        "高抛低吸",
        "超跌反弹",
        "不宜重仓",
        "趋势向上",
        "仓位管理",
        "主线未定",
        "低吸",
    ],
    highlight_stock_codes=True,
    proofread_hint=(
        "段落在讲经典、修行、身体、天气、哲学时，不要用打板、席位、缩量、天地板等盘面词。"
        "后面是涨停、炸板、低吸、打板、案例、标的时，更可能是个股或行话。"
    ),
)

GENERIC_PACK = DomainPack(
    id="generic",
    base_preset="generic",
    name="通用课程",
    asr_hint="以下是简体中文讲解。",
    chapter_focus="转写里出现的概念、方法、步骤、案例和数据写入章节或要点，不要逐句摘录。",
    term_aliases="",
    overview_role="你是一位善于阅读和总结的助手，能把整场内容理解透并浓缩成结构化摘要。",
    overview_stance=(
        "辨立场：区分客观事实、讲者主张、修辞/类比包装，以及讲者自己承认的边界。"
        "不要编造外部资料，不要把总结写成专业鉴定或承诺。"
    ),
    disclaimer="以上归纳仅来自本场转写，未引入外部资料。不能当作专业意见或行动承诺。",
    knowledge_role="你是用户的私人知识库助手。",
    knowledge_guardrails=(
        "资料不足就直说知识库里没有足够依据，不要用常识补全。"
        "这是用户的个人学习笔记，不是权威结论。"
    ),
    example_questions=["这节课的核心方法是什么", "有哪些关键步骤"],
    content_keywords=["方法", "步骤", "定义", "案例", "结论", "练习", "概念", "原理", "课程"],
    highlight_phrases=[],
    highlight_stock_codes=False,
    proofread_hint="只根据候选词和上下文选择，不要把无关领域的专有名词硬套进去。",
)

PRESETS = {
    "a-share": A_SHARE_PACK,
    "generic": GENERIC_PACK,
}

DEFAULT_DOMAIN_ID = "a-share"
PROTECTED_PRESET_IDS = {"a-share"}
_job_pack: ContextVar[DomainPack | None] = ContextVar("job_domain_pack", default=None)

ENGINE_CHAPTER_PROMPT = """你是视频内容编辑。下面是按分段编号给出的转写，编号已对应真实时间，不要自己编造时钟时间。
只输出 JSON。不要写 title，不要写 overview。字段如下：
{
  "chapters": [
    {"title": "章节名", "start_segment": 0, "end_segment": 3, "bullets": ["要点"]}
  ],
  "key_points": [
    {"text": "可定位的关键信息", "start_segment": 2, "end_segment": 2}
  ]
}
规则：
1. 严格忠于原文，禁止编造。可用自己的话压缩，事实和讲者观点分开。
2. start_segment / end_segment 必须是已有编号，禁止输出 mm:ss，不要臆造编号。
3. 章节按时间顺序，不要重叠。同一主题能盖住本窗口就合成一章，允许接近 10 分钟。本窗口通常 1 到 3 章，禁止为凑数拆章。
4. 转写里出现的案例、方法步骤写入章节或要点，不要逐句摘录。
5. chapters 1 到 3 个，禁止空数组。窗口不足约 2 分钟时最多 1 章。每个 bullets 3 到 5 条；key_points 3 到 6 条。
6. 必须使用简体中文。输出必须是完整可解析的 JSON。
"""

ENGINE_OVERVIEW_PROMPT = """# 角色
你是一位善于阅读和总结的助手，能把整场内容理解透并浓缩成结构化摘要。

# 任务
阅读下面按时间排好的全部章节和要点（含 start/end 时钟，这些章节已经覆盖全场）。先按理解步骤消化，再把摘要写入 JSON 的 overview。

# 理解步骤
1. 按时间扫 chapters，把相邻、讲同一件事的章并成同一板块。不要写死行业名单，按本场标题和要点判断是否同一主题。
2. 顶层 ### 做成 3 到 6 个主题板块，写成「一、……」「二、……」。禁止一章一个 ###，禁止把不相邻的同主题跨场拼在一起。
3. 某一板块内容多时，再在其下用 ####「1.」「2.」拆 2 到 5 个小节。只有 1 个子板块时不要写 ####，正文直接放在 ### 下。
4. 抓核心：讲者到底想表达什么，写成一句能独立成立的判断
5. 拆证据：各板块用关键事件、数据、案例支撑；事件自身的日期/盘中时刻写进表的「事件时间」
6. 辨立场：区分客观事实、讲者主张、修辞/类比包装，以及讲者自己承认的边界
7. 不要按每个交易日或每个小节单独开大板块；也不要把整场硬捏成固定两块。

# 只输出一个 JSON 对象。overview 是字符串，必须把写满的 Markdown 放进这个字段，不要写在 JSON 外面。
{
  "title": "根据输入概括的整场标题",
  "overview": "## 一句话总结\\n**根据输入写出的完整判断，禁止省略号。**\\n\\n## 主题与核心观点\\n（后接写满的表、论证结构、辨立场）"
}

# overview 必须严格按此结构（用 Markdown，不要写成互不相关的单条清单）。文中的省略号只是格式示意，输出时必须换成根据输入写的完整句子。
## 一句话总结
**用一句话概括方法+立场+做法，加粗整句。**

## 主题与核心观点
| 维度 | 内容 |
|---|---|
| 主题 | …… |
| 核心观点 | …… |
| 手段 | 原文里的方法/指标，没有就写未注明 |

## 论证结构
板块必须编号。顶层 ### 用汉字「一、二、三」；子板块 #### 用阿拉伯数字「1. 2. 3.」。标题后可带该范围片子时钟（约 hh:mm:ss–hh:mm:ss，必须抄输入 start/end）。

章节少、平铺不超过约 6 块时：

### 一、……（约 00:15:39–00:23:07）
先用一两句话说明这一节在讲什么。有日期、数据、关键事件时用表：
| 事件时间 | 关键事件 | 含义 |
|---|---|---|
| 8月19日 | 关键事件 | 含义 |
核心结论：**……**

### 二、……（约 hh:mm:ss–hh:mm:ss）
概念/方法用小点：解释 + 原文证据。不要写成散装流水账。

章节多、一章一块会超过约 6 块时（必须凝结，禁止 20 个 ### 平铺）：

### 一、主题层（约 00:04:51–00:54:51）
#### 1. 小节（约 00:04:51–00:17:19）
| 事件时间 | 关键事件 | 含义 |
|---|---|---|
| 7月20日 | 关键事件 | 含义 |
#### 2. 小节（约 00:17:19–00:54:51）
该小节结论：**……**
这一大板块的核心结论：**……**

### 二、方法层（约 00:54:51–01:28:12）
#### 1. 概念
#### 2. 案例
| 事件时间 | 关键事件 | 含义 |
|---|---|---|
| 1月30日 | 关键事件 | 含义 |

「事件时间」只写转写里该事件自己的日期或盘中时刻（7月20日、8月21日、9:25、1月30日）。没有就写「未注明」。禁止把音视频播放进度（00:17:41、01:04:41）写进表格。片子时钟只出现在板块标题的「约 hh:mm:ss–hh:mm:ss」里。

## 辨立场
先肯定原文里可操作的纪律或方法（必须能在转写中找到）。再指出：修辞类比与严谨论证的区别、方法边界（仅当原文提到）、信息来源是否只来自讲者。不要编造外部资料。

# 原则
1. 严格忠于原文，禁止编造不存在的信息。总结不是摘抄，要用自己的话改写压缩。
2. 事实和观点分开，不混为一谈。
3. 关键数字注明有无来源；转写没给出就写「未注明」。板块标题里的片子时钟只能从输入的 start/end 或 allowed_video_clocks 抄写，必须带小时（00:09:29），禁止自编。表格「事件时间」只写事件自身的日期/盘中时刻，不要写播放进度。
4. 保持精炼，不堆砌原文细节，不要多余开场白。大板块下只有 1 个子板块时不要重复写子标题。
5. 不要输出 chapters 或 key_points。必须使用简体中文。
6. overview 必须写满。禁止用「...」「……」「Markdown 正文，格式见下」或只留标题骨架。主题表三行、每个板块和辨立场都要写成完整句子。
"""

ENGINE_KNOWLEDGE_PROMPT = """你是用户的私人知识库助手。资料全部来自用户自己转写的视频，只存在本机，回答时不要编造资料之外的内容。
规则：
1. 只根据【资料】回答用户问题。资料不足就直说知识库里没有足够依据，不要用常识编造。
2. 必须使用简体中文。分段书写，关键结论、对象、数字、方法用**加粗**。
3. 提到具体说法时标注来源，格式用〔标题 · mm:ss〕，时间必须来自资料里的时间，禁止自己编时钟。
"""

ENGINE_PROOFREAD_PROMPT = """你是转写校对员。下面每段只列出原文里出现的近音窗口，以及词表里拼音接近的候选。
只输出 JSON：
{"edits": [{"id": 12, "from": "积极人", "to": "机器人"}]}
规则：
1. 默认不改。没有把握、候选和上下文不符，就不要输出那条。
2. 只能使用给出的 from/to，禁止自造词，禁止改数字、标点、未列出的字。
3. from 必须是该编号原文中的连续原文。
4. 不要改观点，不要润色，不要合并或删除分段。
5. 必须使用简体中文。
"""

_path_override: Path | None = None


def set_domain_path(path: Path | None) -> None:
    global _path_override
    _path_override = path


def domain_path() -> Path:
    if _path_override is not None:
        return _path_override
    return settings.data_dir / "domain_pack.json"


def preset_pack(preset_id: str) -> DomainPack:
    pack = PRESETS.get((preset_id or "").strip())
    if pack is None:
        return A_SHARE_PACK.model_copy(deep=True)
    return pack.model_copy(deep=True)


def list_presets() -> list[DomainPack]:
    packs = _pack_map()
    ordered: list[DomainPack] = []
    if DEFAULT_DOMAIN_ID in packs:
        ordered.append(packs[DEFAULT_DOMAIN_ID])
    for key, pack in packs.items():
        if key == DEFAULT_DOMAIN_ID:
            continue
        ordered.append(pack)
    return [item.model_copy(deep=True) for item in ordered]


def _factory_dump() -> dict[str, dict]:
    return {key: item.model_dump() for key, item in PRESETS.items()}


def _seed_store() -> dict:
    return {"active_id": DEFAULT_DOMAIN_ID, "packs": _factory_dump()}


def _normalize_store(payload: object) -> dict:
    if not isinstance(payload, dict):
        return _seed_store()
    raw_packs = payload.get("packs")
    packs: dict[str, dict] = {}
    if isinstance(raw_packs, dict):
        for key, item in raw_packs.items():
            pack = parse_pack(item)
            packs[pack.id] = pack.model_dump()
    elif isinstance(raw_packs, list):
        for item in raw_packs:
            pack = parse_pack(item)
            packs[pack.id] = pack.model_dump()
    else:
        pack = parse_pack(payload)
        packs = _factory_dump()
        packs[pack.id] = pack.model_dump()
        return {"active_id": pack.id or DEFAULT_DOMAIN_ID, "packs": packs}
    if DEFAULT_DOMAIN_ID not in packs:
        packs[DEFAULT_DOMAIN_ID] = A_SHARE_PACK.model_dump()
    active_id = str(payload.get("active_id") or "").strip() or DEFAULT_DOMAIN_ID
    if active_id not in packs:
        active_id = DEFAULT_DOMAIN_ID
    return {"active_id": active_id, "packs": packs}


def _read_store() -> dict:
    path = domain_path()
    if not path.exists():
        return _seed_store()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _seed_store()
    return _normalize_store(payload)


def _write_store(store: dict) -> None:
    path = domain_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _pack_map() -> dict[str, DomainPack]:
    store = _read_store()
    result: dict[str, DomainPack] = {}
    for key, item in store["packs"].items():
        pack = parse_pack(item)
        result[pack.id] = pack
        if key != pack.id:
            result[key] = pack
    if DEFAULT_DOMAIN_ID not in result:
        result[DEFAULT_DOMAIN_ID] = A_SHARE_PACK.model_copy(deep=True)
    return result


def canonicalize_pack(pack: DomainPack) -> DomainPack:
    base_id = (pack.base_preset or "").strip() or DEFAULT_DOMAIN_ID
    if base_id not in PRESETS:
        base_id = DEFAULT_DOMAIN_ID
    pack_id = (pack.id or "").strip() or base_id
    return pack.model_copy(update={"base_preset": base_id, "id": pack_id})


def parse_pack(payload: object | None) -> DomainPack:
    if payload is None:
        return A_SHARE_PACK.model_copy(deep=True)
    if isinstance(payload, DomainPack):
        return canonicalize_pack(payload)
    if not isinstance(payload, dict):
        return A_SHARE_PACK.model_copy(deep=True)
    try:
        pack = DomainPack.model_validate(payload)
    except Exception:
        return A_SHARE_PACK.model_copy(deep=True)
    if pack.base_preset not in PRESETS:
        pack = pack.model_copy(update={"base_preset": DEFAULT_DOMAIN_ID})
    return canonicalize_pack(pack)


def load_active_pack() -> DomainPack:
    override = _job_pack.get()
    if override is not None:
        return override
    store = _read_store()
    packs = store["packs"]
    active_id = store["active_id"]
    payload = packs.get(active_id) or packs.get(DEFAULT_DOMAIN_ID)
    if payload is None:
        return A_SHARE_PACK.model_copy(deep=True)
    return parse_pack(payload)


def save_active_pack(payload: object) -> DomainPack:
    pack = parse_pack(payload)
    store = _read_store()
    store["packs"][pack.id] = pack.model_dump()
    store["active_id"] = pack.id
    _write_store(store)
    return pack


def reset_active_pack(preset_id: str = "a-share") -> DomainPack:
    target = (preset_id or "").strip() or DEFAULT_DOMAIN_ID
    current = load_active_pack()
    if target in PRESETS:
        factory = preset_pack(target)
        if current.id not in PRESETS and current.id:
            factory = factory.model_copy(update={"id": current.id, "name": current.name})
        return save_active_pack(factory)
    return save_active_pack(preset_pack(DEFAULT_DOMAIN_ID))


def job_domain_id(domain_id: str | None) -> str:
    raw = stored_job_domain(domain_id)
    return normalize_domain_id(raw, fallback=True)


def pack_by_id(domain_id: str | None) -> DomainPack:
    target = normalize_domain_id(domain_id, fallback=True)
    packs = _pack_map()
    pack = packs.get(target)
    if pack is None:
        return A_SHARE_PACK.model_copy(deep=True)
    return pack.model_copy(deep=True)


def normalize_domain_id(domain_id: str | None, fallback: bool = True) -> str:
    raw = (domain_id or "").strip()
    if not raw:
        return DEFAULT_DOMAIN_ID if fallback else ""
    packs = _pack_map()
    if raw in packs:
        return raw
    return DEFAULT_DOMAIN_ID if fallback else raw


def stored_job_domain(domain_id: str | None) -> str:
    raw = (domain_id or "").strip()
    if not raw or raw == "custom":
        return DEFAULT_DOMAIN_ID
    return raw


def add_preset(source_id: str | None = None, name: str = "") -> DomainPack:
    source = pack_by_id(source_id) if (source_id or "").strip() else load_active_pack()
    new_id = uuid4().hex
    label = (name or "").strip() or f"{source.name} 副本"
    pack = source.model_copy(deep=True, update={"id": new_id, "name": label})
    store = _read_store()
    store["packs"][new_id] = pack.model_dump()
    store["active_id"] = new_id
    _write_store(store)
    _copy_lexicon(source.id, new_id)
    return pack


def delete_preset(preset_id: str) -> DomainPack:
    target = (preset_id or "").strip()
    if target in PROTECTED_PRESET_IDS:
        raise ValueError("默认 A 股领域不能删除")
    store = _read_store()
    if target not in store["packs"]:
        raise ValueError("领域不存在")
    del store["packs"][target]
    if store["active_id"] == target:
        store["active_id"] = DEFAULT_DOMAIN_ID
    _write_store(store)
    _delete_lexicon(target)
    return load_active_pack()


def _copy_lexicon(source_id: str, dest_id: str) -> None:
    from app.services.lexicon import lexicon_path

    if not source_id or not dest_id or source_id == dest_id:
        return
    src = lexicon_path(source_id)
    dest = lexicon_path(dest_id)
    if src.exists() and src.resolve() != dest.resolve():
        dest.write_bytes(src.read_bytes())


def _delete_lexicon(preset_id: str) -> None:
    from app.services.lexicon import lexicon_path

    if not preset_id or preset_id in PROTECTED_PRESET_IDS:
        return
    path = lexicon_path(preset_id)
    folder = path.parent
    if folder.name == preset_id and folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


def lexicon_preset(preset: str | None = None) -> str:
    raw = (preset or "").strip()
    if raw:
        packs = _pack_map()
        if raw in packs or raw in PRESETS:
            return raw
    pack = load_active_pack()
    pid = (pack.id or "").strip()
    if pid:
        return pid
    return DEFAULT_DOMAIN_ID


def current_domain_id() -> str:
    return load_active_pack().id or DEFAULT_DOMAIN_ID


def uses_ashare_lexicon(pack: DomainPack | None = None, preset: str | None = None) -> bool:
    if pack is not None:
        return pack.base_preset == "a-share" or pack.id == "a-share"
    if preset:
        found = pack_by_id(preset)
        return found.base_preset == "a-share" or found.id == "a-share"
    current = load_active_pack()
    return current.base_preset == "a-share" or current.id == "a-share"


@contextmanager
def job_pack_scope(domain_id: str | None):
    pack = pack_by_id(domain_id)
    token = _job_pack.set(pack)
    try:
        yield pack
    finally:
        _job_pack.reset(token)


def _join_extras(items: list[str]) -> str:
    lines = [item.strip() for item in items if item and item.strip()]
    if not lines:
        return ""
    return "\n领域规则：\n" + "\n".join(f"- {line}" for line in lines)


def chapter_prompt(pack: DomainPack | None = None) -> str:
    current = pack or load_active_pack()
    override = (current.chapter_prompt_override or "").strip()
    if override:
        return override
    return ENGINE_CHAPTER_PROMPT.rstrip() + _join_extras([current.chapter_focus, current.term_aliases])


def overview_prompt(pack: DomainPack | None = None) -> str:
    current = pack or load_active_pack()
    override = (current.overview_prompt_override or "").strip()
    if override:
        return override
    body = ENGINE_OVERVIEW_PROMPT
    role = (current.overview_role or "").strip()
    if role:
        marker = "# 角色\n"
        start = body.find(marker)
        if start >= 0:
            rest = body[start + len(marker) :]
            cut = rest.find("\n# ")
            if cut >= 0:
                body = body[: start + len(marker)] + role + rest[cut:]
            else:
                body = marker + role + "\n" + rest
    extras = _join_extras([current.overview_stance, current.term_aliases, current.disclaimer])
    if extras:
        return body.rstrip() + extras
    return body


def knowledge_system(pack: DomainPack | None = None) -> str:
    current = pack or load_active_pack()
    override = (current.knowledge_prompt_override or "").strip()
    if override:
        return override
    extras = _join_extras([current.knowledge_guardrails])
    return ENGINE_KNOWLEDGE_PROMPT.rstrip() + extras


def proofread_system(pack: DomainPack | None = None) -> str:
    current = pack or load_active_pack()
    hint = (current.proofread_hint or "").strip()
    if not hint:
        return ENGINE_PROOFREAD_PROMPT
    return ENGINE_PROOFREAD_PROMPT.rstrip() + "\n领域校对：\n" + hint


def asr_hint_prefix(pack: DomainPack | None = None) -> str:
    current = pack or load_active_pack()
    return (current.asr_hint or "").strip() or "以下是简体中文讲解。"
