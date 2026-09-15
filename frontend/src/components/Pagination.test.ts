import { createApp, nextTick, ref } from "vue";
import { afterEach, describe, expect, it } from "vitest";
import Pagination from "./Pagination.vue";

let root: HTMLElement | undefined;
let app: ReturnType<typeof createApp> | undefined;

async function flush() {
  for (let i = 0; i < 8; i++) await Promise.resolve();
  await nextTick();
}

async function mountPager(total = 307, initialPage = 1, initialSize = 20) {
  const page = ref(initialPage);
  const pageSize = ref(initialSize);
  const Root = {
    components: { Pagination },
    setup() {
      return { total, page, pageSize };
    },
    template: `
      <Pagination
        :total="total"
        :page="page"
        :page-size="pageSize"
        @update:page="page = $event"
        @update:page-size="pageSize = $event"
      />
    `,
  };
  root = document.createElement("div");
  document.body.appendChild(root);
  app = createApp(Root);
  app.mount(root);
  await flush();
  return { el: root, page, pageSize };
}

afterEach(() => {
  app?.unmount();
  root?.remove();
  root = undefined;
  app = undefined;
});

describe("分页器", () => {
  it("展示总数、页码、每页条数和跳转", async () => {
    const { el } = await mountPager();
    expect(el.textContent).toContain("共 307 条数据");
    expect(el.textContent).toContain("20条/页");
    expect(el.textContent).toContain("跳至");
    expect(el.querySelector('[aria-label="上一页"]')).toBeTruthy();
    expect(el.querySelector('[aria-label="下一页"]')).toBeTruthy();
    expect(el.querySelector('[aria-label="跳至页码"]')).toBeTruthy();
    expect(
      [...el.querySelectorAll(".pager-item")].map((item) =>
        item.textContent?.trim()
      )
    ).toEqual(["1", "2", "3", "4", "5", "16"]);
    expect(el.querySelector(".pager-ellipsis")).toBeTruthy();
    expect(
      (el.querySelector('[aria-label="上一页"]') as HTMLButtonElement).disabled
    ).toBe(true);
  });

  it("点击页码和下一页会更新当前页", async () => {
    const { el, page } = await mountPager();
    (el.querySelector('[aria-label="第 2 页"]') as HTMLButtonElement).click();
    await flush();
    expect(page.value).toBe(2);
    (el.querySelector('[aria-label="下一页"]') as HTMLButtonElement).click();
    await flush();
    expect(page.value).toBe(3);
  });

  it("跳至页码并在越界时收束到有效页", async () => {
    const { el, page } = await mountPager();
    const input = el.querySelector(
      '[aria-label="跳至页码"]'
    ) as HTMLInputElement;
    input.value = "16";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", bubbles: true })
    );
    await flush();
    expect(page.value).toBe(16);

    input.value = "99";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    await flush();
    expect(page.value).toBe(16);
  });
});
