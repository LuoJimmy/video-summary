export function highlightHtml(text: string, query: string): string {
  const escaped = escapeHtml(text);
  const needle = query.trim();
  if (!needle) return escaped;
  const pattern = new RegExp(escapeRegExp(needle), "gi");
  return escaped.replace(pattern, (matched) => `<mark>${matched}</mark>`);
}

export function formatChatHtml(text: string): string {
  const escaped = escapeHtml(text);
  const bolded = escaped.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  return bolded.replace(/\n/g, "<br>");
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
