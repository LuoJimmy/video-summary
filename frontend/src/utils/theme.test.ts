import { describe, expect, it } from "vitest";
import {
  applyTheme,
  DEFAULT_THEME,
  isThemeId,
  readTheme,
  THEME_KEY,
} from "./theme";

describe("theme", () => {
  it("accepts known ids", () => {
    expect(isThemeId("night")).toBe(true);
    expect(isThemeId("dawn")).toBe(true);
    expect(isThemeId("neon")).toBe(false);
  });

  it("persists and restores", () => {
    localStorage.removeItem(THEME_KEY);
    expect(readTheme()).toBe(DEFAULT_THEME);
    expect(applyTheme("nord")).toBe("nord");
    expect(localStorage.getItem(THEME_KEY)).toBe("nord");
    expect(document.documentElement.getAttribute("data-theme")).toBe("nord");
    expect(readTheme()).toBe("nord");
    expect(applyTheme("unknown")).toBe(DEFAULT_THEME);
  });
});
