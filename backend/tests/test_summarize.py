import json

import pytest

from app.schemas import AppSettingsOut, SummaryChapter, SummaryKeyPoint, TranscriptSegment
from app.services.summarize import (
    OpenAICompatibleSummarizer,
    PROMPT,
    SummarizeError,
    _chunk_segments,
    _overview_context,
    _summary_from_payload,
    bullet_is_hollow,
    bullets_from_segments,
    extract_overview_document,
    fallback_overview,
    local_partial,
    overview_is_hollow,
    overview_is_incomplete,
    repair_chapters,
    segments_for_summarize,
    title_from_overview,
    title_is_blank,
)


def test_chunk_segments_splits_by_duration():
    segments = [TranscriptSegment(id=i, start=i * 100, end=i * 100 + 10, text="短") for i in range(10)]
    chunks = _chunk_segments(segments, max_chars=100000, max_seconds=250)
    assert len(chunks) >= 3
    assert chunks[0][0].id == 0
    assert chunks[-1][-1].id == 9


def test_summary_from_payload_skips_broken_items():
    summary = _summary_from_payload(
        {
            "title": "课",
            "overview": "综述",
            "chapters": [
                {"title": "开场", "start_segment": 0, "end_segment": 2, "bullets": "单条"},
                {"title": "坏的"},
            ],
            "key_points": [{"text": "低吸", "start_segment": 1}],
        }
    )
    assert summary.chapters[0].bullets == ["单条"]
    assert summary.key_points[0].text == "低吸"


def test_complete_repairs_truncated_json():
    class FakeMessage:
        content = '{"title": "产业升级", "overview": "先看主线", "chapters": [{"title": "开场", "start_segment": 0, "end_segment": 1, "bullets": ["要点"]}], "key_points": [{"text": "低吸", "start_segment": 1}'

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["max_tokens"] == 8192
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    summary = OpenAICompatibleSummarizer()._complete(
        FakeClient(),
        AppSettingsOut(summarize_model="deepseek-chat"),
        "sys",
        "user",
    )
    assert summary.title == "产业升级"
    assert summary.chapters[0].title == "开场"
    assert summary.key_points[0].text == "低吸"


def test_complete_retries_once_on_prose():
    class FakeMessage:
        def __init__(self, content):
            self.content = content

    class FakeChoice:
        def __init__(self, content):
            self.message = FakeMessage(content)

    class FakeResponse:
        def __init__(self, content):
            self.choices = [FakeChoice(content)]

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            return FakeResponse("我们根据用户要求，需处理一个视频转写。")

    completions = FakeCompletions()

    class FakeChat:
        def __init__(self):
            self.completions = completions

    class FakeClient:
        chat = FakeChat()

    with pytest.raises(SummarizeError, match="不是合法 JSON"):
        OpenAICompatibleSummarizer()._complete(
            FakeClient(),
            AppSettingsOut(summarize_model="deepseek-chat"),
            "sys",
            "user",
        )
    assert completions.calls == 2


def test_complete_ignores_reasoning_after_json():
    class FakeMessage:
        content = '{"title": "课", "overview": "综述"}'
        reasoning_content = "思考过程\n" * 40 + '{"title": "不该拼进来"}'

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    summary = OpenAICompatibleSummarizer()._complete(
        FakeClient(),
        AppSettingsOut(summarize_model="deepseek-v4-flash"),
        "sys",
        "user",
    )
    assert summary.title == "课"
    assert summary.overview == "综述"


def test_complete_accepts_dict_content():
    class FakeMessage:
        content = {"title": "课", "overview": "综述"}

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    summary = OpenAICompatibleSummarizer()._complete(
        FakeClient(),
        AppSettingsOut(summarize_model="deepseek-v4-flash"),
        "sys",
        "user",
    )
    assert summary.title == "课"
    assert summary.overview == "综述"


