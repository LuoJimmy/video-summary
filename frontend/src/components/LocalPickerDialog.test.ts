import { createApp, nextTick, ref } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import type { LocalEntries, LocalEntry, LocalPick } from "../api";
import LocalPickerDialog from "./LocalPickerDialog.vue";

vi.mock("../api", () => ({
  api: {
    localEntries: vi.fn(),
    localRoot: vi.fn(),
  },
  apiErrorMessage: (err: unknown, fallback = "请求失败") =>
    err instanceof Error && err.message ? err.message : fallback,
}));

function makeEntry(overrides: Partial<LocalEntry> = {}): LocalEntry {
  return {
    name: "a.mp4",
    path: "/media/a.mp4",
    kind: "file",
    size: 2048,
    modified_at: null,
    supported: true,
    ...overrides,
  };
}

function makeListing(
  entries: LocalEntry[],
  overrides: Partial<LocalEntries> = {}
): LocalEntries {
  return {
    root: "/media",
    path: "/media",
    parent: "",
    recursive: false,
    query: "",
    page: 1,
    page_size: 50,
    total: entries.length,
    entries,
    truncated: false,
    ...overrides,
  };
}

let root: HTMLElement | undefined;
let app: ReturnType<typeof createApp> | undefined;

async function flush() {
  for (let i = 0; i < 12; i++) await Promise.resolve();
  await nextTick();
}

async function mountDialog(
  options: { selected?: LocalPick[]; limit?: number; scanLimit?: number } = {}
) {
  const open = ref(true);
  const confirmed: { items: LocalPick[] | null } = { items: null };
  const closed = { value: false };
  const Root = {
    components: { LocalPickerDialog },
    setup() {
      return {
        open,
        root: "/media",
        selected: options.selected ?? [],
        limit: options.limit ?? 1000,
        scanLimit: options.scanLimit ?? 1000,
        confirm: (items: LocalPick[]) => {
          confirmed.items = items;
        },
        close: () => {
          closed.value = true;
        },
      };
    },
    template: `
      <LocalPickerDialog
        :open="open"
        :root="root"
        :selected="selected"
        :limit="limit"
        :scan-limit="scanLimit"
        @close="close"
        @confirm="confirm"
      />
    `,
  };
  root = document.createElement("div");
  document.body.appendChild(root);
  app = createApp(Root);
  app.mount(root);
  await flush();
  return { el: document.body, confirmed, closed };
}

function clickNamed(el: HTMLElement, name: string) {
  const btn = [...el.querySelectorAll("button")].find((item) =>
    item.textContent?.trim().includes(name)
  ) as HTMLButtonElement | undefined;
  btn?.click();
}

function dirBoxState(el: HTMLElement) {
  const box = el.querySelector(
    '[aria-label="选择文件夹 2026"]'
  ) as HTMLElement | null;
  return box?.getAttribute("aria-checked");
}

afterEach(() => {
  app?.unmount();
  root?.remove();
  app = undefined;
  root = undefined;
});

beforeEach(() => {
  vi.mocked(api.localEntries).mockReset();
  vi.mocked(api.localRoot).mockReset();
});

describe("LocalPickerDialog", () => {
  it("打开时加载根目录并勾选文件后确定", async () => {
    vi.mocked(api.localEntries).mockResolvedValue(
      makeListing([
        makeEntry({ name: "2026", path: "/media/2026", kind: "dir", size: 0 }),
        makeEntry(),
      ])
    );
    const { el, confirmed } = await mountDialog();

    expect(api.localEntries).toHaveBeenCalledWith("/media", {
      query: "",
      page: 1,
      pageSize: 50,
    });
    expect(el.querySelector(".local-picker-dialog")?.textContent).toContain(
      "2026"
    );
    expect(el.querySelector(".local-picker-dialog")?.textContent).toContain(
      "a.mp4"
    );
    expect(el.querySelector(".local-picker-dialog")?.textContent).toContain(
      "已选 0"
    );

    const checkbox = el.querySelector(
      '[aria-label="选择 a.mp4"]'
    ) as HTMLElement | null;
    checkbox?.click();
    await flush();
    expect(el.textContent).toContain("已选 1 / 1000");

    clickNamed(el, "确定");
    await flush();
    expect(confirmed.items).toEqual([{ path: "/media/a.mp4", name: "a.mp4" }]);
  });

  it("按名称搜索当前文件夹", async () => {
    vi.mocked(api.localEntries).mockResolvedValue(makeListing([]));
    const { el } = await mountDialog();

    const input = el.querySelector(
      'input[aria-label="搜索当前文件夹"]'
    ) as HTMLInputElement;
    input.value = "clip";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    clickNamed(el, "搜索");
    await flush();

    expect(api.localEntries).toHaveBeenLastCalledWith("/media", {
      query: "clip",
      page: 1,
      pageSize: 50,
    });
  });

  it("可翻页并保持每页条数", async () => {
    vi.mocked(api.localEntries).mockResolvedValue(
      makeListing([makeEntry()], { total: 120, page_size: 50 })
    );
    const { el } = await mountDialog();

    const next = el.querySelector('[aria-label="下一页"]') as HTMLButtonElement;
    next.click();
    await flush();

    expect(api.localEntries).toHaveBeenLastCalledWith("/media", {
      query: "",
      page: 2,
      pageSize: 50,
    });
  });

  it("勾选文件夹会加入其中文件，取消勾选再移除", async () => {
    vi.mocked(api.localEntries).mockImplementation(
      async (path, options = {}) => {
        if (options.recursive) {
          return makeListing(
            [
              makeEntry({ name: "a.mp4", path: "/media/2026/a.mp4" }),
              makeEntry({ name: "b.pdf", path: "/media/2026/b.pdf" }),
            ],
            { path: "/media/2026", recursive: true, total: 2 }
          );
        }
        return makeListing([
          makeEntry({
            name: "2026",
            path: "/media/2026",
            kind: "dir",
            size: 0,
          }),
        ]);
      }
    );
    const { el } = await mountDialog();

    const dirBox = el.querySelector(
      '[aria-label="选择文件夹 2026"]'
    ) as HTMLElement;
    expect(dirBox.getAttribute("aria-checked")).toBe("false");
    dirBox.click();
    await flush();
    await flush();

    expect(api.localEntries).toHaveBeenLastCalledWith("/media/2026", {
      recursive: true,
    });
    expect(el.textContent).toContain("已选 2 / 1000");
    expect(dirBoxState(el)).toBe("true");

    (el.querySelector('[aria-label="选择文件夹 2026"]') as HTMLElement).click();
    await flush();
    expect(el.textContent).toContain("已选 0 / 1000");
    expect(dirBoxState(el)).toBe("false");
  });
});
