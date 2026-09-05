import json

import pytest

from app.services.jsonutil import close_truncated_json, coerce_model_text, parse_model_json


def test_parse_fenced_json():
    raw = '```json\n{"title": "课", "overview": "综述"}\n```'
    assert parse_model_json(raw)["title"] == "课"


def test_parse_closes_unterminated_string():
    raw = '{"title": "产业升级", "overview": "先看主线'
    data = parse_model_json(raw)
    assert data["title"] == "产业升级"
    assert data["overview"] == "先看主线"


def test_parse_closes_truncated_array():
    raw = '{"title": "t", "chapters": [{"title": "开场", "start_segment": 0, "end_segment": 2, "bullets": ["要点"'
    data = parse_model_json(raw)
    assert data["chapters"][0]["title"] == "开场"
    assert data["chapters"][0]["bullets"] == ["要点"]


def test_close_truncated_json_strips_dangling_escape():
    raw = '{"title": "ok", "overview": "hello\\'
    repaired = close_truncated_json(raw)
    data = json.loads(repaired)
    assert data["overview"] == "hello"


def test_parse_model_json_ignores_trailing_extra_data():
    raw = '{"title": "课", "overview": "综述"}\n\n这是额外说明'
    assert parse_model_json(raw)["title"] == "课"
    assert parse_model_json(raw)["overview"] == "综述"


def test_parse_model_json_takes_first_object_when_concatenated():
    raw = '{"title": "课", "overview": "综述"}\n{"title": "第二份"}'
    data = parse_model_json(raw)
    assert data["title"] == "课"
    assert data["overview"] == "综述"


def test_parse_model_json_promotes_trailing_overview_markdown():
    raw = (
        '{"title": "课", "overview": "## 一句话总结\\n**...**"}\n\n'
        "## 一句话总结\n**真正要用情绪周期做决策。**\n\n## 辨立场\n仅据转写。"
    )
    data = parse_model_json(raw)
    assert data["title"] == "课"
    assert "真正要用情绪周期做决策" in data["overview"]


def test_parse_model_json_promotes_second_object_overview_when_first_is_hollow():
    raw = (
        '{"title": "课", "overview": "..."}\n'
        '{"overview": "## 一句话总结\\n**完整判断要写在这里。**\\n\\n## 论证结构\\n正文写满。\\n\\n## 辨立场\\n仅据转写。"}'
    )
    data = parse_model_json(raw)
    assert data["title"] == "课"
    assert "完整判断要写在这里" in data["overview"]


def test_parse_model_json_rejects_non_object():
    with pytest.raises(json.JSONDecodeError):
        parse_model_json("[1, 2]")


def test_parse_python_dict_repr():
    raw = "{'title': '课', 'overview': '综述'}"
    assert parse_model_json(raw)["title"] == "课"
    assert parse_model_json(raw)["overview"] == "综述"


def test_parse_smart_quotes_json():
    raw = '{“title”: “课”, “overview”: “综述”}'
    assert parse_model_json(raw)["title"] == "课"


def test_parse_unquoted_keys():
    raw = '{title: "课", overview: "综述"}'
    data = parse_model_json(raw)
    assert data["title"] == "课"
    assert data["overview"] == "综述"


def test_parse_model_json_accepts_dict():
    assert parse_model_json({"title": "课", "overview": "综述"})["title"] == "课"


def test_parse_skips_leading_false_brace():
    raw = '说明 {不是对象 然后才是 {"title": "课", "overview": "综述"}'
    assert parse_model_json(raw)["title"] == "课"


def test_coerce_model_text_dict_and_parts():
    dumped = coerce_model_text({"title": "课", "overview": "综述"})
    assert parse_model_json(dumped)["title"] == "课"
    parts = [{"type": "text", "text": '{"title": "课", "overview": "综述"}'}]
    assert parse_model_json(coerce_model_text(parts))["title"] == "课"
