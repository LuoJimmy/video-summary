import { describe, expect, it } from "vitest";
import {
  formatDateStamp,
  formatDateTime,
  formatDuration,
  formatTimestamp,
  isJobActive,
  jobElapsedSeconds,
  localDayBoundIso,
  statusLabel,
} from "./time";

describe("localDayBoundIso", () => {
  it("converts a local calendar day into utc bounds", () => {
    expect(localDayBoundIso("")).toBe("");
    expect(localDayBoundIso("2026-13-01")).toBe("");
    const start = localDayBoundIso("2026-08-13");
    const end = localDayBoundIso("2026-08-13", true);
    expect(start).toBe(new Date("2026-08-13T00:00:00").toISOString());
    expect(end).toBe(new Date("2026-08-14T00:00:00").toISOString());
    expect(Date.parse(end) - Date.parse(start)).toBe(24 * 60 * 60 * 1000);
  });
});

describe("formatDuration", () => {
  it("formats seconds minutes and hours", () => {
    expect(formatDuration(8)).toBe("8秒");
    expect(formatDuration(75)).toBe("1分15秒");
    expect(formatDuration(3723)).toBe("1小时2分3秒");
  });
});

describe("formatTimestamp", () => {
  it("formats minutes and hours", () => {
    expect(formatTimestamp(75)).toBe("01:15");
    expect(formatTimestamp(3723)).toBe("01:02:03");
  });
});

describe("formatDateTime", () => {
  it("formats utc timestamps in local time", () => {
    expect(formatDateTime("")).toBe("");
    expect(formatDateTime(null)).toBe("");
    const iso = "2026-09-03T06:30:00Z";
    const date = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, "0");
    expect(formatDateTime(iso)).toBe(
      `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
    );
  });
});

describe("formatDateStamp", () => {
  it("formats utc timestamps as YYYYMMDD in local time", () => {
    expect(formatDateStamp("")).toBe("");
    expect(formatDateStamp(null)).toBe("");
    const iso = "2026-09-03T06:30:00Z";
    const date = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, "0");
    expect(formatDateStamp(iso)).toBe(
      `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}`
    );
  });
});

describe("jobElapsedSeconds", () => {
  it("counts from started_at and treats naive timestamps as UTC", () => {
    expect(isJobActive("running")).toBe(true);
    expect(isJobActive("done")).toBe(false);
    expect(
      jobElapsedSeconds(
        {
          started_at: "2026-09-01T04:00:00Z",
          created_at: "2026-08-01T00:00:00Z",
        },
        Date.parse("2026-09-01T04:01:15Z")
      )
    ).toBe(75);
    expect(
      jobElapsedSeconds(
        {
          started_at: "2026-09-01T04:00:00",
          created_at: "2026-08-01T00:00:00",
        },
        Date.parse("2026-09-01T04:00:08Z")
      )
    ).toBe(8);
  });
});

describe("statusLabel", () => {
  it("maps pipeline stages", () => {
    expect(statusLabel("done", "done")).toBe("已完成");
    expect(statusLabel("running", "transcribing")).toBe("转写中");
    expect(statusLabel("running", "proofreading")).toBe("校对转写");
    expect(statusLabel("cancelled", "cancelled")).toBe("已取消");
  });
});
