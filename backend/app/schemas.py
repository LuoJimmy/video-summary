from datetime import datetime
from typing import Any, Literal

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
    transcribe_concurrency: int = 0
    transcribe_threads: int = 0
    transcribe_fast: bool = False
    ai_proofread: bool = True
    show_transcript: bool = True
    play_quota_mb: int = 0
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
    author: str = ""
    site_id: str | None = None
    auth_profile_id: str | None = None
    media_url_override: str = ""
    domain_id: str = ""
    summarize_document: bool = False
    cursor: str = ""


class JobRetryIn(BaseModel):
    media_url_override: str | None = None


class JobUpdateIn(BaseModel):
    title: str = Field(max_length=255)
    author: str | None = Field(default=None, max_length=120)


class TranscriptSegment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    locator: str = ""


class SummaryChapter(BaseModel):
    title: str
    start_segment: int
    end_segment: int
    start: float = 0
    end: float = 0
    locator: str = ""
    bullets: list[str] = Field(default_factory=list)


class SummaryKeyPoint(BaseModel):
    text: str
    start_segment: int
    end_segment: int
    start: float = 0
    end: float = 0
    locator: str = ""


class SummaryResult(BaseModel):
    title: str = ""
    overview: str = ""
    chapters: list[SummaryChapter] = Field(default_factory=list)
    key_points: list[SummaryKeyPoint] = Field(default_factory=list)


class JobRelatedOut(BaseModel):
    id: str
    title: str = ""
    author: str = ""
    status: str = ""


