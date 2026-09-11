export const DOCUMENT_SOURCE_TYPES = new Set([
  "local_document",
  "http_document",
  "web_page",
]);

export function isDocumentSource(sourceType: string | null | undefined): boolean {
  return DOCUMENT_SOURCE_TYPES.has(sourceType || "");
}

export function sourceTypeLabel(sourceType: string | null | undefined): string {
  const labels: Record<string, string> = {
    local_file: "本地媒体",
    local_document: "本地文档",
    http_document: "在线文档",
    web_page: "网页",
    http_video: "在线视频",
    http_audio: "在线音频",
    hls: "HLS",
    page: "页面",
    live: "直播",
  };
  const raw = (sourceType || "").trim();
  return labels[raw] || raw || "未知类型";
}

export function locatorLabel(
  locator?: string | null,
  start?: number,
  fallback = ""
): string {
  const place = (locator || "").trim();
  if (place) return place;
  if (typeof start === "number" && start > 0) return "";
  return fallback;
}

export function locatorPage(locator?: string | null): number | null {
  const match = (locator || "").match(/第\s*(\d+)\s*页/);
  if (!match) return null;
  const page = Number(match[1]);
  return Number.isFinite(page) && page > 0 ? page : null;
}

export function documentPreviewKind(
  sourceType?: string | null,
  sourceUrl?: string | null,
  mediaUrl?: string | null
): "pdf" | "html" | "file" {
  if (sourceType === "web_page") return "html";
  const name = [sourceUrl, mediaUrl]
    .filter((item) => (item || "").trim())
    .join(" ")
    .toLowerCase();
  if (/\.pdf(?:$|[?#])/.test(name)) return "pdf";
  if (/\.(html?|docx?)(?:$|[?#])/.test(name)) return "html";
  return "file";
}

export function publicSourceUrl(url?: string | null): string {
  const text = (url || "").trim();
  if (/^https?:\/\//i.test(text)) return text;
  return "";
}
