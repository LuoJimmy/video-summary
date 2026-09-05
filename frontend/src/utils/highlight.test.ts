import { describe, expect, it } from "vitest";
import { formatChatHtml, highlightHtml } from "./highlight";

describe("highlightHtml", () => {
  it("wraps the query and escapes html", () => {
    expect(highlightHtml("关注贵州茅台减持", "茅台")).toContain(
      "<mark>茅台</mark>"
    );
    expect(highlightHtml("<script>茅台", "茅台")).toContain("&lt;script&gt;");
    expect(highlightHtml("<script>茅台", "茅台")).not.toContain("<script>");
  });

  it("renders chat markdown bold and line breaks", () => {
    const html = formatChatHtml("先看**低吸**\n再看仓位");
    expect(html).toContain("<strong>低吸</strong>");
    expect(html).toContain("<br>");
  });
});
