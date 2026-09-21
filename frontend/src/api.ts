import type { DomainPack } from "./utils/domain";

export type AuthProfile = {
  id: string;
  name: string;
  cookie: string;
  extra_headers: Record<string, string>;
  notes: string;
};

export type Site = {
  id: string;
  name: string;
  adapter: string;
  domain_patterns: string[];
  auth_profile_id: string | null;
  cookie_override: string;
  extra_headers: Record<string, string>;
  enabled: boolean;
  notes: string;
};

export type AppSettings = {
  transcribe_base_url: string;
  transcribe_api_key: string;
  transcribe_model: string;
  summarize_base_url: string;
  summarize_api_key: string;
  summarize_model: string;
  capture_seconds: string;
  summarize_concurrency: number;
  transcribe_threads: number;
  transcribe_fast: boolean;
  cpu_count?: number;
  ai_proofread: boolean;
  show_transcript: boolean;
  domain_pack?: DomainPack;
  domain_presets?: DomainPack[];
};

export type LexiconFix = {
  wrong: string;
  right: string;
};

export type Lexicon = {
  terms: string[];
  fixes: LexiconFix[];
  customized: boolean;
  preset?: string;
};

export type TranscriptSegment = {
  id: number;
  start: number;
  end: number;
  text: string;
  locator?: string;
};

export type SummaryResult = {
  title: string;
  overview: string;
  chapters: Array<{
    title: string;
    start_segment: number;
    end_segment: number;
    start: number;
    end: number;
    locator?: string;
    bullets: string[];
  }>;
  key_points: Array<{
    text: string;
    start_segment: number;
    end_segment: number;
    start: number;
    end: number;
    locator?: string;
  }>;
};

export type JobRelated = {
  id: string;
  title: string;
  author: string;
  status: string;
};

export type Job = {
  id: string;
  title: string;
  author: string;
  source_url: string;
  source_type: string;
  site_id: string | null;
  auth_profile_id: string | null;
  domain_id?: string;
  media_url: string;
  media_url_override: string;
  status: string;
  stage: string;
  progress: number;
  error: string;
  transcript: TranscriptSegment[];
  summary: SummaryResult | null;
  timing: Record<string, number>;
  started_at: string | null;
  source_created_at: string | null;
  summarize_document?: boolean;
  schedule_log_id?: string;
  related_jobs?: JobRelated[];
  created_at: string;
  updated_at: string;
};

export type JobList = {
  items: Job[];
  total: number;
  page: number;
  page_size: number;
};

export type JobBatchAction = "cancel" | "retry" | "delete";

export type JobBatchResult = {
  ok: string[];
  failed: Array<{ id: string; reason: string }>;
};

export type LocalEntry = {
  name: string;
  path: string;
  kind: string;
  size: number;
  modified_at: string | null;
  supported: boolean;
};

export type LocalEntries = {
  root: string;
  path: string;
  parent: string;
  recursive: boolean;
  query: string;
  page: number;
  page_size: number;
  total: number;
  entries: LocalEntry[];
  truncated: boolean;
};

export type LocalRoot = {
  enabled: boolean;
  root: string;
  scan_limit: number;
};

export type LocalPick = { path: string; name: string };

export type CatalogPreviewItem = {
  source_url: string;
  title: string;
  author: string;
  created_at: string | null;
  exists: boolean;
};

export type ResolvePreview = {
  adapter: string;
  title: string;
  source_type: string;
  media_url: string;
  needs_media_url: boolean;
  message: string;
  extra?: Record<string, unknown>;
  catalog?: boolean;
  catalog_label?: string;
  listed?: number;
  existing?: number;
  next_cursor?: string;
  truncated?: boolean;
  items?: CatalogPreviewItem[];
};

export type JobCatalogResult = {
  created: number;
  skipped: number;
  next_cursor: string;
  truncated: boolean;
  message: string;
  catalog_label: string;
};

export type KnowledgeDoc = {
  job_id: string;
  title: string;
  source_url: string;
  status: string;
  segment_count: number;
  updated_at: string | null;
  preview: string;
};

export type KnowledgeHit = {
  job_id: string;
  title: string;
  kind: string;
  kind_label: string;
  text: string;
  snippet: string;
  start: number;
  end: number;
  segment_id: number | null;
  locator?: string;
};

export type KnowledgeSearch = {
  query: string;
  job_count: number;
  hit_count: number;
  documents: KnowledgeDoc[];
  hits: KnowledgeHit[];
  page: number;
  page_size: number;
};

export type KnowledgeChatOut = {
  answer: string;
  citations: KnowledgeHit[];
  conversation_id: string;
  title: string;
};

export type KnowledgeConversationSummary = {
  id: string;
  domain_id: string;
  title: string;
  preview: string;
  updated_at: string;
  created_at: string;
  message_count: number;
};

export type KnowledgeConversation = KnowledgeConversationSummary & {
  messages: Array<{
    role: "user" | "assistant";
    content: string;
    citations?: KnowledgeHit[];
  }>;
};

