import changelogText from "../../../CHANGELOG.md?raw";

export const changelogMarkdown = changelogText;

export type ChangelogSection = {
  title: string;
  items: string[];
};

export type ChangelogRelease = {
  version: string;
  date: string;
  summary: string;
  sections: ChangelogSection[];
};

const HEADING = /^([0-9]+\.[0-9]+\.[0-9]+)\s*-\s*(.+)$/;
const LIST_ITEM = /^\s*[-*+]\s+(.+)$/;

export function parseChangelog(markdown: string): ChangelogRelease[] {
  const text = markdown.replace(/\r\n/g, "\n").trim();
  const blocks = text.split(/^## /m).slice(1);
  const releases: ChangelogRelease[] = [];
  for (const block of blocks) {
    const lines = block.split("\n");
    const heading = (lines[0] || "").trim();
    const match = heading.match(HEADING);
    if (!match) continue;
    const body = lines.slice(1).join("\n").trim();
    const parts = body.split(/^### /m);
    const sections = parts.slice(1).flatMap((part) => {
      const sectionLines = part.split("\n");
      const title = (sectionLines[0] || "").trim();
      const items = sectionLines
        .slice(1)
        .map((line) => line.match(LIST_ITEM)?.[1]?.trim() || "")
        .filter(Boolean);
      return title ? [{ title, items }] : [];
    });
    releases.push({
      version: match[1],
      date: match[2].trim(),
      summary: (parts[0] || "").trim(),
      sections,
    });
  }
  return releases;
}

export function loadChangelog(): ChangelogRelease[] {
  return parseChangelog(changelogMarkdown);
}
