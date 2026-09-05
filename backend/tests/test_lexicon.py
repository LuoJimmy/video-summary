import time

from app.services.lexicon import (
    apply_lexicon,
    known_terms,
    pinyin_candidates,
    pinyin_term_index,
    remember_replacements,
    replacements_from_pair,
    reset_user_lexicon,
    save_user_lexicon,
)


def test_pinyin_aligns_unseen_homophones():
    assert apply_lexicon("排面细节要覆盘") == "盘面细节要复盘"
    assert "哈药" in apply_lexicon("不管是哈呀一跑")
    assert "航天" in apply_lexicon("消费跟韩天争的PK")
    assert apply_lexicon("东北板块") == "东北板块"
    assert "东百" in apply_lexicon("东北是直接死的嘛")


def test_a_share_jargon_and_homophones():
    terms = set(known_terms())
    for term in ("弱转强", "天地板", "中特估", "北向资金", "游资", "核按钮"):
        assert term in terms
    assert apply_lexicon("笼头先走") == "龙头先走"
    assert apply_lexicon("低西比追高稳") == "低吸比追高稳"
    assert apply_lexicon("打版炸版都要看") == "打板炸板都要看"
    assert apply_lexicon("涨停版回封") == "涨停板回封"
    assert apply_lexicon("不管是哈呀一跑") == "不管是哈药一跑"
    assert apply_lexicon("盘面细节要复盘") == "盘面细节要复盘"
    assert apply_lexicon("只要负反馈不会太大") == "只要负反馈不会太大"
    assert "排版" in apply_lexicon("这页排版没问题")
    assert "柚子" in apply_lexicon("桌上放着柚子")


def test_pinyin_does_not_eat_everyday_or_compound_words():
    assert apply_lexicon("更细微的存在") == "更细微的存在"
    assert apply_lexicon("二十八脉") == "二十八脉"
    assert apply_lexicon("天地万物") == "天地万物"
    assert apply_lexicon("有积极人") == "有机器人"
    assert apply_lexicon("好险才1.3") == "好像才1.3"
    assert apply_lexicon("人们交吸的欲望") == "人们交易的欲望"


def test_pinyin_candidates_list_near_terms_without_applying():
    cands = dict(pinyin_candidates("天地万物与更细微的存在"))
    assert "天地万" in cands
    assert "天地板" in cands["天地万"]
    assert apply_lexicon("天地万物") == "天地万物"


def test_user_lexicon_overrides_defaults():
    save_user_lexicon(["测试词"], [])
    assert known_terms() == ["测试词"]
    assert apply_lexicon("覆盘") == "覆盘"
    assert apply_lexicon("排面") == "排面"
    reset_user_lexicon()
    assert "打板" in known_terms()
    assert apply_lexicon("覆盘") == "复盘"


def test_learn_replacements_from_proofread_diff():
    pairs = replacements_from_pair("今天看中气走得弱", "今天看中气走得弱")
    assert pairs == []
    pairs = replacements_from_pair("旗子还没倒", "旗手还没倒")
    assert ("旗子", "旗手") in pairs
    remember_replacements(pairs)
    assert "旗手" in apply_lexicon("看旗子有没有倒")


def test_pinyin_aligns_unseen_homophones():
    assert apply_lexicon("排面细节要覆盘") == "盘面细节要复盘"
    assert "哈药" in apply_lexicon("不管是哈呀一跑")
    assert "航天" in apply_lexicon("消费跟韩天争的PK")
    assert apply_lexicon("东北板块") == "东北板块"
    assert "东百" in apply_lexicon("东北是直接死的嘛")


def test_a_share_jargon_and_homophones():
    terms = set(known_terms())
    for term in ("弱转强", "天地板", "中特估", "北向资金", "游资", "核按钮"):
        assert term in terms
    assert apply_lexicon("笼头先走") == "龙头先走"
    assert apply_lexicon("低西比追高稳") == "低吸比追高稳"
    assert apply_lexicon("打版炸版都要看") == "打板炸板都要看"
    assert apply_lexicon("涨停版回封") == "涨停板回封"
    assert apply_lexicon("不管是哈呀一跑") == "不管是哈药一跑"
    assert apply_lexicon("盘面细节要复盘") == "盘面细节要复盘"
    assert apply_lexicon("只要负反馈不会太大") == "只要负反馈不会太大"
    assert "排版" in apply_lexicon("这页排版没问题")
    assert "柚子" in apply_lexicon("桌上放着柚子")


def test_user_lexicon_overrides_defaults():
    save_user_lexicon(["测试词"], [])
    assert known_terms() == ["测试词"]
    assert apply_lexicon("覆盘") == "覆盘"
    assert apply_lexicon("排面") == "排面"
    reset_user_lexicon()
    assert "打板" in known_terms()
    assert apply_lexicon("覆盘") == "复盘"


def test_learn_replacements_from_proofread_diff():
    pairs = replacements_from_pair("今天看中气走得弱", "今天看中气走得弱")
    assert pairs == []
    pairs = replacements_from_pair("旗子还没倒", "旗手还没倒")
    assert ("旗子", "旗手") in pairs
    remember_replacements(pairs)
    assert "旗手" in apply_lexicon("看旗子有没有倒")


def test_pinyin_candidates_two_char_exact_and_three_char_edit():
    two = dict(pinyin_candidates("今天打版了"))
    assert "打版" in two
    assert "打板" in two["打版"]
    assert "细微" not in dict(pinyin_candidates("更细微的存在"))
    three = dict(pinyin_candidates("天地万物"))
    assert "天地万" in three
    assert "天地板" in three["天地万"]


def test_pinyin_term_index_reused_for_same_terms():
    terms = known_terms()
    first = pinyin_term_index(terms)
    second = pinyin_term_index(list(terms))
    assert first is second


def test_pinyin_candidates_full_scan_under_one_second():
    # 接近一场课：约 945 段、1.6 万字，短句和标点打断连续汉字
    parts = ("盘面细节要复盘，只要负反馈不会太大。", "龙头先走。天地万物与更细微的存在，", "排版没问题，柚子还在桌上。")
    texts = [parts[i % 3] + str(i % 10) for i in range(945)]
    assert 14000 <= sum(len(text) for text in texts) <= 22000
    index = pinyin_term_index()
    cache: dict[str, str] = {}
    started = time.perf_counter()
    for text in texts:
        pinyin_candidates(text, index=index, pinyin_cache=cache)
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, f"候选扫描耗时 {elapsed:.2f}s，应小于 1 秒"
