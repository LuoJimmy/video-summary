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
    bullets: string[];
  }>;
  key_points: Array<{
    text: string;
    start_segment: number;
    end_segment: number;
    start: number;
    end: number;
  }>;
};

export type Job = {
  id: string;
  title: string;
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
  created_at: string;
  updated_at: string;
};

export type JobList = {
  items: Job[];
  total: number;
  page: number;
  page_size: number;
};

export type ResolvePreview = {
  adapter: string;
  title: string;
  source_type: string;
  media_url: string;
  needs_media_url: boolean;
  message: string;
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
    throw new Error(text || response.statusText);
  }
  return response.json() as Promise<T>;
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
  updateJob: (id: string, payload: { title: string }) =>
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
  uploadJob: (file: File, title: string, domainId = "a-share") => {
    const body = new FormData();
    body.append("file", file);
    body.append("title", title);
    body.append("domain_id", domainId || "a-share");
    if (file.lastModified)
      body.append("source_created_at", String(file.lastModified));
    return request<Job>("/api/jobs/upload", { method: "POST", body });
  },
  retryJob: (id: string) =>
    request<Job>(`/api/jobs/${id}/retry`, { method: "POST" }),
  cancelJob: (id: string) =>
    request<Job>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  deleteJob: (id: string) =>
    request<{ ok: boolean }>(`/api/jobs/${id}`, { method: "DELETE" }),
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
    messages: Array<{ role: string; content: string }>,
    domainId = "a-share"
  ) =>
    request<KnowledgeChatOut>("/api/knowledge/chat", {
      method: "POST",
      body: JSON.stringify({ messages, domain_id: domainId }),
    }),
};
