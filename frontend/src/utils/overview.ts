import { A_SHARE_HIGHLIGHT, type OverviewHighlight } from "./domain";

const TARGET_CHARS = 110;
const MAX_CHARS = 180;

const LIST_LINE = /^\s*(?:[-*+]|\d+[.)])\s+(.+)$/;

export function splitOverviewParagraphs(text: string): string[] {
  const raw = text.replace(/\r\n/g, "\n").trim();
  if (!raw) return [];
  const blocks = raw.includes("\n\n")
    ? raw
        .split(/\n{2,}/)
        .map((item) => item.replace(/\n+/g, "").trim())
        .filter(Boolean)
    : [raw];
  const paragraphs: string[] = [];
  for (const block of blocks) {
    paragraphs.push(...packSentences(splitSentences(block)));
  }
  return paragraphs;
}

export function splitOverviewListItems(text: string): string[] | null {
  const lines = text
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
  if (lines.length < 2) return null;
  const extracted = lines.map((line) => {
    const match = line.match(LIST_LINE);
    return match ? match[1].trim() : "";
  });
  const hit = extracted.filter(Boolean).length;
  if (hit < Math.ceil(lines.length * 0.7)) return null;
  return extracted.map((item, index) => item || lines[index]);
}

export function formatOverviewHtml(text: string): string[] {
  const items = splitOverviewListItems(text) || splitOverviewParagraphs(text);
  return items.map((item) => renderInline(item));
}

export function overviewIsList(text: string): boolean {
  return Boolean(splitOverviewListItems(text));
}

export function overviewIsStructured(text: string): boolean {
  return (
    /【(?:主题|核心观点|论证结构|结论)/.test(text) ||
    /^#{1,4}\s+/m.test(text) ||
    /^\|.+\|/m.test(text)
  );
}

export function formatOverviewDocument(text: string): string {
  const raw = text.replace(/\r\n/g, "\n").trim();
  if (!raw) return "";
  if (overviewIsStructured(raw)) return renderRich(collapseLoneSubblocks(raw));
  const list = splitOverviewListItems(raw);
  if (list) {
    return `<ul class="overview-list">${list.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ul>`;
  }
  return splitOverviewParagraphs(raw)
    .map((paragraph) => `<p class="overview-p">${renderInline(paragraph)}</p>`)
    .join("");
}

