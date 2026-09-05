import { afterEach, describe, expect, it } from "vitest";
import {
  formatOverviewDocument,
  formatOverviewHtml,
  setOverviewHighlight,
  splitOverviewParagraphs,
} from "./overview";

describe("splitOverviewParagraphs", () => {
  it("splits a long wall of text into multiple paragraphs", () => {
    const text =
      "首先强调趋势一旦形成极难改变，只要不出现改变趋势的动能，就应保持趋势向上的整体思维。随后复盘礼拜五盘面，指出走势符合修复预期，每次下跌后只要覆反不扩大就可以低吸。接着讲解情绪周期，识别修复信号以及管理仓位，明确不看空不做空。最后给出操作条件，结合板块轮动选择标的，并提醒仓位要跟市场节奏匹配。再往后补充了量能和情绪指标的用法，说明先分化后修复再分化的节奏。";
    const paragraphs = splitOverviewParagraphs(text);
    expect(paragraphs.length).toBeGreaterThan(1);
    expect(paragraphs.join("")).toBe(text);
  });

  it("keeps blank-line blocks as paragraph boundaries", () => {
    const paragraphs =
      splitOverviewParagraphs("开场综述。\n\n后面进入板块分析。");
    expect(paragraphs).toEqual(["开场综述。", "后面进入板块分析。"]);
  });
});

describe("formatOverviewHtml", () => {
  afterEach(() => {
    setOverviewHighlight();
  });
  it("renders markdown lists as separate items", () => {
    const html = formatOverviewHtml(
      "- 保留**东百**结论\n- 数据约100亿\n- 事件是切换航天"
    );
    expect(html).toHaveLength(3);
    expect(html[0]).toContain("<strong>东百</strong>");
    expect(html[1]).toContain("<strong>约100亿</strong>");
  });
  it("renders markdown bold and auto-bolds numbers, conclusions and names", () => {
    const html = formatOverviewHtml(
      "关注**贵州茅台**减持约100亿，以及半导体板块。指出趋势一旦形成极难改变，就可以低吸，风华高科为代表。"
    ).join("");
    expect(html).toContain("<strong>贵州茅台</strong>");
    expect(html).toContain("<strong>约100亿</strong>");
    expect(html).toContain("<strong>半导体板块</strong>");
    expect(html).toContain("<strong>趋势一旦形成极难改变</strong>");
    expect(html).toContain("<strong>低吸</strong>");
    expect(html).toContain("<strong>风华高科</strong>");
  });

  it("does not treat six-digit codes as stocks in generic domain", () => {
    setOverviewHighlight({ phrases: [], stockCodes: false });
    const html = formatOverviewHtml(
      "关注600519以及半导体板块，就可以低吸。"
    ).join("");
    expect(html).not.toContain("<strong>600519</strong>");
    expect(html).not.toContain("<strong>半导体板块</strong>");
    expect(html).not.toContain("<strong>低吸</strong>");
    setOverviewHighlight();
  });

  it("escapes html and does not treat dates as stock codes", () => {
    const html = formatOverviewHtml("日期20260817<script>x</script>").join("");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<strong>202608</strong>");
  });

  it("renders structured overview by sections", () => {
    const html = formatOverviewDocument(
      "【主题】讲东百与航天切换\n【核心观点】主线未定不要上错仓\n【论证结构】\n1. **东百**先走后死（12月24日，来源：转写）\n2. 航天接力\n【结论/行动建议】低吸等修复"
    );
    expect(html).toContain('<h4 class="overview-h">【主题】</h4>');
    expect(html).toContain("讲东百与航天切换");
    expect(html).toContain('<ol class="overview-list">');
    expect(html).toContain("<strong>东百</strong>");
    expect(html).toContain("【结论/行动建议】");
  });

  it("renders doubao-style headings and tables", () => {
    const html = formatOverviewDocument(
      [
        "## 一句话总结",
        "**用情绪周期做决策。**",
        "## 主题与核心观点",
        "| 维度 | 内容 |",
        "|---|---|",
        "| 主题 | 情绪周期 |",
        "| 核心观点 | 研究风比研究旗重要 |",
        "## 论证结构：两大板块",
        "**板块一：市场操作层（约 09:29–01:03）**",
        "| 时间 | 关键事件 | 含义 |",
        "|---|---|---|",
        "| 8/21 | 成交额1.6万亿 | 量能参考 |",
        "核心结论：**上涨中的大冰点是买点。**",
      ].join("\n")
    );
    expect(html).toContain('<h3 class="overview-h">一句话总结</h3>');
    expect(html).toContain('<table class="overview-table">');
    expect(html).toContain("<th>维度</th>");
    expect(html).toContain("情绪周期");
    expect(html).toContain("<strong>1.6万亿</strong>");
    expect(html).toContain("上涨中的大冰点是买点");
  });

  it("renders nested chapter blocks", () => {
    const html = formatOverviewDocument(
      [
        "## 论证结构",
        "### 大板块：市场操作层（约 00:09:29–01:03:00）",
        "#### 1. 冰点复盘（约 00:15:39–00:23:07）",
        "该小节结论：**冰点是买点。**",
        "#### 2. 仓位管理（约 00:23:07–00:54:51）",
        "分批建仓。",
      ].join("\n")
    );
    expect(html).toContain('<h3 class="overview-h">论证结构</h3>');
    expect(html).toContain(
      '<h4 class="overview-h">大板块：市场操作层（约 00:09:29–01:03:00）</h4>'
    );
    expect(html).toContain(
      '<h5 class="overview-h">1. 冰点复盘（约 00:15:39–00:23:07）</h5>'
    );
    expect(html).toContain("仓位管理");
    expect(html).toContain('<h5 class="overview-h">');
  });

  it("hides a lone subblock that repeats the parent", () => {
    const html = formatOverviewDocument(
      [
        "## 论证结构",
        "### 一、道的哲学与投资心态（约 00:00:15–00:04:58）",
        "1. 道的全息与不可言说（约 00:00:15–00:04:58）",
        "人体穴位对应天地。",
      ].join("\n")
    );
    expect(html).toContain("道的哲学与投资心态");
    expect(html).toContain("人体穴位对应天地");
    expect(html).not.toContain("道的全息与不可言说");
  });
});
