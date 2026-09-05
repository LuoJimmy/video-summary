from app.services.domain import (
    A_SHARE_PACK,
    GENERIC_PACK,
    chapter_prompt,
    knowledge_system,
    load_active_pack,
    overview_prompt,
    parse_pack,
    save_active_pack,
)
from app.services.textnorm import whisper_hint


def test_default_pack_is_a_share():
    pack = load_active_pack()
    assert pack.id == "a-share"
    assert pack.base_preset == "a-share"
    assert pack.highlight_stock_codes is True
    prompt = chapter_prompt(pack)
    assert "哈药" in prompt
    assert "不要写 overview" in prompt
    overview = overview_prompt(pack)
    assert "盘面课" in overview
    assert "荐股" in overview
    chat = knowledge_system(pack)
    assert "投资建议" in chat
    hint = whisper_hint()
    assert "A股盘面课" in hint
    assert "打板" in hint


def test_generic_pack_omits_stock_rules():
    prompt = chapter_prompt(GENERIC_PACK)
    assert "哈药" not in prompt
    assert "个股" not in prompt
    overview = overview_prompt(GENERIC_PACK)
    assert "荐股" not in overview
    assert "盘面课" not in overview
    chat = knowledge_system(GENERIC_PACK)
    assert "投资建议" not in chat
    assert "交易建议" not in chat


def test_save_and_load_generic_pack():
    saved = save_active_pack(GENERIC_PACK)
    assert saved.id == "generic"
    loaded = load_active_pack()
    assert loaded.id == "generic"
    assert loaded.name == "通用课程"
    assert "哈药" not in chapter_prompt()
    hint = whisper_hint()
    assert "A股盘面课" not in hint
    assert "简体中文讲解" in hint


def test_edited_pack_keeps_id():
    edited = A_SHARE_PACK.model_copy(update={"name": "我的盘面课"})
    pack = parse_pack(edited)
    assert pack.id == "a-share"
    assert pack.base_preset == "a-share"
    assert pack.name == "我的盘面课"
    restored = parse_pack(A_SHARE_PACK)
    assert restored.id == "a-share"


def test_lexicon_follows_generic_preset():
    from app.services.lexicon import known_terms, lexicon_path, lexicon_payload

    save_active_pack(GENERIC_PACK)
    path = lexicon_path()
    assert path.parent.name == "generic"
    assert "打板" not in known_terms()
    ashare = lexicon_payload("a-share")
    assert "打板" in ashare["terms"]
    assert ashare["preset"] == "a-share"


def test_prompt_override_used_when_set():
    pack = GENERIC_PACK.model_copy(update={"chapter_prompt_override": "只要章节 JSON"})
    assert chapter_prompt(pack) == "只要章节 JSON"


def test_add_and_delete_user_preset():
    from app.services.domain import add_preset, delete_preset, list_presets

    added = add_preset("a-share", "期货课")
    assert added.id != "a-share"
    assert added.name == "期货课"
    assert added.id in {item.id for item in list_presets()}
    assert load_active_pack().id == added.id
    delete_preset(added.id)
    assert added.id not in {item.id for item in list_presets()}
    assert load_active_pack().id == "a-share"
    try:
        delete_preset("a-share")
        raise AssertionError("should not delete a-share")
    except ValueError:
        pass
