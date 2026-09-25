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


def test_retrieve_document_uses_locator_not_clock():
    job = Job(
        id="doc1",
        title="研报",
        status="done",
        transcript_json=dumps(
            [{"id": 0, "start": 0, "end": 0, "text": "利率下行对估值有支撑", "locator": "第3页"}]
        ),
    )
    hits = retrieve([job], "利率估值", limit=5)
    assert hits
    assert hits[0].locator == "第3页"
    from app.services.knowledge import _format_context

    context = _format_context(hits)
    assert "第3页" in context
    assert "00:00" not in context


def test_digest_job_is_excluded_from_knowledge():
    digest = Job(
        id="digest1",
        title="2026-09-16 08:00 定时汇总",
        status="done",
        source_type="schedule_digest",
        source_url="",
        transcript_json="",
        summary_json=dumps(
            {
                "title": "定时汇总",
                "overview": "低吸要等收敛，卖票先看分时走弱",
                "chapters": [],
                "key_points": [],
            }
        ),
    )
    source = _job()
    listed = search_knowledge([digest, source])
    assert [item.job_id for item in listed.documents] == ["job1"]
    assert retrieve([digest, source], "低吸收敛", limit=5) == []
    hits = retrieve([digest, source], "卖票", limit=5)
    assert hits
    assert all(item.job_id != "digest1" for item in hits)
    manual = Job(
        id="digest2",
        title="2026-09-17 11:00 汇总",
        status="done",
        source_type="digest",
        source_url="digest://job1",
        transcript_json="",
        summary_json=digest.summary_json,
    )
    assert [item.job_id for item in search_knowledge([manual, source]).documents] == ["job1"]
    assert all(item.job_id != "digest2" for item in retrieve([manual, source], "卖票", limit=5))


def test_retrieve_reuses_chunk_index_between_queries(monkeypatch):
    import app.services.knowledge as knowledge

    job = _job()
    assert retrieve([job], "卖票的方法是什么", limit=5)

    calls: list[str] = []
    real = knowledge._chunks_for_job

    def counting(item):
        calls.append(item.id)
        return real(item)

    monkeypatch.setattr(knowledge, "_chunks_for_job", counting)
    hits = retrieve([job], "分时走弱", limit=5)
    assert calls == []
    assert hits and hits[0].job_id == "job1"


def test_chunk_index_rebuilds_after_transcript_changes():
    job = _job()
    assert retrieve([job], "分时走弱", limit=5)
    job.transcript_json = dumps([{"id": 0, "start": 0, "end": 5, "text": "现在只讲低吸反包"}])
    assert retrieve([job], "分时走弱", limit=5) == []
    hits = retrieve([job], "低吸反包", limit=5)
    assert hits and hits[0].job_id == "job1"


def test_chunk_index_rebuilds_after_title_changes():
    job = _job()
    hits = retrieve([job], "手机炒股", limit=5)
    assert hits and hits[0].kind == "title"
    job.title = "半导体专场"
    hits = retrieve([job], "半导体专场", limit=5)
    assert hits and hits[0].kind == "title"
    assert all(item.kind != "title" for item in retrieve([job], "手机炒股", limit=5))


def test_chunk_index_evicts_least_recently_used(monkeypatch):
    import app.services.knowledge as knowledge

    monkeypatch.setattr(knowledge, "MAX_INDEX_JOBS", 1)
    first = _job()
    second = _job()
    second.id = "job2"
    assert retrieve([first], "卖票", limit=5)

    calls: list[str] = []
    real = knowledge._chunks_for_job

    def counting(item):
        calls.append(item.id)
        return real(item)

    monkeypatch.setattr(knowledge, "_chunks_for_job", counting)
    assert retrieve([second], "卖票", limit=5)
    assert calls == ["job2"]
    assert retrieve([first], "卖票", limit=5)
    assert calls == ["job2", "job1"]


def test_search_knowledge_builds_docs_only_for_hits(monkeypatch):
    import app.services.knowledge as knowledge

    jobs = [
        Job(
            id=f"job{index}",
            title=f"课{index}",
            status="done",
            transcript_json=dumps([{"id": 0, "start": 0, "end": 5, "text": text}]),
        )
        for index, text in enumerate(["讲分时走弱", "讲低吸", "讲卖票"], start=1)
    ]
    built: list[str] = []
    real = knowledge._doc

    def counting(job):
        built.append(job.id)
        return real(job)

    monkeypatch.setattr(knowledge, "_doc", counting)
    out = search_knowledge(jobs, "分时走弱", page=1, page_size=20)
    assert built == ["job1"]
    assert [item.job_id for item in out.documents] == ["job1"]
    assert out.job_count == 1
