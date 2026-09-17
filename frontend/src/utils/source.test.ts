import { describe, expect, it } from "vitest";
import {
  documentPreviewKind,
  isCatalogSourceUrl,
  isDocumentSource,
  isDigestSource,
  locatorPage,
  needsMediaOverrideError,
  parseSourceUrls,
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
    expect(sourceTypeLabel("schedule_digest")).toBe("定时汇总");
    expect(sourceTypeLabel("digest")).toBe("汇总");
    expect(isDigestSource("schedule_digest")).toBe(true);
    expect(isDigestSource("digest")).toBe(true);
    expect(isDigestSource("page")).toBe(false);
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

  it("按行拆分地址并去掉空行和重复项", () => {
    expect(
      parseSourceUrls(
        " https://cdn.example.com/a.mp4 \n\nhttps://cdn.example.com/b.mp4\r\nhttps://cdn.example.com/a.mp4\n"
      )
    ).toEqual([
      "https://cdn.example.com/a.mp4",
      "https://cdn.example.com/b.mp4",
    ]);
    expect(parseSourceUrls("   \n  ")).toEqual([]);
  });

  it("识别空间店铺站点目录地址", () => {
    expect(isCatalogSourceUrl("https://space.bilibili.com/11430504")).toBe(true);
    expect(isCatalogSourceUrl("https://www.bilibili.com/video/BV1a4awzsENn")).toBe(
      false
    );
    expect(isCatalogSourceUrl("https://appdemo.h5.xiaoeknow.com/")).toBe(true);
    expect(
      isCatalogSourceUrl(
        "https://appdemo.h5.xiaoeknow.com/v4/course/alive/l_abc?app_id=appdemo"
      )
    ).toBe(false);
    expect(isCatalogSourceUrl("https://jf.yueniuzq.com/living/")).toBe(true);
    expect(
      isCatalogSourceUrl("https://jf.yueniuzq.com/living/?id=abc")
    ).toBe(false);
  });

  it("识别需要补流地址的解析失败", () => {
    expect(
      needsMediaOverrideError("无法解析媒体地址，请填写媒体地址覆盖后重试")
    ).toBe(true);
    expect(needsMediaOverrideError("转写失败")).toBe(false);
    expect(needsMediaOverrideError("")).toBe(false);
  });
});
