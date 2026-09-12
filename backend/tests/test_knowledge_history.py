from app.models import KnowledgeConversation
from app.services.knowledge_history import conversation_title, list_conversations, save_conversation


def test_conversation_title_uses_first_user_question():
    assert conversation_title([{"role": "assistant", "content": "hi"}, {"role": "user", "content": "  利率怎么看  "}]) == "利率怎么看"
    long_q = "这是一段非常长的问题" * 6
    titled = conversation_title([{"role": "user", "content": long_q}])
    assert titled.endswith("…")
    assert len(titled) == 41


def test_save_and_search_conversations(db_session):
    first = save_conversation(
        db_session,
        "",
        "a-share",
        [
            {"role": "user", "content": "茅台怎么看"},
            {"role": "assistant", "content": "量能放大可以低吸"},
        ],
    )
    save_conversation(
        db_session,
        "",
        "generic",
        [{"role": "user", "content": "这节课讲什么"}, {"role": "assistant", "content": "核心方法"}],
    )
    listed = list_conversations(db_session, "a-share")
    assert listed.total == 1
    assert listed.items[0].id == first.id
    assert listed.items[0].preview.startswith("量能放大")

    found = list_conversations(db_session, "a-share", q="低吸")
    assert found.total == 1
    assert list_conversations(db_session, "a-share", q="核心方法").total == 0
    assert list_conversations(db_session, "a-share", q="%").total == 0

    continued = save_conversation(
        db_session,
        first.id,
        "a-share",
        [
            {"role": "user", "content": "茅台怎么看"},
            {"role": "assistant", "content": "量能放大可以低吸"},
            {"role": "user", "content": "还有什么注意"},
            {"role": "assistant", "content": "别追高"},
        ],
    )
    assert continued.id == first.id
    assert continued.title == "茅台怎么看"
    assert continued.message_count == 4
    assert db_session.get(KnowledgeConversation, first.id).title == "茅台怎么看"


def test_rename_conversation(db_session):
    from app.services.knowledge_history import rename_conversation

    row = save_conversation(
        db_session,
        "",
        "a-share",
        [{"role": "user", "content": "茅台怎么看"}, {"role": "assistant", "content": "低吸"}],
    )
    renamed = rename_conversation(db_session, row.id, "  茅台复盘  ")
    assert renamed is not None
    assert renamed.title == "茅台复盘"
    assert rename_conversation(db_session, "missing", "x") is None