class JobOut(BaseModel):
    id: str
    title: str
    author: str = ""
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
    summarize_document: bool = False
    schedule_log_id: str = ""
    related_jobs: list[JobRelatedOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class JobListOut(BaseModel):
    items: list[JobOut]
    total: int
    page: int
    page_size: int


class JobBatchActionIn(BaseModel):
    action: Literal["cancel", "retry", "delete"]
    ids: list[str] = Field(min_length=1, max_length=100)


class JobDigestIn(BaseModel):
    ids: list[str] = Field(min_length=2, max_length=100)


class JobBatchFailedItem(BaseModel):
    id: str
    reason: str


class JobBatchActionOut(BaseModel):
    ok: list[str] = Field(default_factory=list)
    failed: list[JobBatchFailedItem] = Field(default_factory=list)


class JobMediaOut(BaseModel):
    url: str = ""
    refreshed: bool = False
    message: str = ""


class CatalogPreviewItem(BaseModel):
    source_url: str
    title: str = ""
    author: str = ""
    created_at: datetime | None = None
    exists: bool = False


class ResolvePreview(BaseModel):
    adapter: str
    title: str = ""
    source_type: str
    media_url: str = ""
    needs_media_url: bool = False
    message: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
    catalog: bool = False
    catalog_label: str = ""
    listed: int = 0
    existing: int = 0
    next_cursor: str = ""
    truncated: bool = False
    items: list[CatalogPreviewItem] = Field(default_factory=list)


class LocalEntryOut(BaseModel):
    name: str
    path: str
    kind: str = "file"
    size: int = 0
    modified_at: datetime | None = None
    supported: bool = False


class LocalEntriesOut(BaseModel):
    root: str = ""
    path: str = ""
    parent: str = ""
    recursive: bool = False
    query: str = ""
    page: int = 1
    page_size: int = 50
    total: int = 0
    entries: list[LocalEntryOut] = Field(default_factory=list)
    truncated: bool = False


class LocalRootOut(BaseModel):
    enabled: bool = False
    root: str = ""
    scan_limit: int = 1000


class JobCatalogIn(JobCreateIn):
    items: list[CatalogPreviewItem] = Field(min_length=1, max_length=200)
    next_cursor: str = ""
    truncated: bool = False
    catalog_label: str = ""


class JobCatalogOut(BaseModel):
    created: int = 0
    skipped: int = 0
    next_cursor: str = ""
    truncated: bool = False
    message: str = ""
    catalog_label: str = ""


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
    locator: str = ""


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
    citations: list[KnowledgeHit] = Field(default_factory=list)


class KnowledgeChatIn(BaseModel):
    messages: list[KnowledgeChatMessage] = Field(default_factory=list)
    domain_id: str = "a-share"
    conversation_id: str = ""


class KnowledgeChatOut(BaseModel):
    answer: str
    citations: list[KnowledgeHit] = Field(default_factory=list)
    conversation_id: str = ""
    title: str = ""


class KnowledgeConversationSummary(BaseModel):
    id: str
    domain_id: str
    title: str
    preview: str = ""
    updated_at: datetime
    created_at: datetime
    message_count: int = 0


class KnowledgeConversationOut(KnowledgeConversationSummary):
    messages: list[KnowledgeChatMessage] = Field(default_factory=list)


class KnowledgeConversationListOut(BaseModel):
    items: list[KnowledgeConversationSummary] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 30


class KnowledgeConversationRenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class PluginOut(BaseModel):
    id: str
    title: str
    description: str = ""
    size_hint: str = ""
    status: str
    error: str = ""
    soffice: str = ""


class StorageUsageOut(BaseModel):
    path: str = ""
    total_bytes: int = 0
    wav_bytes: int = 0
    wav_files: int = 0
    archive_bytes: int = 0
    archive_files: int = 0
    play_bytes: int = 0
    play_files: int = 0
    play_quota_bytes: int = 0
    source_bytes: int = 0
    other_bytes: int = 0
    orphan_dirs: int = 0


class StorageCleanupOut(BaseModel):
    removed_files: int = 0
    freed_bytes: int = 0
    usage: StorageUsageOut = Field(default_factory=StorageUsageOut)


class StorageArchiveOut(BaseModel):
    archived_files: int = 0
    saved_bytes: int = 0
    failed_files: int = 0
    usage: StorageUsageOut = Field(default_factory=StorageUsageOut)


class LexiconFix(BaseModel):
    wrong: str = ""
    right: str = ""


class LexiconIn(BaseModel):
    terms: list[str] = Field(default_factory=list)
    fixes: list[LexiconFix] = Field(default_factory=list)


class LexiconOut(LexiconIn):
    customized: bool = False
    preset: str = "a-share"


class ScheduleRuleSiteIn(BaseModel):
    site_id: str
    enabled: bool = False
    catalog_id: str = ""


class ScheduleRuleIn(BaseModel):
    name: str = ""
    enabled: bool = False
    time: str = "08:00"
    cron: str = ""
    max_jobs: int = 5
    domain_id: str = ""
    digest_enabled: bool = True
    sites: list[ScheduleRuleSiteIn] = Field(default_factory=list)


class ScheduleRuleSiteOut(BaseModel):
    site_id: str
    name: str
    adapter: str
    enabled: bool = False
    catalog_id: str = ""
    catalog_hint: str = ""


class ScheduleRuleOut(BaseModel):
    id: str
    name: str = ""
    enabled: bool = False
    time: str = "08:00"
    cron: str = ""
    cron_hint: str = ""
    next_run_at: datetime | None = None
    max_jobs: int = 5
    domain_id: str = ""
    digest_enabled: bool = True
    sites: list[ScheduleRuleSiteOut] = Field(default_factory=list)


class ScheduleLogSiteDetail(BaseModel):
    site_id: str = ""
    site_name: str = ""
    listed: int = 0
    created: int = 0
    skipped: int = 0
    error: str = ""


class ScheduleLogOut(BaseModel):
    id: str
    started_at: datetime
    finished_at: datetime | None = None
    trigger: str = "cron"
    status: str = "ok"
    summary: str = ""
    detail: list[ScheduleLogSiteDetail] = Field(default_factory=list)
    digest_job_id: str = ""
    rule_id: str = ""
    rule_name: str = ""
