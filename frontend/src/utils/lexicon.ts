export type LexiconFix = {
  wrong: string;
  right: string;
};

export function parseLexiconTerms(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const line of text.split(/\r?\n/)) {
    const term = line.trim();
    if (!term || seen.has(term)) continue;
    seen.add(term);
    out.push(term);
  }
  return out;
}

export function serializeLexiconTerms(terms: string[]): string {
  return terms.join("\n");
}

export function sanitizeLexiconFixes(rows: LexiconFix[]): LexiconFix[] {
  const seen = new Set<string>();
  const out: LexiconFix[] = [];
  for (const row of rows) {
    const wrong = (row.wrong || "").trim();
    const right = (row.right || "").trim();
    if (!wrong || !right || wrong === right || seen.has(wrong)) continue;
    seen.add(wrong);
    out.push({ wrong, right });
  }
  return out;
}
