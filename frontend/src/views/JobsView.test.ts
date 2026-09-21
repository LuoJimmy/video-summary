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
    fromCatalog: vi.fn(),
    uploadJob: vi.fn(),
    localEntries: vi.fn(),
    localRoot: vi.fn(),
    batchJobs: vi.fn(),
    digestJobs: vi.fn(),
    settings: vi.fn(),
  },
}));

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    title: "卖票方法",
    author: "",
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
let mountedRouter: ReturnType<typeof createRouter> | undefined;

async function flush() {
  for (let i = 0; i < 8; i++) await Promise.resolve();
  await nextTick();
}

async function mountJobs(
  items: Job[] = [makeJob()],
  total = items.length,
  options: { mediaRoot?: boolean } = {}
) {
  vi.mocked(api.jobs).mockResolvedValue({
    items,
    total,
    page: 1,
    page_size: 10,
  });
  vi.mocked(api.sites).mockResolvedValue([]);
  vi.mocked(api.localRoot).mockResolvedValue(
    options.mediaRoot
      ? { enabled: true, root: "/media", scan_limit: 1000 }
      : { enabled: false, root: "", scan_limit: 1000 }
  );
  vi.mocked(api.localEntries).mockResolvedValue({
    root: "/media",
    path: "/media",
    parent: "",
    recursive: false,
    query: "",
    page: 1,
    page_size: 50,
    total: 0,
    truncated: false,
    entries: [],
  });
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
  mountedRouter = router;
  app.mount(root);
  await flush();
  return root;
}

afterEach(() => {
  app?.unmount();
  root?.remove();
  root = undefined;
  app = undefined;
  mountedRouter = undefined;
});

beforeEach(() => {
  vi.mocked(api.jobs).mockReset();
  vi.mocked(api.sites).mockReset();
  vi.mocked(api.createJob).mockReset();
  vi.mocked(api.fromCatalog).mockReset();
  vi.mocked(api.preview).mockReset();
  vi.mocked(api.uploadJob).mockReset();
  vi.mocked(api.localEntries).mockReset();
  vi.mocked(api.localRoot).mockReset();
  vi.mocked(api.batchJobs).mockReset();
  vi.mocked(api.digestJobs).mockReset();
  vi.mocked(api.deleteJob).mockReset();
});

function clickLocalMode(el: HTMLElement, value: "upload" | "media") {
  const radio = el.querySelector(
    `input[type="radio"][name="local-mode"][value="${value}"]`
  ) as HTMLInputElement;
  radio.click();
}

function clickNamed(el: HTMLElement, name: string) {
  const btn = [...el.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === name
  ) as HTMLButtonElement;
  btn.click();
}

