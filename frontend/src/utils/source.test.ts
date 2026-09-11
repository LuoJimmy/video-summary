import { describe, expect, it } from "vitest";
import {
  documentPreviewKind,
  isDocumentSource,
  locatorPage,
  publicSourceUrl,
  sourceTypeLabel,
} from "./source";

describe("source helpers", () => {
  it("识别文档来源", () => {
    expect(isDocumentSource("local_document")).toBe(true);
    expect(isDocumentSource("web_page")).toBe(true);
    expect(isDocumentSource("local_file")).toBe(false);
  });

  it("给出中文类型名", () => {
    expect(sourceTypeLabel("local_document")).toBe("本地文档");
    expect(sourceTypeLabel("http_document")).toBe("在线文档");
    expect(sourceTypeLabel("web_page")).toBe("网页");
  });

  it("从 locator 解析页码并判断预览类型", () => {
    expect(locatorPage("第3页")).toBe(3);
    expect(locatorPage("第1段")).toBeNull();
    expect(documentPreviewKind("local_document", "/tmp/a.pdf")).toBe("pdf");
    expect(documentPreviewKind("web_page", "https://example.com/a")).toBe(
      "html"
    );
    expect(documentPreviewKind("local_document", "/tmp/a.docx")).toBe("html");
  });

  it("本地路径不作为公开地址展示", () => {
    expect(publicSourceUrl("https://cdn.example.com/a.mp4")).toBe(
      "https://cdn.example.com/a.mp4"
    );
    expect(publicSourceUrl("/tmp/report.pdf")).toBe("");
    expect(publicSourceUrl("file:///Users/me/a.pdf")).toBe("");
  });
});
