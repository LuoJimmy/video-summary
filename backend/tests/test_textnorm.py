from app.services.textnorm import fix_asr_glossary, to_simplified


def test_traditional_to_simplified():
    assert to_simplified("好,各位同學,大家晚上好") == "好,各位同学,大家晚上好"
    assert to_simplified("專題課") == "专题课"
    assert to_simplified("") == ""


def test_to_simplified_is_stable_across_traditional_and_simplified():
    assert to_simplified("為什麼半年") == "为什么半年"
    assert to_simplified("为什么半年") == "为什么半年"
    converted = to_simplified("為什麼半年你改變自己")
    assert converted == to_simplified(converted)


def test_to_simplified_keeps_real_yao_and_undoes_phrase_typo():
    assert to_simplified("幺蛾子") == "幺蛾子"
    assert to_simplified("那么半年") == "那么半年"
    assert to_simplified("啊，那么半导体。") == "啊，那么半导体。"


def test_match_key_absorbs_legacy_yao_typo():
    from app.services.textnorm import match_key

    assert match_key("那幺半年") == match_key("那么半年")
    assert match_key("為什麼半年") == match_key("为什么半年")
    assert match_key("AI 復盤") == "ai 复盘"


def test_asr_glossary_fixes_trading_homophones():
    assert "负反馈不会太大" in fix_asr_glossary("只要覆反会不扩大")
    assert "每一次调整都可以参与" in fix_asr_glossary("每一次挑准都可以参与")
    assert fix_asr_glossary("排面细节") == "盘面细节"
    assert fix_asr_glossary("覆盘") == "复盘"
    assert fix_asr_glossary("不管是哈亚一跑") == "不管是哈药一跑"
    assert "航天" in fix_asr_glossary("消费跟韩天争的PK")
    assert "航天" in fix_asr_glossary("当韩发走不动了")
    assert fix_asr_glossary("我们就看到A保底") == "我们就看到宝鼎"
    assert fix_asr_glossary("我们就看到啊保底") == "我们就看到宝鼎"
    assert "保底仓" in fix_asr_glossary("给情绪保底仓")
    assert "东百" in fix_asr_glossary("东北是直接死的嘛")
    assert "东百" in fix_asr_glossary("来东板站出来的")
    assert "东北板块" in fix_asr_glossary("先看东北板块")
    assert fix_asr_glossary("东北证券") == "东北证券"
    assert fix_asr_glossary("笼头先走") == "龙头先走"
    assert fix_asr_glossary("弱转墙反包") == "弱转强反包"


def test_whisper_hint_uses_current_terms():
    from app.services.textnorm import whisper_hint

    hint = whisper_hint()
    assert "打板" in hint
    assert "弱转强" in hint