describe("任务列表筛选", () => {
  it("展示标题、时间、状态和查询重置", async () => {
    const el = await mountJobs();
    expect(el.querySelector("input[placeholder='标题 / 作者']")).toBeTruthy();
    expect(el.querySelector("input[placeholder='标题']")).toBeFalsy();
    expect(el.querySelector("input[placeholder='作者']")).toBeFalsy();
    expect(el.querySelector("input[aria-label='开始日期']")).toBeTruthy();
    expect(el.querySelector("input[aria-label='结束日期']")).toBeTruthy();
    expect(el.querySelector(".job-filters [aria-label='状态']")).toBeTruthy();
    const sortTrigger = el.querySelector(
      ".job-filters [aria-label='排序']"
    ) as HTMLElement | null;
    expect(sortTrigger).toBeTruthy();
    expect(sortTrigger?.querySelector("svg")).toBeTruthy();
    expect(sortTrigger?.classList.contains("sort-trigger")).toBe(true);
    expect(
      el.querySelector(".job-filters [aria-label='排序方向']")
    ).toBeFalsy();
    expect(el.querySelector(".job-filters")?.textContent).toContain(
      "任务时间 降序"
    );
    expect(api.jobs).toHaveBeenCalledWith(1, 10, { sort: "created" });
    expect(el.querySelector(".job-filters")?.textContent).toContain("查询");
    expect(el.querySelector(".job-filters")?.textContent).toContain("重置");
    expect(el.querySelector(".pager")?.textContent).not.toContain("清除筛选");
    expect(el.querySelector(".pager")?.textContent).not.toContain("查询");
    expect(el.textContent).toContain("内容领域");
    expect(el.textContent).toContain("A股盘面课");
    expect(el.textContent).toContain("视频作者");
    expect(el.textContent).not.toContain("媒体地址覆盖");
  });

  it("解析失败任务出现后才展开媒体地址覆盖", async () => {
    const el = await mountJobs([
      makeJob({
        status: "failed",
        stage: "failed",
        error: "无法解析媒体地址，请填写媒体地址覆盖后重试",
      }),
    ]);
    expect(el.textContent).toContain("媒体地址覆盖");
  });

  it("按标题筛选时把关键字传给列表接口", async () => {
    const el = await mountJobs();
    vi.mocked(api.jobs).mockClear();
    const input = el.querySelector(
      "input[placeholder='标题 / 作者']"
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

  it("按作者筛选时把同一关键字传给列表接口", async () => {
    const el = await mountJobs();
    vi.mocked(api.jobs).mockClear();
    const input = el.querySelector(
      "input[placeholder='标题 / 作者']"
    ) as HTMLInputElement;
    input.value = "加菲";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    clickNamed(el, "查询");
    await flush();
    expect(api.jobs).toHaveBeenCalledWith(
      1,
      10,
      expect.objectContaining({ title: "加菲" })
    );
  });

  it("列表在地址前展示作者并用间隔符隔开", async () => {
    const el = await mountJobs([makeJob({ author: "加菲财经" })]);
    expect(el.querySelector(".list-item .msg")?.textContent).toBe(
      "加菲财经 · https://cdn.example.com/a.mp4"
    );
  });

  it("本地上传不展示文件路径", async () => {
    const el = await mountJobs([
      makeJob({
        author: "自己",
        source_url: "/downloads/job-1/source.pdf",
        source_type: "local_document",
      }),
    ]);
    expect(el.querySelector(".list-item .msg")?.textContent).toBe("自己");
    expect(el.textContent).not.toContain("/downloads/");
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
      "input[placeholder='标题 / 作者']"
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
      "input[placeholder='标题 / 作者']"
    ) as HTMLInputElement;
    input.value = "卖票";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    clickNamed(el, "查询");
    await flush();
    vi.mocked(api.jobs).mockClear();
    clickNamed(el, "重置");
    await flush();
    expect(api.jobs).toHaveBeenCalledWith(1, 10, { sort: "created" });
    expect(
      (el.querySelector("input[placeholder='标题 / 作者']") as HTMLInputElement)
        .value
    ).toBe("");
  });
});

function clickCreateTab(el: HTMLElement, label: string) {
  const tab = [...el.querySelectorAll('[role="tab"]')].find(
    (item) => item.textContent?.trim() === label
  ) as HTMLButtonElement | undefined;
  expect(tab).toBeTruthy();
  tab?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
}

describe("文档来源", () => {
  it("用 tab 切换在线任务和本地任务", async () => {
    const el = await mountJobs();
    const tabs = [...el.querySelectorAll('[role="tab"]')].map(
      (item) => item.textContent?.trim() || ""
    );
    expect(tabs).toEqual(["在线任务", "本地任务"]);
    const online = el.querySelector("#create-panel-online") as HTMLElement;
    const local = el.querySelector("#create-panel-local") as HTMLElement;
    expect(online.style.display).not.toBe("none");
    expect(local.style.display).toBe("none");
    expect(el.textContent).toContain("开始转写总结");
    clickCreateTab(el, "本地任务");
    await flush();
    expect(local.style.display).not.toBe("none");
    expect(online.style.display).toBe("none");
    expect(el.textContent).toContain("上传并处理");
    expect(el.textContent).toContain("文档生成 AI 总结");
    expect(el.querySelector("#summarize-document")).toBeTruthy();
  });

  it("上传接受文档并默认不勾选总结", async () => {
    const el = await mountJobs();
    clickCreateTab(el, "本地任务");
    await flush();
    expect(el.textContent).toContain("文档生成 AI 总结");
    const hint = el.querySelector(".info-tip") as HTMLButtonElement | null;
    expect(hint).toBeTruthy();
    expect(hint?.querySelector("svg")).toBeTruthy();
    expect(hint?.querySelector(".info-tip-text")?.textContent).toContain(
      "文档/网页默认直接入库原文；勾选后才调用总结模型。音视频始终会总结。"
    );
    const file = el.querySelector("input[type='file']") as HTMLInputElement;
    expect(file.accept).toContain(".pdf");
    expect(file.accept).toContain(".doc");
    expect(file.multiple).toBe(true);
    const pick = [...el.querySelectorAll("button")].find((item) =>
      item.textContent?.includes("选择文件")
    );
    expect(pick).toBeTruthy();
    expect(pick?.querySelector("svg")).toBeTruthy();
    expect(el.textContent).toContain("未选择文件");
    const box = el.querySelector("#summarize-document");
    expect(
      box?.getAttribute("data-state") || box?.getAttribute("aria-checked")
    ).not.toBe("true");
  });
});

function toolbarButton(el: HTMLElement, name: string) {
  return [...el.querySelectorAll(".list-toolbar button")].find(
    (item) => item.textContent?.trim() === name
  ) as HTMLButtonElement | undefined;
}

describe("批量创建", () => {
  it("多行地址会多次创建并留在列表", async () => {
    const el = await mountJobs();
    vi.mocked(api.createJob).mockImplementation(async (payload) =>
      makeJob({
        id: String(payload.source_url).slice(-5),
        source_url: String(payload.source_url),
      })
    );
    const area = el.querySelector("textarea") as HTMLTextAreaElement;
    area.value =
      "https://cdn.example.com/a.mp4\nhttps://cdn.example.com/b.mp4\n";
    area.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    vi.mocked(api.jobs).mockClear();
    clickNamed(el, "开始转写总结");
    await flush();
    await flush();
    expect(api.createJob).toHaveBeenCalledTimes(2);
    expect(api.createJob).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ source_url: "https://cdn.example.com/a.mp4" })
    );
    expect(api.createJob).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ source_url: "https://cdn.example.com/b.mp4" })
    );
    expect(mountedRouter?.currentRoute.value.path).toBe("/");
    expect(api.jobs).toHaveBeenCalled();
  });

  it("单条地址创建后进入详情", async () => {
    const el = await mountJobs();
    const push = vi.spyOn(mountedRouter!, "push");
    vi.mocked(api.createJob).mockResolvedValue(makeJob({ id: "job-9" }));
    const area = el.querySelector("textarea") as HTMLTextAreaElement;
    area.value = "https://cdn.example.com/a.mp4";
    area.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    clickNamed(el, "开始转写总结");
    await flush();
    await flush();
    await flush();
    expect(api.createJob).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledWith("/jobs/job-9");
  });

  it("多文件会多次上传并留在列表", async () => {
    const el = await mountJobs();
    clickCreateTab(el, "本地任务");
    await flush();
    vi.mocked(api.uploadJob).mockImplementation(async (file) =>
      makeJob({ id: file.name, title: file.name })
    );
    const input = el.querySelector("input[type='file']") as HTMLInputElement;
    Object.defineProperty(input, "files", {
      configurable: true,
      value: [new File(["a"], "a.mp4"), new File(["b"], "b.mp4")],
    });
    input.dispatchEvent(new Event("change", { bubbles: true }));
    await flush();
    expect(el.textContent).toContain("已选 2 个文件");
    expect(el.querySelector('[aria-label="移除 a.mp4"]')).toBeTruthy();
    vi.mocked(api.jobs).mockClear();
    clickNamed(el, "上传并处理");
    await flush();
    await flush();
    expect(api.uploadJob).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.uploadJob).mock.calls[0][0].name).toBe("a.mp4");
    expect(vi.mocked(api.uploadJob).mock.calls[1][0].name).toBe("b.mp4");
    expect(mountedRouter?.currentRoute.value.path).toBe("/");
    expect(api.jobs).toHaveBeenCalled();
  });

  it("可从已选文件中移除一项", async () => {
    const el = await mountJobs();
    clickCreateTab(el, "本地任务");
    await flush();
    vi.mocked(api.uploadJob).mockImplementation(async (file) =>
      makeJob({ id: file.name, title: file.name })
    );
    const input = el.querySelector("input[type='file']") as HTMLInputElement;
    Object.defineProperty(input, "files", {
      configurable: true,
      value: [new File(["a"], "a.mp4"), new File(["b"], "b.mp4")],
    });
    input.dispatchEvent(new Event("change", { bubbles: true }));
    await flush();
    const remove = el.querySelector(
      '[aria-label="移除 a.mp4"]'
    ) as HTMLButtonElement;
    remove.click();
    await flush();
    expect(el.textContent).not.toContain("已选 2 个文件");
    expect(el.textContent).toContain("b.mp4");
    expect(el.querySelector('[aria-label="移除 a.mp4"]')).toBeFalsy();
    clickNamed(el, "上传并处理");
    await flush();
    await flush();
    expect(api.uploadJob).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.uploadJob).mock.calls[0][0].name).toBe("b.mp4");
  });

  it("没有挂载媒体目录时只有本地上传单选", async () => {
    const el = await mountJobs();
    clickCreateTab(el, "本地任务");
    await flush();
    const radios = el.querySelectorAll(
      'input[type="radio"][name="local-mode"]'
    );
    expect(radios.length).toBe(1);
    expect((radios[0] as HTMLInputElement).value).toBe("upload");
    expect((radios[0] as HTMLInputElement).checked).toBe(true);
    expect(el.textContent).toContain("从本地选择");
    expect(el.textContent).not.toContain("从挂载目录选择");
    expect(api.localEntries).not.toHaveBeenCalled();
  });

  it("有挂载目录时从弹框多选文件创建任务", async () => {
    const el = await mountJobs([makeJob()], 1, { mediaRoot: true });
    vi.mocked(api.localEntries).mockResolvedValue({
      root: "/media",
      path: "/media",
      parent: "",
      recursive: false,
      query: "",
      page: 1,
      page_size: 50,
      total: 2,
      truncated: false,
      entries: [
        {
          name: "2026",
          path: "/media/2026",
          kind: "dir",
          size: 0,
          modified_at: null,
          supported: false,
        },
        {
          name: "a.mp4",
          path: "/media/a.mp4",
          kind: "file",
          size: 2048,
          modified_at: null,
          supported: true,
        },
      ],
    });
    clickCreateTab(el, "本地任务");
    await flush();
    expect(el.textContent).toContain("从挂载目录选择");

    clickLocalMode(el, "media");
    await flush();
    clickNamed(el, "选择文件 / 文件夹");
    await flush();
    await flush();

    const dialog = document.body.querySelector(
      ".local-picker-dialog"
    ) as HTMLElement | null;
    expect(dialog).toBeTruthy();
    expect(api.localEntries).toHaveBeenCalledWith("/media", {
      query: "",
      page: 1,
      pageSize: 50,
    });

    const checkbox = dialog?.querySelector(
      '[aria-label="选择 a.mp4"]'
    ) as HTMLElement;
    checkbox.click();
    await flush();
    clickNamed(dialog as HTMLElement, "确定");
    await flush();

    expect(el.textContent).toContain("已选 1 / 1000");
    vi.mocked(api.createJob).mockResolvedValue(makeJob({ id: "job-media" }));
    clickNamed(el, "创建 1 个任务");
    await flush();
    await flush();
    await flush();
    expect(api.createJob).toHaveBeenCalledWith(
      expect.objectContaining({ source_url: "/media/a.mp4" })
    );
  });

  it("挂载目录模式下提供选择入口并可切回上传", async () => {
    const el = await mountJobs([makeJob()], 1, { mediaRoot: true });
    clickCreateTab(el, "本地任务");
    await flush();
    const radios = el.querySelectorAll(
      'input[type="radio"][name="local-mode"]'
    );
    expect(radios.length).toBe(2);

    clickLocalMode(el, "media");
    await flush();
    expect(
      (
        el.querySelector(
          'input[type="radio"][name="local-mode"][value="media"]'
        ) as HTMLInputElement
      ).checked
    ).toBe(true);
    expect(el.textContent).toContain("已选 0 / 1000");
    expect(el.textContent).toContain("选择文件 / 文件夹");
    expect(el.textContent).not.toContain("上传并处理");
    expect(api.localEntries).not.toHaveBeenCalled();

    clickLocalMode(el, "upload");
    await flush();
    expect(
      (
        el.querySelector(
          'input[type="radio"][name="local-mode"][value="upload"]'
        ) as HTMLInputElement
      ).checked
    ).toBe(true);
    expect(el.textContent).toContain("上传并处理");
  });
});

