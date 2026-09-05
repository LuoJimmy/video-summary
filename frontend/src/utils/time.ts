export const STAGE_TIME_LABELS: Record<string, string> = {
  resolving: "解析媒体",
  extracting: "抽取音频",
  transcribing: "转写",
  proofreading: "校对转写",
  summarizing: "总结",
  total: "总计",
};

export function isJobActive(status: string): boolean {
  return status === "pending" || status === "running";
}

function parseUtcMillis(iso: string): number {
  const raw = (iso || "").trim();
  if (!raw) return Number.NaN;
  if (/Z$|[+-]\d{2}:\d{2}$/.test(raw)) return Date.parse(raw);
  return Date.parse(`${raw}Z`);
}

export function jobElapsedSeconds(
  job: { started_at?: string | null; created_at: string },
  nowMs: number
): number {
  const start = parseUtcMillis(job.started_at || job.created_at);
  if (!Number.isFinite(start)) return 0;
  return Math.max(0, Math.floor((nowMs - start) / 1000));
}

export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) {
    return `${hours}小时${minutes}分${secs}秒`;
  }
  if (minutes > 0) {
    return `${minutes}分${secs}秒`;
  }
  return `${secs}秒`;
}

export function formatDateTime(iso: string | null | undefined): string {
  const ms = parseUtcMillis(iso || "");
  if (!Number.isFinite(ms)) return "";
  const date = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function localDayBoundIso(date: string, endExclusive = false): string {
  const raw = (date || "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return "";
  const start = Date.parse(`${raw}T00:00:00`);
  if (!Number.isFinite(start)) return "";
  if (!endExclusive) return new Date(start).toISOString();
  const next = new Date(start);
  next.setDate(next.getDate() + 1);
  return next.toISOString();
}

export function formatDateStamp(iso: string | null | undefined): string {
  const ms = parseUtcMillis(iso || "");
  if (!Number.isFinite(ms)) return "";
  const date = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}`;
}

export function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) {
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

export function statusLabel(status: string, stage: string): string {
  if (status === "done") return "已完成";
  if (status === "failed") return "失败";
  if (status === "cancelled") return "已取消";
  const stages: Record<string, string> = {
    queued: "排队中",
    resolving: "解析媒体",
    extracting: "抽取音频",
    transcribing: "转写中",
    proofreading: "校对转写",
    summarizing: "总结中",
  };
  return stages[stage] || "处理中";
}
