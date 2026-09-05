from app.schemas import SummaryChapter, SummaryKeyPoint, SummaryResult, TranscriptSegment


def format_ts(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_video_clock(seconds: float) -> str:
    """综述用的片子时钟，始终带小时，避免 09:29 被看成开盘时刻。"""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def clamp_index(index: int, size: int) -> int:
    if size <= 0:
        return 0
    return min(max(index, 0), size - 1)


def attach_timestamps(summary: SummaryResult, segments: list[TranscriptSegment]) -> SummaryResult:
    size = len(segments)
    by_id = {item.id: index for index, item in enumerate(segments)}

    def resolve_index(ref: int) -> int:
        if ref in by_id:
            return by_id[ref]
        return clamp_index(ref, size)

    def bounds(start_segment: int, end_segment: int) -> tuple[float, float, int, int]:
        start_i = resolve_index(start_segment)
        end_i = resolve_index(end_segment)
        if end_i < start_i:
            start_i, end_i = end_i, start_i
        if not segments:
            return 0.0, 0.0, start_segment, end_segment
        start_seg = segments[start_i]
        end_seg = segments[end_i]
        return start_seg.start, end_seg.end, start_seg.id, end_seg.id

    chapters: list[SummaryChapter] = []
    for chapter in summary.chapters:
        start, end, start_i, end_i = bounds(chapter.start_segment, chapter.end_segment)
        chapters.append(
            chapter.model_copy(
                update={
                    "start": start,
                    "end": end,
                    "start_segment": start_i,
                    "end_segment": end_i,
                }
            )
        )

    points: list[SummaryKeyPoint] = []
    for point in summary.key_points:
        start, end, start_i, end_i = bounds(point.start_segment, point.end_segment)
        points.append(
            point.model_copy(
                update={
                    "start": start,
                    "end": end,
                    "start_segment": start_i,
                    "end_segment": end_i,
                }
            )
        )

    return summary.model_copy(update={"chapters": chapters, "key_points": points})


def indexed_transcript(segments: list[TranscriptSegment]) -> str:
    lines: list[str] = []
    for segment in segments:
        lines.append(f"[{segment.id}] {segment.text.strip()}")
    return "\n".join(lines)