def test_complete_accepts_python_dict_repr():
    class FakeMessage:
        content = "{'title': '课', 'overview': '综述'}"

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    summary = OpenAICompatibleSummarizer()._complete(
        FakeClient(),
        AppSettingsOut(summarize_model="deepseek-v4-flash"),
        "sys",
        "user",
    )
    assert summary.title == "课"
    assert summary.overview == "综述"


def test_summarize_falls_back_when_overview_json_invalid(monkeypatch):
    segments = [
        TranscriptSegment(id=i, start=i * 100, end=i * 100 + 10, text="低吸纪律要等收敛后再做。")
        for i in range(8)
    ]
    chunk_payload = json.dumps(
        {
            "title": "分段",
            "overview": "短",
            "chapters": [{"title": "开场", "start_segment": 0, "end_segment": 1, "bullets": ["低吸纪律要等收敛后再做。"]}],
            "key_points": [{"text": "低吸纪律要等收敛后再做。", "start_segment": 0}],
        },
        ensure_ascii=False,
    )

    class FakeMessage:
        def __init__(self, content):
            self.content = content

    class FakeChoice:
        def __init__(self, content):
            self.message = FakeMessage(content)

    class FakeResponse:
        def __init__(self, content):
            self.choices = [FakeChoice(content)]

    class FakeCompletions:
        def create(self, **kwargs):
            system = kwargs["messages"][0]["content"]
            if system.startswith("# 角色"):
                return FakeResponse("不是 JSON")
            return FakeResponse(chunk_payload)

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr("app.services.summarize.openai_client", lambda *args, **kwargs: FakeClient())
    summary = OpenAICompatibleSummarizer().summarize(
        segments,
        AppSettingsOut(summarize_api_key="k", summarize_model="deepseek-v4-flash"),
    )
    assert summary.chapters
    assert "低吸纪律要等收敛后再做" in summary.overview
    assert not overview_is_hollow(summary.overview)


def test_complete_prefers_reasoning_when_content_is_prose():
    class FakeMessage:
        content = "我们根据用户要求先分析转写，编号里很多是噪音。"
        reasoning_content = '{"title": "课", "overview": "综述"}'

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    summary = OpenAICompatibleSummarizer()._complete(
        FakeClient(),
        AppSettingsOut(summarize_model="deepseek-v4-flash"),
        "sys",
        "user",
    )
    assert summary.title == "课"
    assert summary.overview == "综述"


def test_summarize_uses_local_chunk_when_json_missing(monkeypatch):
    segments = [
        TranscriptSegment(id=i, start=i * 100, end=i * 100 + 10, text="低吸纪律要等收敛后再做。")
        for i in range(8)
    ]
    overview_payload = json.dumps(
        {
            "title": "整场",
            "overview": FILLED_OVERVIEW,
        },
        ensure_ascii=False,
    )

    class FakeMessage:
        def __init__(self, content):
            self.content = content

    class FakeChoice:
        def __init__(self, content):
            self.message = FakeMessage(content)

    class FakeResponse:
        def __init__(self, content):
            self.choices = [FakeChoice(content)]

    class FakeCompletions:
        def create(self, **kwargs):
            system = kwargs["messages"][0]["content"]
            if system.startswith("# 角色"):
                return FakeResponse(overview_payload)
            return FakeResponse("我们根据用户要求，需处理一个视频转写，不要输出 JSON。")

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr("app.services.summarize.openai_client", lambda *args, **kwargs: FakeClient())
    summary = OpenAICompatibleSummarizer().summarize(
        segments,
        AppSettingsOut(summarize_api_key="k", summarize_model="deepseek-v4-flash"),
    )
    assert summary.chapters
    assert summary.title == "整场"
    assert "只要不出现巨量下砸就不看空" in summary.overview