describe("批量管理", () => {
  it("未选中时仍保留批量操作栏占位", async () => {
    const el = await mountJobs();
    const meta = el.querySelector(".list-toolbar-meta") as HTMLElement | null;
    expect(meta).toBeTruthy();
    expect(meta?.classList.contains("is-idle")).toBe(true);
    expect(toolbarButton(el, "汇总总结")).toBeTruthy();
    expect(toolbarButton(el, "删除")?.disabled).toBe(true);
  });

  it("全选后批量删除走确认", async () => {
    const items = [
      makeJob({ id: "job-1", title: "甲" }),
      makeJob({ id: "job-2", title: "乙" }),
    ];
    const el = await mountJobs(items);
    vi.mocked(api.batchJobs).mockResolvedValue({
      ok: ["job-1", "job-2"],
      failed: [],
    });
    const selectAll = el.querySelector(
      '[aria-label="全选当前页"]'
    ) as HTMLElement;
    selectAll.click();
    await flush();
    expect(el.textContent).toContain("已选 2");
    toolbarButton(el, "删除")?.click();
    await flush();
    expect(document.body.textContent).toContain("确定删除 2 个任务");
    expect(api.batchJobs).not.toHaveBeenCalled();
    const confirm = [...document.body.querySelectorAll("button")].find(
      (item) => item.textContent?.trim() === "确认删除"
    ) as HTMLButtonElement;
    confirm.click();
    await flush();
    await flush();
    expect(api.batchJobs).toHaveBeenCalledWith("delete", ["job-1", "job-2"]);
    expect(api.deleteJob).not.toHaveBeenCalled();
  });

  it("多选后可创建汇总总结", async () => {
    const items = [
      makeJob({ id: "job-1", title: "甲" }),
      makeJob({ id: "job-2", title: "乙" }),
    ];
    const el = await mountJobs(items);
    const push = vi.spyOn(mountedRouter!, "push");
    vi.mocked(api.digestJobs).mockResolvedValue(
      makeJob({
        id: "digest-1",
        title: "2026-09-17 11:00 汇总",
        source_type: "digest",
        source_url: "digest://job-1,job-2",
      })
    );
    const selectAll = el.querySelector(
      '[aria-label="全选当前页"]'
    ) as HTMLElement;
    selectAll.click();
    await flush();
    toolbarButton(el, "汇总总结")?.click();
    await flush();
    await flush();
    await flush();
    expect(api.digestJobs).toHaveBeenCalledWith(["job-1", "job-2"]);
    expect(push).toHaveBeenCalledWith("/jobs/digest-1");
  });

  it("只选一个任务时禁用汇总", async () => {
    const el = await mountJobs([makeJob({ status: "done", stage: "done" })]);
    const selectAll = el.querySelector(
      '[aria-label="全选当前页"]'
    ) as HTMLElement;
    selectAll.click();
    await flush();
    expect(toolbarButton(el, "汇总总结")?.disabled).toBe(true);
    expect(toolbarButton(el, "取消")?.disabled).toBe(true);
    expect(toolbarButton(el, "重试")?.disabled).toBe(true);
    expect(toolbarButton(el, "删除")?.disabled).toBe(false);
  });

  it("所选都不可取消时禁用取消和重试", async () => {
    const items = [
      makeJob({ id: "job-1", status: "done", stage: "done" }),
      makeJob({ id: "job-2", status: "done", stage: "done" }),
    ];
    const el = await mountJobs(items);
    const selectAll = el.querySelector(
      '[aria-label="全选当前页"]'
    ) as HTMLElement;
    selectAll.click();
    await flush();
    expect(toolbarButton(el, "汇总总结")?.disabled).toBe(false);
    expect(toolbarButton(el, "取消")?.disabled).toBe(true);
    expect(toolbarButton(el, "重试")?.disabled).toBe(true);
    expect(toolbarButton(el, "删除")?.disabled).toBe(false);
  });

  it("所选含处理中时仅取消可用，失败任务可重试", async () => {
    const items = [
      makeJob({ id: "job-1", status: "running", stage: "transcribing" }),
      makeJob({ id: "job-2", status: "failed", stage: "failed" }),
    ];
    const el = await mountJobs(items);
    const selectAll = el.querySelector(
      '[aria-label="全选当前页"]'
    ) as HTMLElement;
    selectAll.click();
    await flush();
    expect(toolbarButton(el, "汇总总结")?.disabled).toBe(true);
    expect(toolbarButton(el, "取消")?.disabled).toBe(false);
    expect(toolbarButton(el, "重试")?.disabled).toBe(false);
  });

  it("所选含汇总任务时不计入可汇总数量", async () => {
    const items = [
      makeJob({ id: "job-1", status: "done", stage: "done" }),
      makeJob({
        id: "job-2",
        status: "done",
        stage: "done",
        source_type: "digest",
      }),
    ];
    const el = await mountJobs(items);
    const selectAll = el.querySelector(
      '[aria-label="全选当前页"]'
    ) as HTMLElement;
    selectAll.click();
    await flush();
    expect(toolbarButton(el, "汇总总结")?.disabled).toBe(true);
  });
});

