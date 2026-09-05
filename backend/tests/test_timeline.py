from app.schemas import SummaryChapter, SummaryKeyPoint, SummaryResult, TranscriptSegment
from app.services.summarize import _chunk_segments, stitch_partials
from app.services.timeline import attach_timestamps, format_ts, format_video_clock, indexed_transcript


def test_format_ts():
    assert format_ts(75) == "01:15"
    assert format_ts(3723) == "01:02:03"


def test_format_video_clock_always_has_hours():
    assert format_video_clock(569) == "00:09:29"
    assert format_video_clock(3723) == "01:02:03"


def test_attach_timestamps_uses_segment_index_not_model_clock():
    segments = [
        TranscriptSegment(id=0, start=10, end=20, text="开场"),
        TranscriptSegment(id=1, start=20, end=40, text="策略"),
        TranscriptSegment(id=2, start=40, end=55, text="风险"),
    ]
    summary = SummaryResult(
        title="测试",
        overview="概述",
        chapters=[SummaryChapter(title="策略段", start_segment=1, end_segment=2, bullets=["要点"])],
        key_points=[SummaryKeyPoint(text="风险提示", start_segment=2, end_segment=2)],
    )
    mapped = attach_timestamps(summary, segments)
    assert mapped.chapters[0].start == 20
    assert mapped.chapters[0].end == 55
    assert mapped.key_points[0].start == 40
    assert mapped.key_points[0].end == 55


def test_attach_timestamps_clamps_out_of_range():
    segments = [TranscriptSegment(id=0, start=0, end=5, text="a")]
    summary = SummaryResult(
        chapters=[SummaryChapter(title="x", start_segment=9, end_segment=12)],
    )
    mapped = attach_timestamps(summary, segments)
    assert mapped.chapters[0].start_segment == 0
    assert mapped.chapters[0].end == 5


def test_attach_timestamps_maps_by_segment_id_not_list_index():
    segments = [TranscriptSegment(id=i, start=float(i), end=float(i + 1), text=f"s{i}") for i in range(200)]
    segments[156] = TranscriptSegment(id=156, start=760.8, end=763.2, text="错位")
    target = TranscriptSegment(id=851, start=3056.0, end=3059.0, text="航天小商业航天是吧？")
    segments.append(target)
    summary = SummaryResult(
        chapters=[SummaryChapter(title="商业航天", start_segment=851, end_segment=851, bullets=["航天"])],
    )
    mapped = attach_timestamps(summary, segments)
    assert mapped.chapters[0].start == 3056.0
    assert mapped.chapters[0].end == 3059.0
    assert mapped.chapters[0].start_segment == 851
    assert mapped.chapters[0].start != 760.8


def test_indexed_transcript_hides_raw_clock():
    text = indexed_transcript([TranscriptSegment(id=0, start=12.3, end=15, text="你好")])
    assert text == "[0] 你好"
    assert "12" not in text


def test_chunk_segments_keeps_global_ids():
    segments = [TranscriptSegment(id=i, start=i, end=i + 1, text="字" * 20) for i in range(6)]
    chunks = _chunk_segments(segments, max_chars=50)
    assert len(chunks) >= 2
    assert chunks[0][0].id == 0
    assert chunks[-1][-1].id == 5


def test_stitch_partials_keeps_later_chapters():
    early = SummaryResult(
        title="前半",
        chapters=[SummaryChapter(title="开场", start_segment=0, end_segment=10, bullets=["介绍"])],
        key_points=[SummaryKeyPoint(text="问题", start_segment=2, end_segment=2)],
    )
    late = SummaryResult(
        title="后半",
        chapters=[
            SummaryChapter(title="AI算力案例", start_segment=80, end_segment=110, bullets=["龙头"]),
            SummaryChapter(title="创新药案例", start_segment=120, end_segment=150, bullets=["突破"]),
        ],
        key_points=[SummaryKeyPoint(text="案例", start_segment=90, end_segment=90)],
    )
    chapters, points = stitch_partials([early, late])
    assert [item.title for item in chapters] == ["开场", "AI算力案例", "创新药案例"]
    assert chapters[-1].start_segment == 120
    assert len(points) == 2
    assert points[-1].start_segment == 90