def test_complete_empty_stays_on_json_object():
    class FakeMessage:
        def __init__(self, content, reasoning_content=None):
            self.content = content
            self.reasoning_content = reasoning_content

    class FakeChoice:
        def __init__(self, content, reasoning_content=None):
            self.message = FakeMessage(content, reasoning_content)

    class FakeResponse:
        def __init__(self, content, reasoning_content=None):
            self.choices = [FakeChoice(content, reasoning_content)]

    class FakeCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return FakeResponse("")

    completions = FakeCompletions()

    class FakeChat:
        def __init__(self):
            self.completions = completions

    class FakeClient:
        chat = FakeChat()

    with pytest.raises(SummarizeError, match="空内容"):
        OpenAICompatibleSummarizer()._complete(
            FakeClient(),
            AppSettingsOut(summarize_model="deepseek-v4-flash"),
            "sys",
            "user",
        )
    assert len(completions.calls) == 2
    assert completions.calls[0]["response_format"] == {"type": "json_object"}
    assert completions.calls[1]["response_format"] == {"type": "json_object"}


def test_overview_context_includes_clock():
    segments = [
        TranscriptSegment(id=0, start=569, end=580, text="开场"),
        TranscriptSegment(id=1, start=3600, end=3780, text="后半"),
    ]
    payload = _overview_context(
        [SummaryChapter(title="市场操作", start_segment=0, end_segment=1, bullets=["冰点"])],
        [SummaryKeyPoint(text="分批建仓", start_segment=1, end_segment=1)],
        segments,
    )
    assert '"start": "00:09:29"' in payload
    assert '"end": "01:03:00"' in payload
    assert "allowed_video_clocks" in payload
    assert "00:09:29" in payload
    assert "市场操作" in payload
    assert "分批建仓" in payload
    assert payload.count('"text":') <= 12
    assert payload.count("冰点") >= 1
    extra_points = [SummaryKeyPoint(text=f"要点{i}要写进综述上下文。", start_segment=1, end_segment=1) for i in range(20)]
    slim = _overview_context(
        [SummaryChapter(title="市场操作", start_segment=0, end_segment=1, bullets=["冰点", "二", "三", "四"])],
        extra_points,
        segments,
    )
    assert slim.count('"text":') == 12
    assert slim.count("四") == 0


SKELETON_OVERVIEW = """## 一句话总结
**...**

## 主题与核心观点
| 维度 | 内容 |
...

## 论证结构
### 一、市场节奏与操作纪律（约 00:20:00–00:52:22）
#### 1. 调整结束与低吸纪律（约 00:20:00–00:22:25、00:40:00–00:41:19）
...

## 辨立场
..."""

FILLED_OVERVIEW = """## 一句话总结
**调整结束后用低吸纪律做二段反弹，不看空但要等收敛。**

## 主题与核心观点
| 维度 | 内容 |
|---|---|
| 主题 | 二段反弹节奏 |
| 核心观点 | 上涨放量、调整缩量才继续做 |
| 手段 | 低吸与仓位管理 |

## 论证结构
### 一、市场节奏与操作纪律（约 00:20:00–00:52:22）
周五冲高回落但调整收敛，属于健康形态。
核心结论：**只要不出现巨量下砸就不看空。**

## 辨立场
纪律可操作；修辞类比不能当成信号。方法边界在于等待收敛，信息只来自本场转写，不能当成荐股。"""


def test_overview_is_hollow_detects_ellipsis_skeleton():
    assert overview_is_hollow(SKELETON_OVERVIEW)
    assert not overview_is_hollow(FILLED_OVERVIEW)
    assert overview_is_incomplete(SKELETON_OVERVIEW)
    assert not overview_is_incomplete(FILLED_OVERVIEW)
    truncated = (
        "## 一句话总结\n"
        "**面对主要经济体加息、国内流动性退坡、日本套息交易空间被压缩，"
        "A股难有单边上涨大趋势，讲者把下半年重点从AI硬件转向有色金属与化工等资源品，"
        "并以减少操作、八成以上仓位集中资源龙头、只低吸不追高作为执行纪律。**\n\n"
        "## 主题与核心观点\n| 维度 | 内容 |\n|---|---|\n"
        "| 主题 | 在流动性收紧、指数难有单边趋势的市场里，做下半年周期资源切换与防守式交易。 |\n"
        "| 核心观点 |"
    )
    assert overview_is_incomplete(truncated)