function headingLevel(line: string): number {
  const match = line.trim().match(/^(#{1,4})\s+/);
  return match ? match[1].length : 0;
}

function isSubblockHeading(line: string): boolean {
  const trimmed = line.trim();
  if (/^#{4}\s+/.test(trimmed)) return true;
  return /^\d+\.\s+\S/.test(trimmed) && /约\s*\d{1,2}:\d{2}/.test(trimmed);
}

function collapseLoneSubblocks(text: string): string {
  const lines = text.split("\n");
  const drop = new Set<number>();
  let index = 0;
  while (index < lines.length) {
    if (headingLevel(lines[index]) !== 3) {
      index += 1;
      continue;
    }
    const start = index + 1;
    let end = start;
    while (end < lines.length) {
      const level = headingLevel(lines[end]);
      if (level > 0 && level <= 3) break;
      end += 1;
    }
    const subs: number[] = [];
    for (let cursor = start; cursor < end; cursor += 1) {
      if (isSubblockHeading(lines[cursor])) subs.push(cursor);
    }
    if (subs.length === 1) drop.add(subs[0]);
    index = end;
  }
  return lines.filter((_, lineIndex) => !drop.has(lineIndex)).join("\n");
}

function isTableSeparator(line: string): boolean {
  return /^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?$/.test(line);
}

function splitTableCells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function renderTable(rows: string[][]): string {
  if (!rows.length) return "";
  const head = rows[0];
  const body = rows.slice(1);
  const th = head.map((cell) => `<th>${renderInline(cell)}</th>`).join("");
  const tr = body
    .map(
      (row) =>
        `<tr>${row.map((cell) => `<td>${renderInline(cell)}</td>`).join("")}</tr>`
    )
    .join("");
  return `<div class="overview-table-wrap"><table class="overview-table"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
}

function renderRich(text: string): string {
  const lines = text.split("\n");
  const parts: string[] = [];
  let listOpen: "ul" | "ol" | "" = "";
  const closeList = () => {
    if (!listOpen) return;
    parts.push(listOpen === "ol" ? "</ol>" : "</ul>");
    listOpen = "";
  };
  let index = 0;
  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      closeList();
      index += 1;
      continue;
    }
    if (line.startsWith("|") && line.includes("|", 1)) {
      closeList();
      const tableLines: string[] = [];
      while (index < lines.length) {
        const next = lines[index].trim();
        if (!next.startsWith("|")) break;
        if (!isTableSeparator(next)) tableLines.push(next);
        index += 1;
      }
      const rows = tableLines
        .map(splitTableCells)
        .filter((row) => row.some(Boolean));
      parts.push(renderTable(rows));
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      closeList();
      const tags = { 1: "h3", 2: "h3", 3: "h4", 4: "h5" } as const;
      const level = tags[heading[1].length as 1 | 2 | 3 | 4];
      parts.push(
        `<${level} class="overview-h">${renderInline(heading[2].trim())}</${level}>`
      );
      index += 1;
      continue;
    }
    const section = line.match(/^【([^】]+)】(.*)$/);
    if (section) {
      closeList();
      parts.push(
        `<h4 class="overview-h">${escapeHtml(`【${section[1].trim()}】`)}</h4>`
      );
      const rest = section[2].trim();
      if (rest)
        parts.push(`<p class="overview-lead">${renderInline(rest)}</p>`);
      index += 1;
      continue;
    }
    const unordered = line.match(/^[-*+]\s+(.+)$/);
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      const kind = ordered ? "ol" : "ul";
      if (listOpen && listOpen !== kind) closeList();
      if (!listOpen) {
        parts.push(
          kind === "ol"
            ? '<ol class="overview-list">'
            : '<ul class="overview-list">'
        );
        listOpen = kind;
      }
      parts.push(
        `<li>${renderInline((ordered || unordered)?.[1].trim() || "")}</li>`
      );
      index += 1;
      continue;
    }
    closeList();
    parts.push(`<p class="overview-lead">${renderInline(line)}</p>`);
    index += 1;
  }
  closeList();
  return parts.join("");
}

function splitSentences(block: string): string[] {
  return block
    .split(/(?<=[。！？；])\s*|\n+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function packSentences(sentences: string[]): string[] {
  if (!sentences.length) return [];
  const paragraphs: string[] = [];
  let buffer: string[] = [];
  let chars = 0;
  for (const sentence of sentences) {
    if (buffer.length && chars + sentence.length > MAX_CHARS) {
      paragraphs.push(buffer.join(""));
      buffer = [sentence];
      chars = sentence.length;
      continue;
    }
    buffer.push(sentence);
    chars += sentence.length;
    if (chars >= TARGET_CHARS) {
      paragraphs.push(buffer.join(""));
      buffer = [];
      chars = 0;
    }
  }
  if (buffer.length) paragraphs.push(buffer.join(""));
  return paragraphs;
}

type InlinePart = { bold: boolean; text: string };

type EmphasisRule = {
  pattern: RegExp;
  pick: (match: RegExpExecArray) => { start: number; value: string };
};

const BASE_EMPHASIS_RULES: EmphasisRule[] = [
  {
    pattern: /《[^》]+》|「[^」]+」|『[^』]+』/g,
    pick: (match) => ({ start: match.index, value: match[0] }),
  },
  {
    pattern: /(强调了|指出|认为|明确了?)([^，。；]{4,28})/g,
    pick: (match) => ({
      start: match.index + match[1].length,
      value: match[2],
    }),
  },
  {
    pattern:
      /(?<!\d)(?:约|近)?\d{1,4}(?:\.\d+)?(?:万亿|亿元|万元|%|％|元|万|亿|倍|个点|天)(?!\d)/g,
    pick: (match) => ({ start: match.index, value: match[0] }),
  },
  {
    pattern: /[一二三四五六七八九十两]+(?:天|日|成|倍)/g,
    pick: (match) => ({ start: match.index, value: match[0] }),
  },
];

const STOCK_EMPHASIS_RULES: EmphasisRule[] = [
  {
    pattern: /[\u4e00-\u9fff]{2,4}(?:高科|股份|集团|证券|银行|茅台)(?!板块)/g,
    pick: (match) => ({ start: match.index, value: match[0] }),
  },
  {
    pattern: /[\u4e00-\u9fff]{2,4}板块/g,
    pick: (match) => {
      let start = match.index;
      let value = match[0];
      while (value.length > 4 && LEADING_PARTICLE.test(value[0])) {
        start += 1;
        value = value.slice(1);
      }
      return { start, value };
    },
  },
  {
    pattern: /(?<!\d)\d{6}(?!\d)/g,
    pick: (match) => ({ start: match.index, value: match[0] }),
  },
];

let activeHighlight: OverviewHighlight = {
  phrases: [...A_SHARE_HIGHLIGHT.phrases],
  stockCodes: A_SHARE_HIGHLIGHT.stockCodes,
};

export function setOverviewHighlight(config?: OverviewHighlight | null) {
  if (!config) {
    activeHighlight = {
      phrases: [...A_SHARE_HIGHLIGHT.phrases],
      stockCodes: A_SHARE_HIGHLIGHT.stockCodes,
    };
    return;
  }
  activeHighlight = {
    phrases: [...(config.phrases || [])],
    stockCodes: Boolean(config.stockCodes),
  };
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function emphasisRules(): EmphasisRule[] {
  const rules = [...BASE_EMPHASIS_RULES];
  const phrases = activeHighlight.phrases.filter(Boolean);
  if (phrases.length) {
    rules.splice(2, 0, {
      pattern: new RegExp(phrases.map(escapeRegExp).join("|"), "g"),
      pick: (match) => ({ start: match.index, value: match[0] }),
    });
  }
  if (activeHighlight.stockCodes) {
    rules.push(...STOCK_EMPHASIS_RULES);
  }
  return rules;
}

const LEADING_PARTICLE = /^[及以和与的对在把就还而则]$/;

function renderInline(text: string): string {
  return tokenize(text)
    .map((part) => {
      const escaped = escapeHtml(part.text);
      return part.bold ? `<strong>${escaped}</strong>` : escaped;
    })
    .join("");
}

function tokenize(text: string): InlinePart[] {
  const marked = splitByMarkdownBold(text);
  const parts: InlinePart[] = [];
  for (const item of marked) {
    if (item.bold) {
      parts.push(item);
      continue;
    }
    parts.push(...splitByEmphasis(item.text));
  }
  return parts.length ? parts : [{ bold: false, text }];
}

function splitByMarkdownBold(text: string): InlinePart[] {
  const parts: InlinePart[] = [];
  const pattern = /\*\*(.+?)\*\*/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text))) {
    if (match.index > last) {
      parts.push({ bold: false, text: text.slice(last, match.index) });
    }
    parts.push({ bold: true, text: match[1] });
    last = match.index + match[0].length;
  }
  if (last < text.length) {
    parts.push({ bold: false, text: text.slice(last) });
  }
  return parts.length ? parts : [{ bold: false, text }];
}

function splitByEmphasis(text: string): InlinePart[] {
  const parts: InlinePart[] = [];
  let cursor = 0;
  while (cursor < text.length) {
    const found = nextEmphasis(text, cursor);
    if (!found) {
      parts.push({ bold: false, text: text.slice(cursor) });
      break;
    }
    if (found.start > cursor) {
      parts.push({ bold: false, text: text.slice(cursor, found.start) });
    }
    parts.push({ bold: true, text: found.value });
    cursor = found.start + found.value.length;
  }
  return parts.length ? parts : [{ bold: false, text }];
}

function nextEmphasis(
  text: string,
  from: number
): { start: number; value: string } | null {
  let best: { at: number; start: number; value: string } | null = null;
  for (const rule of emphasisRules()) {
    rule.pattern.lastIndex = from;
    const match = rule.pattern.exec(text);
    if (!match) continue;
    const picked = rule.pick(match);
    if (picked.start < from || !picked.value) continue;
    if (
      !best ||
      match.index < best.at ||
      (match.index === best.at && picked.value.length > best.value.length)
    ) {
      best = { at: match.index, start: picked.start, value: picked.value };
    }
  }
  return best ? { start: best.start, value: best.value } : null;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
