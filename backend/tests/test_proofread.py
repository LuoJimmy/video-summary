from app.schemas import AppSettingsOut, TranscriptSegment
from app.services.lexicon import save_user_lexicon
from app.services.proofread import proofread_transcript


def test_proofread_without_api_key_uses_glossary():
    segments = [
        TranscriptSegment(id=0, start=0, end=4, text="只要覆反会不扩大"),
        TranscriptSegment(id=1, start=4, end=8, text="每一次挑准都可以参与"),
    ]
    out = proofread_transcript(segments, AppSettingsOut())
    assert out[0].id == 0
    assert out[0].start == 0
    assert out[0].end == 4
    assert out[0].text == "只要负反馈不会太大"
    assert out[1].text == "每一次调整都可以参与"


def test_proofread_without_api_key_fixes_stock_aliases():
    segments = [
        TranscriptSegment(id=0, start=0, end=2, text="不管是哈亚一跑"),
        TranscriptSegment(id=1, start=2, end=4, text="我们就看到A保底"),
        TranscriptSegment(id=2, start=4, end=6, text="消费跟韩天争的PK"),
        TranscriptSegment(id=3, start=6, end=8, text="东北是直接死的嘛"),
    ]
    out = proofread_transcript(segments, AppSettingsOut())
    assert out[0].text == "不管是哈药一跑"
    assert out[1].text == "我们就看到宝鼎"
    assert "航天" in out[2].text
    assert "东百" in out[3].text


def _fake_client(monkeypatch, payload: str, calls: list):
    class FakeMessage:
        content = payload

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr("app.services.proofread.openai_client", lambda *args, **kwargs: FakeClient())


def test_llm_proofread_applies_sparse_candidate_only(monkeypatch):
    save_user_lexicon(["机器人", "基器人"], [])
    calls: list = []
    _fake_client(
        monkeypatch,
        '{"edits": [{"id": 0, "from": "积极人", "to": "机器人"}]}',
        calls,
    )
    segments = [
        TranscriptSegment(id=0, start=1.5, end=3.2, text="对吧有积极人"),
        TranscriptSegment(id=1, start=3.2, end=6.0, text="负反馈还在"),
    ]
    out = proofread_transcript(
        segments,
        AppSettingsOut(summarize_api_key="k", summarize_model="demo"),
        use_llm=True,
    )
    assert [item.id for item in out] == [0, 1]
    assert out[0].start == 1.5
    assert out[1].end == 6.0
    assert out[0].text == "对吧有机器人"
    assert out[1].text == "负反馈还在"
    assert len(calls) == 1
    user = calls[0]["messages"][1]["content"]
    assert "积极人 →" in user
    assert "只能从这里选" in user
    assert "负反馈还在" not in user
    assert "默认不改" in calls[0]["messages"][0]["content"]


def test_llm_proofread_ignores_edit_outside_candidates(monkeypatch):
    save_user_lexicon(["机器人", "基器人"], [])
    calls: list = []
    _fake_client(
        monkeypatch,
        '{"edits": [{"id": 0, "from": "积极人", "to": "席位"}, {"id": 0, "from": "对吧", "to": "机器人"}]}',
        calls,
    )
    segments = [TranscriptSegment(id=0, start=0, end=2, text="对吧有积极人")]
    out = proofread_transcript(segments, AppSettingsOut(summarize_api_key="k"), use_llm=True)
    assert out[0].text == "对吧有积极人"


def test_llm_skips_request_when_no_pinyin_candidates(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("没有候选时不应调云端校对")

    monkeypatch.setattr("app.services.proofread.openai_client", boom)
    segments = [
        TranscriptSegment(id=0, start=0, end=2, text="只要负反馈不会太大"),
        TranscriptSegment(id=1, start=2, end=4, text="排面细节要覆盘"),
    ]
    out = proofread_transcript(segments, AppSettingsOut(summarize_api_key="k"), use_llm=True)
    assert out[0].text == "只要负反馈不会太大"
    assert out[1].text == "盘面细节要复盘"


def test_long_transcript_batches_llm_proofread(monkeypatch):
    import re

    from app.services.proofread import LLM_PROOFREAD_CHUNK_SIZE

    save_user_lexicon(["机器人", "基器人"], [])
    calls: list = []
    _fake_client(monkeypatch, '{"edits": []}', calls)
    total = LLM_PROOFREAD_CHUNK_SIZE * 2 + 1
    segments = [
        TranscriptSegment(id=i, start=float(i), end=float(i + 1), text="对吧有积极人")
        for i in range(total)
    ]
    out = proofread_transcript(segments, AppSettingsOut(summarize_api_key="k"), use_llm=True)
    assert len(out) == total
    assert len(calls) == 3
    counts = [len(re.findall(r"^\[\d+\]", kwargs["messages"][1]["content"], re.M)) for kwargs in calls]
    assert counts[0] == LLM_PROOFREAD_CHUNK_SIZE
    assert counts[1] == LLM_PROOFREAD_CHUNK_SIZE
    assert counts[2] == 1


def test_auto_pipeline_skips_llm_even_for_short_transcript(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("自动流水线不应再调云端校对")

    monkeypatch.setattr("app.services.proofread.openai_client", boom)
    segments = [TranscriptSegment(id=0, start=0, end=2, text="排面细节要覆盘")]
    out = proofread_transcript(segments, AppSettingsOut(summarize_api_key="k"))
    assert out[0].text == "盘面细节要复盘"


def test_llm_proofread_failure_falls_back_to_glossary(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("接口不可用")

    monkeypatch.setattr("app.services.proofread.openai_client", boom)
    segments = [TranscriptSegment(id=0, start=0, end=2, text="排面细节要覆盘")]
    out = proofread_transcript(segments, AppSettingsOut(summarize_api_key="k"), use_llm=True)
    assert out[0].text == "盘面细节要复盘"