def test_fallback_overview_fills_template_from_chapters():
    segments = [
        TranscriptSegment(id=0, start=1200, end=1345, text="调整结束"),
        TranscriptSegment(id=1, start=1345, end=3142, text="第二段"),
    ]
    text = fallback_overview(
        [
            SummaryChapter(
                title="调整结束与操作纪律",
                start_segment=0,
                end_segment=0,
                bullets=["调整结束，增量后情绪发散。", "上涨放量、调整缩量。"],
            ),
            SummaryChapter(
                title="第二段的时间与警惕信号",
                start_segment=1,
                end_segment=1,
                bullets=["第二段时间会更久。"],
            ),
        ],
        [SummaryKeyPoint(text="只要不出现巨量下砸就不看空。", start_segment=0, end_segment=0)],
        segments,
    )
    assert overview_is_hollow(text) is False
    assert not overview_is_incomplete(text)
    assert "只要不出现巨量下砸就不看空" in text
    assert "调整结束与操作纪律" in text
    assert "..." not in text
    assert "……" not in text


def test_complete_retries_incomplete_overview_then_fails():
    class FakeMessage:
        def __init__(self, content):
            self.content = content

    class FakeChoice:
        def __init__(self, content):
            self.message = FakeMessage(content)

    class FakeResponse:
        def __init__(self, content):
            self.choices = [FakeChoice(content)]

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            assert kwargs.get("extra_body", {}).get("thinking") == {"type": "disabled"}
            return FakeResponse(json.dumps({"title": "二段反弹", "overview": SKELETON_OVERVIEW}, ensure_ascii=False))

    completions = FakeCompletions()

    class FakeChat:
        def __init__(self):
            self.completions = completions

    class FakeClient:
        chat = FakeChat()

    with pytest.raises(SummarizeError, match="综述未写完"):
        OpenAICompatibleSummarizer()._complete(
            FakeClient(),
            AppSettingsOut(summarize_model="deepseek-v4-flash"),
            "sys",
            "user",
            require_filled_overview=True,
        )
    assert completions.calls == 2


def test_bullet_is_hollow_rejects_truncated_fragment():
    assert bullet_is_hollow("讲")
    assert bullet_is_hollow("嗯")
    assert bullet_is_hollow("对吧。")
    assert not bullet_is_hollow("底部跟指数共振四次后有行情预期。")


def test_repair_chapters_fills_truncated_bullet_from_transcript():
    segments = [
        TranscriptSegment(id=928, start=2998, end=3003, text="你站在这么个角度嘛。"),
        TranscriptSegment(id=937, start=3018, end=3022, text="共振指数4次。"),
        TranscriptSegment(id=938, start=3022, end=3028, text="他在底部跟他们共振的，后面就有行情的预期嘛。"),
        TranscriptSegment(id=944, start=3047, end=3055, text="你到它里面，你去做超短不现实嘛，你就是用时间去可保的。"),
        TranscriptSegment(id=961, start=3141, end=3142, text="好。"),
        TranscriptSegment(id=980, start=3300, end=3360, text="半导体设备每次调整都可以低吸，因为还有国产替代和扩产逻辑。"),
        TranscriptSegment(id=1000, start=3360, end=3420, text="弹性分支看MLCC和PTFE，核心仍要聚焦能扛的标的。"),
        TranscriptSegment(id=1100, start=4000, end=4060, text="后面机构药明康龙走弱，说明这条线少了一大块。"),
    ]
    chapters = repair_chapters(
        [
            SummaryChapter(title="共振与心态：用时间换空间", start_segment=928, end_segment=961, bullets=["讲"]),
            SummaryChapter(
                title="药板块退潮",
                start_segment=1100,
                end_segment=1100,
                bullets=["机构走弱后只能聚焦核心。"],
            ),
        ],
        segments,
    )
    first = next(item for item in chapters if item.title == "共振与心态：用时间换空间")
    assert "讲" not in first.bullets
    assert any("共振" in item or "时间" in item or "超短" in item for item in first.bullets)
    assert len(chapters) == 2


