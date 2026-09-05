from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuthProfileIn(BaseModel):
    name: str
    cookie: str = ""
    extra_headers: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


class AuthProfileOut(BaseModel):
    id: str
    name: str
    cookie: str
    extra_headers: dict[str, str]
    notes: str
    created_at: datetime
    updated_at: datetime


class SiteIn(BaseModel):
    name: str
    adapter: str = "generic"
    domain_patterns: list[str] = Field(default_factory=list)
    auth_profile_id: str | None = None
    cookie_override: str = ""
    extra_headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    notes: str = ""


class SiteOut(BaseModel):
    id: str
    name: str
    adapter: str
    domain_patterns: list[str]
    auth_profile_id: str | None
    cookie_override: str
    extra_headers: dict[str, str]
    enabled: bool
    notes: str
    created_at: datetime
    updated_at: datetime


class DomainPack(BaseModel):
    id: str = "a-share"
    base_preset: str = "a-share"
    name: str = "A股盘面课"
    asr_hint: str = ""
    chapter_focus: str = ""
    term_aliases: str = ""
    overview_role: str = ""
    overview_stance: str = ""
    disclaimer: str = ""
    knowledge_role: str = ""
    knowledge_guardrails: str = ""
    example_questions: list[str] = Field(default_factory=list)
    content_keywords: list[str] = Field(default_factory=list)
    highlight_phrases: list[str] = Field(default_factory=list)
    highlight_stock_codes: bool = True
    proofread_hint: str = ""
    chapter_prompt_override: str = ""
    overview_prompt_override: str = ""
    knowledge_prompt_override: str = ""


class AppSettingsIn(BaseModel):
    transcribe_base_url: str = ""
    transcribe_api_key: str = ""
    transcribe_model: str = ""
    summarize_base_url: str = ""
    summarize_api_key: str = ""
    summarize_model: str = ""
    capture_seconds: str = "180"
    summarize_concurrency: int = 3
    transcribe_threads: int = 0
    transcribe_fast: bool = False
    ai_proofread: bool = True
    show_transcript: bool = True
    domain_pack: DomainPack | None = None


class AppSettingsOut(AppSettingsIn):
    cpu_count: int = 0
    domain_pack: DomainPack = Field(default_factory=DomainPack)
    domain_presets: list[DomainPack] = Field(default_factory=list)


class DomainPresetCreateIn(BaseModel):
    source_id: str = ""
    name: str = ""


class JobCreateIn(BaseModel):
    source_url: str = ""
    title: str = ""
    site_id: str | None = None
    auth_profile_id: str | None = None
    media_url_override: str = ""
    domain_id: str = ""


class JobUpdateIn(BaseModel):
    title: str = Field(max_length=255)


class TranscriptSegment(BaseModel):
    id: int
    start: float
    end: float
    text: str


class SummaryChapter(BaseModel):
    title: str
    start_segment: int
    end_segment: int
    start: float = 0
    end: float = 0
    bullets: list[str] = Field(default_factory=list)


class SummaryKeyPoint(BaseModel):
    text: str
    start_segment: int
    end_segment: int
    start: float = 0
    end: float = 0


class SummaryResult(BaseModel):
    title: str = ""
    overview: str = ""
    chapters: list[SummaryChapter] = Field(default_factory=list)
    key_points: list[SummaryKeyPoint] = Field(default_factory=list)


class JobOut(BaseModel):
    id: str
    title: str
    source_url: str
    source_type: str
    site_id: str | None
    auth_profile_id: str | None
    domain_id: str = ""
    media_url: str
    media_url_override: str
    status: str
    stage: str
    progress: int
    error: str
    transcript: list[TranscriptSegment] = Field(default_factory=list)
    summary: SummaryResult | None = None
    timing: dict[str, float] = Field(default_factory=dict)
    started_at: datetime | None = None
    source_created_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class JobListOut(BaseModel):
    items: list[JobOut]
    total: int
    page: int
    page_size: int


class JobMediaOut(BaseModel):
    url: str = ""
    refreshed: bool = False
    message: str = ""


class ResolvePreview(BaseModel):
    adapter: str
    title: str = ""
    source_type: str
    media_url: str = ""
    needs_media_url: bool = False
    message: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class KnowledgeDoc(BaseModel):
    job_id: str
    title: str
    source_url: str = ""
    status: str = ""
    segment_count: int = 0
    updated_at: datetime | None = None
    preview: str = ""


class KnowledgeHit(BaseModel):
    job_id: str
    title: str
    kind: str
    kind_label: str = ""
    text: str
    snippet: str
    start: float = 0
    end: float = 0
    segment_id: int | None = None


class KnowledgeSearchOut(BaseModel):
    query: str = ""
    job_count: int = 0
    hit_count: int = 0
    documents: list[KnowledgeDoc] = Field(default_factory=list)
    hits: list[KnowledgeHit] = Field(default_factory=list)
    page: int = 1
    page_size: int = 20


class KnowledgeChatMessage(BaseModel):
    role: str
    content: str


class KnowledgeChatIn(BaseModel):
    messages: list[KnowledgeChatMessage] = Field(default_factory=list)
    domain_id: str = "a-share"


class KnowledgeChatOut(BaseModel):
    answer: str
    citations: list[KnowledgeHit] = Field(default_factory=list)


class LexiconFix(BaseModel):
    wrong: str = ""
    right: str = ""


class LexiconIn(BaseModel):
    terms: list[str] = Field(default_factory=list)
    fixes: list[LexiconFix] = Field(default_factory=list)


class LexiconOut(LexiconIn):
    customized: bool = False
    preset: str = "a-share"
