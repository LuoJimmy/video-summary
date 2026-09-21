import { describe, expect, it } from "vitest";
import { formatFileSize } from "./size";

describe("formatFileSize", () => {
  it("按量级选择单位", () => {
    expect(formatFileSize(0)).toBe("");
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(2048)).toBe("2.0 KB");
    expect(formatFileSize(15 * 1024)).toBe("15 KB");
    expect(formatFileSize(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(formatFileSize(3 * 1024 * 1024 * 1024)).toBe("3.0 GB");
  });

  it("忽略非法输入", () => {
    expect(formatFileSize(-1)).toBe("");
  });
});