def test_title_is_blank_treats_ellipsis_as_empty():
    assert title_is_blank("...")
    assert title_is_blank("……")
    assert title_is_blank("  ")
    assert not title_is_blank("9月主线")


def test_extract_overview_strips_thinking():
    raw = (
        "这样字符串内包含 \\n，但实际内容是一行行的，这是 JSON 对象。需要把整段作为 JSON 字符串。构建 overview 详细文本。\n"
        + FILLED_OVERVIEW
        + "\n\n这个 overview 相当长，应该够。注意表格中事件时间。"
    )
    extracted = extract_overview_document(raw)
    assert extracted.startswith("## 一句话总结")
    assert "只要不出现巨量下砸就不看空" in extracted
    assert "构建 overview" not in extracted
    assert "这个 overview 相当长" not in extracted
    assert not overview_is_hollow(extracted)


def test_summary_from_payload_drops_ellipsis_title_and_thinking():
    summary = _summary_from_payload(
        {
            "title": "...",
            "overview": "这是 JSON 对象。构建 overview。\n" + FILLED_OVERVIEW,
            "chapters": [{"title": "开场", "start_segment": 0, "end_segment": 1, "bullets": ["低吸纪律要等收敛后再做。"]}],
        }
    )
    assert summary.title == ""
    assert summary.overview.startswith("## 一句话总结")
    assert "构建 overview" not in summary.overview


def test_local_partial_keeps_global_segment_ids():
    chunk = [
        TranscriptSegment(id=851, start=3056, end=3059, text="航天小商业航天是吧，指数里票很杂。"),
        TranscriptSegment(id=852, start=3059, end=3100, text="能源金属这块你真看好有色就去做铜。"),
        TranscriptSegment(id=860, start=3140, end=3180, text="逻辑还在我就不管，仓位放在主线上。"),
    ]
    partial = local_partial(chunk)
    assert partial.chapters
    assert partial.chapters[0].start_segment == 851
    assert partial.chapters[0].end_segment >= 851


def test_local_partial_skips_filler_only_buckets():
    chunk = [
        TranscriptSegment(id=0, start=0, end=20, text="嗯。"),
        TranscriptSegment(id=1, start=20, end=40, text="Yeah."),
        TranscriptSegment(id=2, start=40, end=50, text="好。"),
    ]
    partial = local_partial(chunk)
    assert partial.chapters == []


def test_summarize_runs_each_chunk_once_then_overview(monkeypatch):
    segments = [
        TranscriptSegment(id=i, start=i * 100, end=i * 100 + 10, text="低吸纪律要等收敛后再做。")
        for i in range(8)
    ]
    chunk_payload = json.dumps(
        {
            "title": "分段",
            "overview": "短",
            "chapters": [{"title": "开场", "start_segment": 0, "end_segment": 1, "bullets": ["低吸纪律要等收敛后再做。"]}],
            "key_points": [{"text": "低吸纪律要等收敛后再做。", "start_segment": 0}],
        },
        ensure_ascii=False,
    )
    overview_payload = json.dumps({"title": "整场", "overview": FILLED_OVERVIEW}, ensure_ascii=False)
    calls: list[str] = []

    class FakeMessage:
        def __init__(self, content):
            self.content = content

    class FakeChoice:
        def __init__(self, content):
            self.message = FakeMessage(content)

    class FakeResponse:
        def __init__(self, content):
            self.choices = [FakeChoice(content)]

    class FakeCompletions:
        def create(self, **kwargs):
            system = kwargs["messages"][0]["content"]
            calls.append("overview" if system.startswith("# 角色") else "chunk")
            if system.startswith("# 角色"):
                return FakeResponse(overview_payload)
            return FakeResponse(chunk_payload)

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr("app.services.summarize.openai_client", lambda *args, **kwargs: FakeClient())
    monkeypatch.setattr("app.services.summarize._summarize_concurrency", lambda settings=None: 3)
    summary = OpenAICompatibleSummarizer().summarize(
        segments,
        AppSettingsOut(summarize_api_key="k", summarize_model="deepseek-v4-flash"),
    )
    assert calls[-1] == "overview"
    assert calls.count("overview") == 1
    assert calls.count("chunk") == len(_chunk_segments(segments))
    assert summary.title == "整场"


