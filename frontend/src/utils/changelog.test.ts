import { describe, expect, it } from "vitest";
import { changelogMarkdown, parseChangelog } from "./changelog";

describe("parseChangelog", () => {
  it("解析版本、日期、摘要和分组条目", () => {
    const releases = parseChangelog(`# 更新日志

前言。

## 1.2.0 - 2026-10-01

小版本说明。

### 新增

- 第一项
- 第二项

### 修复

- 修好旧问题

## 1.0.0 - 2026-09-05

首个正式版本。

### 新增

- 基础能力
`);
    expect(releases).toEqual([
      {
        version: "1.2.0",
        date: "2026-10-01",
        summary: "小版本说明。",
        sections: [
          { title: "新增", items: ["第一项", "第二项"] },
          { title: "修复", items: ["修好旧问题"] },
        ],
      },
      {
        version: "1.0.0",
        date: "2026-09-05",
        summary: "首个正式版本。",
        sections: [{ title: "新增", items: ["基础能力"] }],
      },
    ]);
  });

  it("忽略无法识别的标题块", () => {
    expect(parseChangelog("## 未发布\n\n- 草稿")).toEqual([]);
  });

  it("仓库更新日志包含 1.0.0", () => {
    const releases = parseChangelog(changelogMarkdown);
    expect(releases[0]?.version).toBe("1.0.0");
    expect(releases[0]?.date).toBe("2026-09-05");
    expect(releases[0]?.sections.some((item) => item.items.length > 0)).toBe(
      true
    );
  });
});
