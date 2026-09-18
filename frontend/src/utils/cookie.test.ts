import { describe, expect, it } from "vitest";
import { normalizeCookie } from "./cookie";

describe("normalizeCookie", () => {
  it("把每行一个 name=value 的导出格式合并成一行", () => {
    expect(
      normalizeCookie("Buvid=ZD49B1D5\nDedeUserID=396771578\nSESSDATA=505e96d7")
    ).toBe("Buvid=ZD49B1D5; DedeUserID=396771578; SESSDATA=505e96d7");
  });

  it("去掉 Cookie: 前缀并忽略空行与其他请求头", () => {
    expect(
      normalizeCookie("Cookie: a=1;\n\nb=2\nUser-Agent: Mozilla/5.0")
    ).toBe("a=1; b=2");
  });

  it("兼容字面量 \\n 与空输入，并保留值里的等号", () => {
    expect(normalizeCookie("a=1\\nb=2")).toBe("a=1; b=2");
    expect(normalizeCookie("token=a=b; sid=1")).toBe("token=a=b; sid=1");
    expect(normalizeCookie("")).toBe("");
  });

  it("单行 Cookie 保持不变", () => {
    expect(normalizeCookie("sid=1; _xx_ppt_token=abc")).toBe(
      "sid=1; _xx_ppt_token=abc"
    );
  });
});
