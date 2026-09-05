export type DomainPack = {
  id: string;
  base_preset: string;
  name: string;
  asr_hint: string;
  chapter_focus: string;
  term_aliases: string;
  overview_role: string;
  overview_stance: string;
  disclaimer: string;
  knowledge_role: string;
  knowledge_guardrails: string;
  example_questions: string[];
  content_keywords: string[];
  highlight_phrases: string[];
  highlight_stock_codes: boolean;
  proofread_hint: string;
  chapter_prompt_override: string;
  overview_prompt_override: string;
  knowledge_prompt_override: string;
};

export type OverviewHighlight = {
  phrases: string[];
  stockCodes: boolean;
};

export const A_SHARE_HIGHLIGHT: OverviewHighlight = {
  phrases: [
    "不看空不做空",
    "高抛低吸",
    "超跌反弹",
    "不宜重仓",
    "趋势向上",
    "仓位管理",
    "主线未定",
    "低吸",
  ],
  stockCodes: true,
};

export function emptyDomainPack(): DomainPack {
  return {
    id: "a-share",
    base_preset: "a-share",
    name: "A股盘面课",
    asr_hint: "",
    chapter_focus: "",
    term_aliases: "",
    overview_role: "",
    overview_stance: "",
    disclaimer: "",
    knowledge_role: "",
    knowledge_guardrails: "",
    example_questions: [],
    content_keywords: [],
    highlight_phrases: [...A_SHARE_HIGHLIGHT.phrases],
    highlight_stock_codes: true,
    proofread_hint: "",
    chapter_prompt_override: "",
    overview_prompt_override: "",
    knowledge_prompt_override: "",
  };
}

export function highlightFromPack(pack?: DomainPack | null): OverviewHighlight {
  if (!pack)
    return { ...A_SHARE_HIGHLIGHT, phrases: [...A_SHARE_HIGHLIGHT.phrases] };
  return {
    phrases: [...(pack.highlight_phrases || [])],
    stockCodes: pack.highlight_stock_codes !== false,
  };
}
