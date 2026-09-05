export const THEME_KEY = "vs-theme";
export const DEFAULT_THEME = "night";

export const THEMES = [
  {
    id: "night",
    name: "夜航",
    desc: "深蓝工作台",
    swatches: ["#121821", "#1b2430", "#7aa7e8"],
  },
  {
    id: "nord",
    name: "极光",
    desc: "Nord 冷色",
    swatches: ["#2e3440", "#3b4252", "#88c0d0"],
  },
  {
    id: "graphite",
    name: "石墨",
    desc: "OLED 深黑",
    swatches: ["#09090b", "#18181b", "#7dd3fc"],
  },
  {
    id: "dawn",
    name: "月光",
    desc: "浅色日间",
    swatches: ["#f4f6fb", "#ffffff", "#3b6fd4"],
  },
  {
    id: "forest",
    name: "竹野",
    desc: "Everforest",
    swatches: ["#2d353b", "#343f44", "#a7c080"],
  },
  {
    id: "rose",
    name: "玫瑰",
    desc: "Catppuccin",
    swatches: ["#1e1e2e", "#313244", "#f38ba8"],
  },
] as const;

export type ThemeId = (typeof THEMES)[number]["id"];

export function isThemeId(value: string): value is ThemeId {
  return THEMES.some((item) => item.id === value);
}

export function readTheme(): ThemeId {
  try {
    const raw = localStorage.getItem(THEME_KEY) || "";
    if (isThemeId(raw)) return raw;
  } catch {
    return DEFAULT_THEME;
  }
  return DEFAULT_THEME;
}

export function applyTheme(id: string): ThemeId {
  const theme = isThemeId(id) ? id : DEFAULT_THEME;
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* 无痕模式可能写不了 */
  }
  return theme;
}