export type KnowledgeConversationList = {
  items: KnowledgeConversationSummary[];
  total: number;
  page: number;
  page_size: number;
};

export type ScheduleSite = {
  site_id: string;
  name: string;
  adapter: string;
  enabled: boolean;
  catalog_id: string;
  catalog_hint: string;
};

export type ScheduleConfig = {
  enabled: boolean;
  time: string;
  since: string;
  max_jobs: number;
  domain_id: string;
  digest_enabled: boolean;
  sites: ScheduleSite[];
};

export type ScheduleLogDetail = {
  site_id: string;
  site_name: string;
  listed: number;
  created: number;
  skipped: number;
  error: string;
};

export type ScheduleLog = {
  id: string;
  started_at: string;
  finished_at: string | null;
  trigger: string;
  status: string;
  summary: string;
  detail: ScheduleLogDetail[];
  digest_job_id: string;
};

export type PluginInfo = {
  id: string;
  title: string;
  description: string;
  size_hint: string;
  status: string;
  error: string;
  soffice: string;
};

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(apiErrorMessage(text || response.statusText));
  }
  return response.json() as Promise<T>;
}

export function apiErrorMessage(err: unknown, fallback = "请求失败"): string {
  const raw =
    err instanceof Error ? err.message : typeof err === "string" ? err : "";
  const text = raw.trim();
  if (!text) return fallback;
  try {
    const payload = JSON.parse(text) as { detail?: unknown };
    if (typeof payload?.detail === "string" && payload.detail.trim()) {
      return payload.detail.trim();
    }
  } catch {
    /* 已是可读错误文案 */
  }
  return text;
}

