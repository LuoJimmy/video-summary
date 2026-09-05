import { createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Job } from "../api";
import JobsView from "./JobsView.vue";

vi.mock("../api", () => ({
  api: {
    jobs: vi.fn(),
    sites: vi.fn(),
    updateJob: vi.fn(),
    cancelJob: vi.fn(),
    deleteJob: vi.fn(),
    preview: vi.fn(),
    createJob: vi.fn(),
    uploadJob: vi.fn(),
    settings: vi.fn(),
  },
}));

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    title: "卖票方法",
    source_url: "https://cdn.example.com/a.mp4",
    source_type: "direct",
    site_id: null,
    auth_profile_id: null,
    media_url: "",
    media_url_override: "",
    status: "done",
    stage: "done",
    progress: 100,
    error: "",
    transcript: [],
    summary: null,
    timing: {},
    started_at: "2026-09-02T06:00:00Z",
    source_created_at: "2026-08-13T04:00:00Z",
    created_at: "2026-09-02T06:00:00Z",
    updated_at: "2026-09-02T06:00:00Z",
    ...overrides,
  };
}

let root: HTMLElement | undefined;
let app: ReturnType<typeof createApp> | undefined;

async function flush() {
  for (let i = 0; i < 8; i++) await Promise.resolve();
  await nextTick();
}

async function mountJobs(items: Job[] = [makeJob()], total = items.length) {
  vi.mocked(api.jobs).mockResolvedValue({
    items,
    total,
    page: 1,
    page_size: 10,
  });
  vi.mocked(api.sites).mockResolvedValue([]);
  vi.mocked(api.settings).mockResolvedValue({
    transcribe_base_url: "",
    transcribe_api_key: "",
    transcribe_model: "",
    summarize_base_url: "",
    summarize_api_key: "",
    summarize_model: "",
    capture_seconds: "180",
    summarize_concurrency: 3,
    transcribe_threads: 4,
    transcribe_fast: false,
    cpu_count: 10,
    ai_proofread: true,
    show_transcript: true,
    domain_presets: [
      { id: "a-share", name: "A股盘面课" },
      { id: "generic", name: "通用课程" },
    ],
  } as never);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: JobsView },
      { path: "/jobs/:id", component: { template: "<div />" } },
    ],
  });
  await router.push("/");
  await router.isReady();
  root = document.createElement("div");
  document.body.appendChild(root);
  app = createApp(JobsView);
  app.use(router);
  app.mount(root);
  await flush();
  return root;
}

afterEach(() => {
  app?.unmount();
  root?.remove();
  root = undefined;
  app = undefined;
});

beforeEach(() => {
  vi.mocked(api.jobs).mockReset();
  vi.mocked(api.sites).mockReset();
});

function clickNamed(el: HTMLElement, name: string) {
  const btn = [...el.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === name
  ) as HTMLButtonElement;
  btn.click();
}

describe("任务列表筛选", () => {
  it("展示标题、时间、状态和查询重置", async () => {
    const el = await mountJobs();
    expect(el.querySelector("input[placeholder='标题']")).toBeTruthy();
    expect(el.querySelector("input[aria-label='开始日期']")).toBeTruthy();
    expect(el.querySelector("input[aria-label='结束日期']")).toBeTruthy();
    expect(el.querySelector(".job-filters [aria-label='状态']")).toBeTruthy();
    expect(el.querySelector(".job-filters")?.textContent).toContain("查询");
    expect(el.querySelector(".job-filters")?.textContent).toContain("重置");
    expect(el.querySelector(".pager")?.textContent).not.toContain("清除筛选");
    expect(el.querySelector(".pager")?.textContent).not.toContain("查询");
    expect(el.textContent).toContain("内容领域");
    expect(el.textContent).toContain("A股盘面课");
  });

  it("按标题筛选时把关键字传给列表接口", async () => {
    const el = await mountJobs();
    vi.mocked(api.jobs).mockClear();
    const input = el.querySelector(
      "input[placeholder='标题']"
    ) as HTMLInputElement;
    input.value = "卖票";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    clickNamed(el, "查询");
    await flush();
    expect(api.jobs).toHaveBeenCalledWith(
      1,
      10,
      expect.objectContaining({ title: "卖票" })
    );
  });

  it("按日期筛选时传本地日界的 utc 时间", async () => {
    const el = await mountJobs();
    vi.mocked(api.jobs).mockClear();
    const from = el.querySelector(
      "input[aria-label='开始日期']"
    ) as HTMLInputElement;
    const to = el.querySelector(
      "input[aria-label='结束日期']"
    ) as HTMLInputElement;
    from.value = "2026-08-13";
    from.dispatchEvent(new Event("input", { bubbles: true }));
    to.value = "2026-08-13";
    to.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    clickNamed(el, "查询");
    await flush();
    expect(api.jobs).toHaveBeenCalledWith(
      1,
      10,
      expect.objectContaining({
        dateFrom: new Date("2026-08-13T00:00:00").toISOString(),
        dateTo: new Date("2026-08-14T00:00:00").toISOString(),
      })
    );
  });

  it("没有匹配时提示没有符合条件的任务", async () => {
    const el = await mountJobs([makeJob()]);
    vi.mocked(api.jobs).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 10,
    });
    const input = el.querySelector(
      "input[placeholder='标题']"
    ) as HTMLInputElement;
    input.value = "不存在";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    clickNamed(el, "查询");
    await flush();
    expect(el.textContent).toContain("没有符合条件的任务。");
    expect(el.querySelector(".pager")?.textContent).not.toContain("清除筛选");
  });

  it("重置会清空条件并重新拉列表", async () => {
    const el = await mountJobs();
    const input = el.querySelector(
      "input[placeholder='标题']"
    ) as HTMLInputElement;
    input.value = "卖票";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    clickNamed(el, "查询");
    await flush();
    vi.mocked(api.jobs).mockClear();
    clickNamed(el, "重置");
    await flush();
    expect(api.jobs).toHaveBeenCalledWith(1, 10, {});
    expect(
      (el.querySelector("input[placeholder='标题']") as HTMLInputElement).value
    ).toBe("");
  });
});
