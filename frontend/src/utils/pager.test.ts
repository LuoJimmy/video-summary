import { describe, expect, it } from "vitest";
import { pageAfterSizeChange, pagerItems } from "./pager";

describe("pagerItems", () => {
  it("页数不多时展示全部页码", () => {
    expect(pagerItems(1, 7)).toEqual([
      { type: "page", value: 1 },
      { type: "page", value: 2 },
      { type: "page", value: 3 },
      { type: "page", value: 4 },
      { type: "page", value: 5 },
      { type: "page", value: 6 },
      { type: "page", value: 7 },
    ]);
  });

  it("首页展示前五页、省略号和末页", () => {
    expect(pagerItems(1, 16)).toEqual([
      { type: "page", value: 1 },
      { type: "page", value: 2 },
      { type: "page", value: 3 },
      { type: "page", value: 4 },
      { type: "page", value: 5 },
      { type: "ellipsis", jump: 6 },
      { type: "page", value: 16 },
    ]);
  });

  it("中间页两侧都出现省略号", () => {
    expect(pagerItems(8, 16)).toEqual([
      { type: "page", value: 1 },
      { type: "ellipsis", jump: 3 },
      { type: "page", value: 6 },
      { type: "page", value: 7 },
      { type: "page", value: 8 },
      { type: "page", value: 9 },
      { type: "page", value: 10 },
      { type: "ellipsis", jump: 13 },
      { type: "page", value: 16 },
    ]);
  });

  it("末页展示首页、省略号和最后五页", () => {
    expect(pagerItems(16, 16)).toEqual([
      { type: "page", value: 1 },
      { type: "ellipsis", jump: 11 },
      { type: "page", value: 12 },
      { type: "page", value: 13 },
      { type: "page", value: 14 },
      { type: "page", value: 15 },
      { type: "page", value: 16 },
    ]);
  });
});

describe("pageAfterSizeChange", () => {
  it("尽量保持当前页第一条数据", () => {
    expect(pageAfterSizeChange(3, 10, 20)).toBe(2);
    expect(pageAfterSizeChange(1, 10, 50)).toBe(1);
  });
});
