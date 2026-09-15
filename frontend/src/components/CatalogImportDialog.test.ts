import { createApp, nextTick, ref } from "vue";
import { afterEach, describe, expect, it } from "vitest";
import CatalogImportDialog from "./CatalogImportDialog.vue";
import type { CatalogPreviewItem } from "../api";

function makeItem(
  overrides: Partial<CatalogPreviewItem> = {}
): CatalogPreviewItem {
  return {
    source_url: "https://www.bilibili.com/video/BV1a4awzsENn",
    title: "卖票方法",
    author: "UP",
    created_at: "2026-08-13T04:00:00Z",
    exists: false,
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
  items: CatalogPreviewItem[],
  onConfirm?: (picked: CatalogPreviewItem[]) => void
) {
  const open = ref(true);
  const Root = {
    components: { CatalogImportDialog },
    setup() {
      return {
        open,
        items,
        confirm: (picked: CatalogPreviewItem[]) => onConfirm?.(picked),
        close: () => {
          open.value = false;
        },
      };
    },
    template: `
      <CatalogImportDialog
        :open="open"
        catalog-label="B 站 UP 空间"
        :listed="items.length"
        :items="items"
        next-cursor="next"
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
  return { el: document.body, open };
}

afterEach(() => {
  app?.unmount();
  root?.remove();
  app = undefined;
  root = undefined;
});

describe("CatalogImportDialog", () => {
  it("默认全选并展示已选 badge", async () => {
    const items = [
      makeItem({ source_url: "https://a.example/1", title: "第一课" }),
      makeItem({
        source_url: "https://a.example/2",
        title: "第二课",
        exists: true,
        created_at: "2026-08-14T04:00:00Z",
      }),
    ];
    const { el } = await mountDialog(items);
    expect(el.textContent).toContain("确认拉取B 站 UP 空间");
    expect(el.textContent).toContain("第一课");
    expect(el.textContent).toContain("已存在");
    expect(el.textContent).toContain("已选 2 条");
    const chips = el.querySelectorAll(".catalog-selected-chip");
    expect(chips.length).toBe(2);
  });

  it("标题筛选后保留隐藏勾选，删除 badge 会取消勾选", async () => {
    const items = [
      makeItem({ source_url: "https://a.example/1", title: "早盘直播" }),
      makeItem({ source_url: "https://a.example/2", title: "复盘课" }),
    ];
    const { el } = await mountDialog(items);
    const titleInput = el.querySelector(
      "#catalog-title-filter"
    ) as HTMLInputElement;
    titleInput.value = "早盘";
    titleInput.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    expect(el.textContent).toContain("早盘直播");
    expect(el.querySelector(".catalog-import-table")?.textContent).not.toContain(
      "复盘课"
    );
    expect(el.textContent).toContain("已选 2 条");
    const remove = el.querySelector(
      '[aria-label="移除 复盘课"]'
    ) as HTMLButtonElement;
    remove.click();
    await flush();
    expect(el.textContent).toContain("已选 1 条");
  });

  it("创建本批只提交未存在的勾选项", async () => {
    const picked: CatalogPreviewItem[][] = [];
    const items = [
      makeItem({ source_url: "https://a.example/1", title: "新课" }),
      makeItem({
        source_url: "https://a.example/2",
        title: "旧课",
        exists: true,
      }),
    ];
    const { el } = await mountDialog(items, (next) => picked.push(next));
    const submit = [...el.querySelectorAll("button")].find(
      (btn) => btn.textContent?.trim() === "创建本批"
    ) as HTMLButtonElement;
    submit.click();
    await flush();
    expect(picked).toHaveLength(1);
    expect(picked[0].map((item) => item.title)).toEqual(["新课"]);
  });
});
