import { createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it } from "vitest";
import { version as appVersion } from "../../package.json";
import ChangelogView from "./ChangelogView.vue";

let root: HTMLElement | undefined;
let app: ReturnType<typeof createApp> | undefined;

afterEach(() => {
  app?.unmount();
  root?.remove();
  root = undefined;
  app = undefined;
});

async function mountChangelog() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/settings", component: { template: "<div>settings</div>" } },
      { path: "/settings/changelog", component: ChangelogView },
    ],
  });
  await router.push("/settings/changelog");
  await router.isReady();
  root = document.createElement("div");
  document.body.appendChild(root);
  app = createApp(ChangelogView);
  app.use(router);
  app.mount(root);
  await nextTick();
  return root;
}

describe("更新日志页", () => {
  it("展示当前版本记录并提供返回设置入口", async () => {
    const el = await mountChangelog();
    expect(el.querySelector("h1")?.textContent).toBe("更新日志");
    expect(el.textContent).toContain(appVersion);
    expect(el.textContent).toContain("2026-09-05");
    expect(el.textContent).toContain("新增");
    const back = el.querySelector('a[href="/settings"]');
    expect(back?.getAttribute("aria-label")).toBe("返回设置");
  });
});
