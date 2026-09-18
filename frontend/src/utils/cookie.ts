const COOKIE_PREFIX = /^\s*(?:cookie|set-cookie)\s*:\s*/i;
const BAD_NAME_CHARS = /[\s:,]/;

function stripControlChars(text: string): string {
  return [...text]
    .filter((char) => {
      const code = char.charCodeAt(0);
      return code > 0x1f && code !== 0x7f;
    })
    .join("");
}

/**
 * 把粘贴进来的 Cookie 合并成单行 `name=value; name=value`。
 *
 * 浏览器扩展导出的「Header String」常是每行一个 name=value，
 * 直接发到后端会被当成非法请求头（Illegal header value）。
 */
export function normalizeCookie(raw: string): string {
  const text = String(raw ?? "")
    .replace(/\\r\\n|\\r|\\n/g, "\n")
    .replace(/\r\n?/g, "\n")
    .replace(COOKIE_PREFIX, "");
  const pairs: string[] = [];
  for (const line of text.split("\n")) {
    for (const item of line.split(";")) {
      const pair = stripControlChars(item).trim();
      const index = pair.indexOf("=");
      if (index <= 0) continue;
      const name = pair.slice(0, index).trim();
      if (!name || BAD_NAME_CHARS.test(name)) continue;
      pairs.push(`${name}=${pair.slice(index + 1).trim()}`);
    }
  }
  return pairs.join("; ");
}
