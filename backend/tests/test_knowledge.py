from app.models import Job
from app.schemas import AppSettingsOut
from app.services.jsonutil import dumps
from app.services.knowledge import answer_from_knowledge, jobs_in_domain, retrieve, search_knowledge


def _job() -> Job:
    return Job(
        id="job1",
        title="手机炒股核心卖票方法",
        status="done",
        transcript_json=dumps(
            [
                {"id": 0, "start": 12, "end": 20, "text": "卖票先看分时有没有走弱，再决定是否挂条件单"},
                {"id": 1, "start": 20, "end": 28, "text": "今天重点看贵州茅台的量能"},
            ]
        ),
        summary_json=dumps({"title": "卖票", "overview": "讲解卖票方法", "chapters": [], "key_points": []}),
    )


def test_retrieve_matches_question_not_just_exact_phrase():
    hits = retrieve([_job()], "卖票的方法是什么", limit=5)
    assert hits
    assert any("卖票" in item.text for item in hits)


def test_answer_uses_private_context(monkeypatch):
    settings = AppSettingsOut(summarize_api_key="k", summarize_model="demo")
    captured = {}

    def fake_complete(_settings, messages):
        captured["messages"] = messages
        return "根据资料，**卖票**要先看分时是否走弱。"

    answer, citations = answer_from_knowledge(
        [_job()],
        [{"role": "user", "content": "卖票方法是什么"}],
        settings,
        completer=fake_complete,
    )
    assert "卖票" in answer
    assert citations
    assert "【资料】" in captured["messages"][0]["content"]
    assert "分时" in captured["messages"][0]["content"]


def test_jobs_in_domain_keeps_legacy_empty_as_ashare():
    ashare = _job()
    generic = Job(
        id="job2",
        title="通用课",
        status="done",
        domain_id="generic",
        transcript_json=ashare.transcript_json,
    )
    assert [item.id for item in jobs_in_domain([ashare, generic], "a-share")] == ["job1"]
    assert [item.id for item in jobs_in_domain([ashare, generic], "generic")] == ["job2"]


def test_search_knowledge_paginates_documents():
    jobs = [
        Job(
            id=f"job{index}",
            title=f"课{index}",
            status="done",
            source_url="",
            transcript_json=dumps([{"id": 0, "start": 0, "end": 8, "text": f"内容{index}"}]),
        )
        for index in range(1, 4)
    ]
    listed = search_knowledge(jobs, page=2, page_size=2)
    assert listed.job_count == 3
    assert listed.page == 2
    assert listed.page_size == 2
    assert [item.title for item in listed.documents] == ["课3"]

    paged = search_knowledge(jobs[:2], page=1, page_size=2, total=3)
    assert paged.job_count == 3
    assert [item.title for item in paged.documents] == ["课1", "课2"]