describe("任务列表分页", () => {
  it("展示增强分页器并按页请求", async () => {
    const firstPage = Array.from({ length: 10 }, (_, index) =>
      makeJob({ id: `job-${index}`, title: `课${index}` })
    );
    const el = await mountJobs(firstPage, 12);
    expect(el.querySelector(".pager")?.textContent).toContain("共 12 条数据");
    expect(el.querySelector(".pager")?.textContent).toContain("10条/页");
    expect(el.querySelector('[aria-label="跳至页码"]')).toBeTruthy();
    expect(
      el.querySelector('.pager [aria-current="page"]')?.textContent?.trim()
    ).toBe("1");

    vi.mocked(api.jobs).mockResolvedValue({
      items: [makeJob({ id: "job-10", title: "课10" })],
      total: 12,
      page: 2,
      page_size: 10,
    });
    (el.querySelector('[aria-label="下一页"]') as HTMLButtonElement).click();
    await flush();
    expect(api.jobs).toHaveBeenCalledWith(2, 10, expect.any(Object));
    expect(el.textContent).toContain("课10");
    expect(
      el.querySelector('.pager [aria-current="page"]')?.textContent?.trim()
    ).toBe("2");
  });
});

describe("整站目录拉取", () => {
  it("粘贴空间页会弹出确认框并走 from-catalog", async () => {
    const el = await mountJobs();
    vi.mocked(api.preview).mockResolvedValue({
      adapter: "bilibili",
      title: "B 站 UP 空间",
      source_type: "catalog",
      media_url: "",
      needs_media_url: false,
      message: "本批 1 条",
      catalog: true,
      catalog_label: "B 站 UP 空间",
      listed: 1,
      existing: 0,
      next_cursor: "next-token",
      truncated: false,
      items: [
        {
          source_url: "https://www.bilibili.com/video/BV1new000002",
          title: "新稿",
          author: "UP",
          created_at: "2026-08-14T04:00:00Z",
          exists: false,
        },
      ],
    });
    vi.mocked(api.fromCatalog).mockResolvedValue({
      created: 1,
      skipped: 0,
      next_cursor: "next-token",
      truncated: false,
      message: "已创建 1 个任务。该B 站 UP 空间还有后续内容。",
      catalog_label: "B 站 UP 空间",
    });
    const textarea = el.querySelector("textarea") as HTMLTextAreaElement;
    textarea.value = "https://space.bilibili.com/11430504";
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    const start = [...el.querySelectorAll("button")].find(
      (btn) => btn.textContent?.trim() === "开始转写总结"
    ) as HTMLButtonElement;
    start.click();
    await flush();
    expect(document.body.textContent).toContain("确认拉取B 站 UP 空间");
    const submit = [...document.body.querySelectorAll("button")].find(
      (btn) => btn.textContent?.trim() === "创建本批"
    ) as HTMLButtonElement;
    submit.click();
    await flush();
    expect(api.createJob).not.toHaveBeenCalled();
    expect(api.fromCatalog).toHaveBeenCalled();
    expect(el.textContent).toContain("继续拉取下一批");
  });

  it("单视频不弹目录确认框", async () => {
    const el = await mountJobs();
    vi.mocked(api.createJob).mockResolvedValue(makeJob({ id: "job-new" }));
    const textarea = el.querySelector("textarea") as HTMLTextAreaElement;
    textarea.value = "https://www.bilibili.com/video/BV1a4awzsENn";
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    const start = [...el.querySelectorAll("button")].find(
      (btn) => btn.textContent?.trim() === "开始转写总结"
    ) as HTMLButtonElement;
    start.click();
    await flush();
    expect(api.createJob).toHaveBeenCalled();
    expect(api.fromCatalog).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain("确认拉取");
  });

  it("空间页拉取等待时按钮显示 loading", async () => {
    const el = await mountJobs();
    let release!: (value: unknown) => void;
    vi.mocked(api.preview).mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        })
    );
    const textarea = el.querySelector("textarea") as HTMLTextAreaElement;
    textarea.value = "https://space.bilibili.com/11430504/video";
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    expect(
      [...el.querySelectorAll("button")].some(
        (btn) => btn.textContent?.trim() === "预解析"
      )
    ).toBe(false);
    const start = [...el.querySelectorAll("button")].find((btn) =>
      btn.textContent?.includes("开始转写总结")
    ) as HTMLButtonElement;
    start.click();
    await flush();
    expect(start.getAttribute("aria-busy")).toBe("true");
    expect(start.disabled).toBe(true);
    expect(start.textContent).toContain("解析中");
    expect(start.querySelector(".animate-spin")).toBeTruthy();
    release({
      adapter: "bilibili",
      title: "B 站 UP 空间",
      source_type: "catalog",
      media_url: "",
      needs_media_url: false,
      message: "本批 1 条",
      catalog: true,
      catalog_label: "B 站 UP 空间",
      listed: 1,
      existing: 0,
      next_cursor: "",
      truncated: false,
      items: [
        {
          source_url: "https://www.bilibili.com/video/BV1new000002",
          title: "新稿",
          author: "UP",
          created_at: "2026-08-14T04:00:00Z",
          exists: false,
        },
      ],
    });
    await flush();
    expect(document.body.textContent).toContain("确认拉取B 站 UP 空间");
    expect(start.getAttribute("aria-busy")).not.toBe("true");
  });
});
