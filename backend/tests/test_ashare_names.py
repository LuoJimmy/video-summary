from app.services.ashare_names import (
    ashare_short_name,
    board_lexicon_terms,
    unique_ashare_short_names,
    unique_board_names,
)
from app.services.lexicon import known_terms


def test_ashare_short_name_strips_letters_and_clips():
    assert ashare_short_name("万  科Ａ") == "万科"
    assert ashare_short_name("深物业A") == "深物业"
    assert ashare_short_name("比亚迪") == "比亚迪"
    assert ashare_short_name("贵州茅台") == "贵州"
    assert ashare_short_name("*ST美丽") == "美丽"
    assert ashare_short_name("TCL科技") == "科技"
    assert ashare_short_name("哈药股份") == "哈药"
    assert ashare_short_name("A") == ""
    assert ashare_short_name("") == ""


def test_unique_ashare_short_names_dedupes_in_order():
    assert unique_ashare_short_names(["贵州茅台", "贵州白酒", "比亚迪", "比亚迪"]) == (
        "贵州",
        "比亚迪",
    )


def test_a_share_lexicon_includes_company_shorts():
    terms = set(known_terms())
    for term in ("万科", "平安", "贵州", "比亚迪", "哈药", "东百", "航天", "宁德", "茅台"):
        assert term in terms
    assert sum(1 for term in terms if len(term) in (2, 3)) >= 4000


def test_board_lexicon_keeps_full_name_and_stems():
    assert board_lexicon_terms("白酒Ⅲ") == ("白酒",)
    assert board_lexicon_terms("海南板块") == ("海南板块", "海南")
    assert board_lexicon_terms("华为概念") == ("华为概念", "华为")
    assert board_lexicon_terms("2026中报预增") == ()
    assert board_lexicon_terms("钨") == ()
    assert board_lexicon_terms("昨日连板_含一字") == ("昨日连板含一字",)


def test_unique_board_names_dedupes_levels():
    assert unique_board_names(["白酒Ⅲ", "白酒Ⅱ", "半导体", "海南板块"]) == (
        "白酒",
        "半导体",
        "海南板块",
        "海南",
    )


def test_a_share_lexicon_includes_board_names():
    terms = set(known_terms())
    for term in ("半导体", "白酒", "人工智能", "光刻胶", "海南板块", "海南", "昨日涨停"):
        assert term in terms
    assert "白酒Ⅲ" not in terms
    assert "2026中报预增" not in terms
    assert sum(1 for term in terms if len(term) >= 2) >= 5000