def test_chunk_prompt_omits_long_overview():
    assert "不要写 overview" in PROMPT
    assert "一句话总结" not in PROMPT
    assert "论证结构" not in PROMPT
    assert '"chapters"' in PROMPT
    assert '"key_points"' in PROMPT
    assert "1 到 3 章" in PROMPT
    assert "每 3 到 8 分钟" not in PROMPT


def test_title_from_overview_uses_one_liner_not_chapter():
    assert "调整结束后用低吸纪律" in title_from_overview(FILLED_OVERVIEW)


def test_segments_for_summarize_drops_chatter_and_filler():
    segments = [
        TranscriptSegment(id=0, start=0, end=2, text="嗯。"),
        TranscriptSegment(id=1, start=2, end=6, text="能听得到吗？进不去直播间。"),
        TranscriptSegment(id=2, start=6, end=20, text="本堂课程先看流动性收紧下的主线。"),
        TranscriptSegment(id=3, start=20, end=40, text="有色和化工是下半年更想做的方向。"),
        TranscriptSegment(id=4, start=40, end=42, text="好。"),
        TranscriptSegment(id=5, start=42, end=45, text="那我们周三再见，兄弟们。"),
    ]
    kept = segments_for_summarize(segments)
    assert [item.id for item in kept] == [2, 3]
    assert segments[0].text == "嗯。"


def _fake_chat_client(handler):
    class FakeMessage:
        def __init__(self, content):
            self.content = content

    class FakeChoice:
        def __init__(self, content):
            self.message = FakeMessage(content)

    class FakeResponse:
        def __init__(self, content):
            self.choices = [FakeChoice(content)]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResponse(handler(kwargs))

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    return FakeClient()


def test_complete_retries_then_accepts_valid_json():
    payloads = [
        "我们根据用户要求先分析。",
        json.dumps(
            {
                "chapters": [{"title": "开场", "start_segment": 0, "end_segment": 1, "bullets": ["低吸"]}],
                "key_points": [{"text": "低吸", "start_segment": 0}],
            },
            ensure_ascii=False,
        ),
    ]
    calls = {"n": 0}

    def handler(_kwargs):
        index = calls["n"]
        calls["n"] += 1
        return payloads[index]

    summary = OpenAICompatibleSummarizer()._complete(
        _fake_chat_client(handler),
        AppSettingsOut(summarize_model="deepseek-v4-flash"),
        "sys",
        "user",
        require_chapters=True,
    )
    assert calls["n"] == 2
    assert summary.chapters[0].title == "开场"


def test_summarize_retries_empty_chapters_then_falls_back(monkeypatch):
    segments = [
        TranscriptSegment(id=i, start=i * 40, end=i * 40 + 10, text="低吸纪律要等收敛后再做，不要追高。")
        for i in range(8)
    ]
    empty = json.dumps({"chapters": [], "key_points": []}, ensure_ascii=False)
    overview_payload = json.dumps({"title": "整场", "overview": FILLED_OVERVIEW}, ensure_ascii=False)
    chunk_calls = {"n": 0}

    def handler(kwargs):
        system = kwargs["messages"][0]["content"]
        if system.startswith("# 角色"):
            return overview_payload
        chunk_calls["n"] += 1
        return empty

    monkeypatch.setattr("app.services.summarize.openai_client", lambda *args, **kwargs: _fake_chat_client(handler))
    summary = OpenAICompatibleSummarizer().summarize(
        segments,
        AppSettingsOut(summarize_api_key="k", summarize_model="deepseek-v4-flash"),
    )
    assert chunk_calls["n"] == 2 * len(_chunk_segments(segments))
    assert summary.chapters
    assert summary.title == "整场"
    assert any("低吸" in item.title or "低吸" in "".join(item.bullets) for item in summary.chapters)
