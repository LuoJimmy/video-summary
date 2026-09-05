import { createApp } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it } from "vitest";
import App from "./App.vue";

const stub = { template: "<div />" };
let root: HTMLElement | undefined;

async function mountAt(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: stub },
      { path: "/jobs/:id", component: stub },
      { path: "/knowledge", component: stub },
      { path: "/sites", component: stub },
      { path: "/settings", component: stub },
      { path: "/settings/changelog", component: stub },
    ],
  });
  await router.push(path);
  await router.isReady();
  root = document.createElement("div");
  document.body.appendChild(root);
  const app = createApp(App);
  app.use(router);
  app.mount(root);
  return root;
}

function jobLinkClass(el: HTMLElement) {
  const link = [...el.querySelectorAll(".nav-links a")].find((a) =>
    (a.textContent || "").includes("任务")
  );
  return link?.className || "";
}

afterEach(() => {
  root?.remove();
  root = undefined;
});

describe("任务导航高亮", () => {
  it("在任务列表页高亮", async () => {
    const el = await mountAt("/");
    expect(jobLinkClass(el)).toContain("router-link-active");
  });

  it("在任务详情页高亮", async () => {
    const el = await mountAt("/jobs/abc123");
    expect(jobLinkClass(el)).toContain("router-link-active");
  });

  it("在其他页面不高亮", async () => {
    const el = await mountAt("/knowledge");
    expect(jobLinkClass(el)).not.toContain("router-link-active");
  });

  it("在更新日志页高亮设置", async () => {
    const el = await mountAt("/settings/changelog");
    const link = [...el.querySelectorAll(".nav-links a")].find((a) =>
      (a.textContent || "").includes("设置")
    );
    expect(link?.className).toContain("router-link-active");
    expect(jobLinkClass(el)).not.toContain("router-link-active");
  });

  it("每项菜单都有对应图标", async () => {
    const el = await mountAt("/");
    const links = [...el.querySelectorAll(".nav-links a")];
    expect(links.map((link) => link.textContent?.replace(/\s+/g, ""))).toEqual([
      "任务",
      "知识库",
      "站点",
      "设置",
    ]);
    expect(links.every((link) => link.querySelector("svg"))).toBe(true);
  });
});