export const api = {
  profiles: () => request<AuthProfile[]>("/api/profiles"),
  saveProfile: (payload: Omit<AuthProfile, "id">, id?: string) =>
    request<AuthProfile>(id ? `/api/profiles/${id}` : "/api/profiles", {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(payload),
    }),
  deleteProfile: (id: string) =>
    request(`/api/profiles/${id}`, { method: "DELETE" }),
  sites: () => request<Site[]>("/api/sites"),
  saveSite: (payload: Omit<Site, "id">, id?: string) =>
    request<Site>(id ? `/api/sites/${id}` : "/api/sites", {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(payload),
    }),
  deleteSite: (id: string) => request(`/api/sites/${id}`, { method: "DELETE" }),
  settings: () => request<AppSettings>("/api/settings"),
  saveSettings: (payload: AppSettings) =>
    request<AppSettings>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  saveDomainPack: (pack: DomainPack) =>
    request<AppSettings>("/api/settings", {
      method: "PUT",
      body: JSON.stringify({ domain_pack: pack }),
    }),
  addDomainPreset: (sourceId?: string, name?: string) =>
    request<AppSettings>("/api/settings/domain-presets", {
      method: "POST",
      body: JSON.stringify({
        source_id: sourceId || "",
        name: name || "",
      }),
    }),
  deleteDomainPreset: (presetId: string) =>
    request<AppSettings>(
      `/api/settings/domain-presets/${encodeURIComponent(presetId)}`,
      { method: "DELETE" }
    ),
  lexicon: (preset?: string) => {
    const query = preset ? `?preset=${encodeURIComponent(preset)}` : "";
    return request<Lexicon>(`/api/lexicon${query}`);
  },
  saveLexicon: (
    payload: { terms: string[]; fixes: LexiconFix[] },
    preset?: string
  ) => {
    const query = preset ? `?preset=${encodeURIComponent(preset)}` : "";
    return request<Lexicon>(`/api/lexicon${query}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  resetLexicon: (preset?: string) => {
    const query = preset ? `?preset=${encodeURIComponent(preset)}` : "";
    return request<Lexicon>(`/api/lexicon/reset${query}`, { method: "POST" });
  },
  jobs: (
    page = 1,
    pageSize = 10,
    filters: {
      title?: string;
      status?: string;
      dateFrom?: string;
      dateTo?: string;
      sort?: string;
      order?: string;
    } = {}
  ) => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    if (filters.title) params.set("title", filters.title);
    if (filters.status) params.set("status", filters.status);
    if (filters.dateFrom) params.set("date_from", filters.dateFrom);
    if (filters.dateTo) params.set("date_to", filters.dateTo);
    if (filters.sort) params.set("sort", filters.sort);
    if (filters.order) params.set("order", filters.order);
    return request<JobList>(`/api/jobs?${params}`);
  },
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  updateJob: (id: string, payload: { title: string; author?: string }) =>
    request<Job>(`/api/jobs/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  createJob: (payload: Record<string, unknown>) =>
    request<Job>("/api/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  preview: (payload: Record<string, unknown>) =>
    request<ResolvePreview>("/api/jobs/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  fromCatalog: (payload: Record<string, unknown>) =>
    request<JobCatalogResult>("/api/jobs/from-catalog", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  uploadJob: (
    file: File,
    title: string,
    domainId = "a-share",
    author = "",
    summarizeDocument = false
  ) => {
    const body = new FormData();
    body.append("file", file);
    body.append("title", title);
    body.append("author", author);
    body.append("domain_id", domainId || "a-share");
    body.append("summarize_document", summarizeDocument ? "true" : "false");
    if (file.lastModified)
      body.append("source_created_at", String(file.lastModified));
    return request<Job>("/api/jobs/upload", { method: "POST", body });
  },
  localRoot: () => request<LocalRoot>("/api/jobs/local-root"),
  localEntries: (
    path = "",
    options: {
      recursive?: boolean;
      query?: string;
      page?: number;
      pageSize?: number;
    } = {}
  ) => {
    const params = new URLSearchParams();
    if (path) params.set("path", path);
    if (options.query) params.set("query", options.query);
    if (options.recursive) params.set("recursive", "true");
    if (options.page) params.set("page", String(options.page));
    if (options.pageSize) params.set("page_size", String(options.pageSize));
    const query = params.toString();
    return request<LocalEntries>(
      `/api/jobs/local-entries${query ? `?${query}` : ""}`
    );
  },
  retryJob: (id: string, payload?: { media_url_override?: string }) =>
    request<Job>(`/api/jobs/${id}/retry`, {
      method: "POST",
      body: payload ? JSON.stringify(payload) : undefined,
    }),
  cancelJob: (id: string) =>
    request<Job>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  deleteJob: (id: string) =>
    request<{ ok: boolean }>(`/api/jobs/${id}`, { method: "DELETE" }),
  batchJobs: (action: JobBatchAction, ids: string[]) =>
    request<JobBatchResult>("/api/jobs/batch", {
      method: "POST",
      body: JSON.stringify({ action, ids }),
    }),
  digestJobs: (ids: string[]) =>
    request<Job>("/api/jobs/digest", {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),
  resummarizeJob: (id: string) =>
    request<Job>(`/api/jobs/${id}/resummarize`, { method: "POST" }),
  proofreadJob: (id: string) =>
    request<Job>(`/api/jobs/${id}/proofread`, { method: "POST" }),
  retranscribeJob: (id: string) =>
    request<Job>(`/api/jobs/${id}/retranscribe`, { method: "POST" }),
  jobMedia: (id: string) =>
    request<{ url: string; refreshed: boolean; message: string }>(
      `/api/jobs/${id}/media`
    ),
  knowledge: (q = "", domainId = "a-share", page = 1, pageSize = 10) => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    if (q) params.set("q", q);
    if (domainId) params.set("domain_id", domainId);
    return request<KnowledgeSearch>(`/api/knowledge?${params}`);
  },
  knowledgeChat: (
    messages: Array<{
      role: string;
      content: string;
      citations?: KnowledgeHit[];
    }>,
    domainId = "a-share",
    conversationId = ""
  ) =>
    request<KnowledgeChatOut>("/api/knowledge/chat", {
      method: "POST",
      body: JSON.stringify({
        messages,
        domain_id: domainId,
        conversation_id: conversationId,
      }),
    }),
  knowledgeConversations: (
    q = "",
    domainId = "a-share",
    page = 1,
    pageSize = 30
  ) => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
      domain_id: domainId,
    });
    if (q) params.set("q", q);
    return request<KnowledgeConversationList>(
      `/api/knowledge/conversations?${params}`
    );
  },
  knowledgeConversation: (id: string) =>
    request<KnowledgeConversation>(`/api/knowledge/conversations/${id}`),
  renameKnowledgeConversation: (id: string, title: string) =>
    request<KnowledgeConversation>(`/api/knowledge/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteKnowledgeConversation: (id: string) =>
    request<{ ok: boolean }>(`/api/knowledge/conversations/${id}`, {
      method: "DELETE",
    }),
  schedule: () => request<ScheduleConfig>("/api/schedule"),
  saveSchedule: (payload: ScheduleConfig) =>
    request<ScheduleConfig>("/api/schedule", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  runSchedule: () =>
    request<ScheduleLog>("/api/schedule/run?wait=false", { method: "POST" }),
  scheduleLogs: (limit = 20) =>
    request<ScheduleLog[]>(`/api/schedule/logs?limit=${limit}`),
  clearScheduleLogs: () =>
    request<{ ok: boolean }>("/api/schedule/logs", { method: "DELETE" }),
  plugins: () => request<PluginInfo[]>("/api/plugins"),
  installPlugin: (id: string) =>
    request<PluginInfo>(`/api/plugins/${id}/install`, { method: "POST" }),
  cancelPlugin: (id: string) =>
    request<PluginInfo>(`/api/plugins/${id}/cancel`, { method: "POST" }),
  uninstallPlugin: (id: string) =>
    request<PluginInfo>(`/api/plugins/${id}/uninstall`, { method: "POST" }),
};
