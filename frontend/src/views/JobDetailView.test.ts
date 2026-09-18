import { createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "vue-sonner";
import { api, type AppSettings, type Job } from "../api";
import { formatDateTime } from "../utils/time";
import JobDetailView from "./JobDetailView.vue";

vi.mock("vue-sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}));

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    api: {
      settings: vi.fn(),
      job: vi.fn(),
      jobMedia: vi.fn(),
      updateJob: vi.fn(),
      retryJob: vi.fn(),
      cancelJob: vi.fn(),
      resummarizeJob: vi.fn(),
      proofreadJob: vi.fn(),
      retranscribeJob: vi.fn(),
      deleteJob: vi.fn(),
    },
  };
});

const settings: AppSettings = {
  transcribe_base_url: "",
  transcribe_api_key: "",
  transcribe_model: "",
  summarize_base_url: "",
  summarize_api_key: "",
  summarize_model: "",
  capture_seconds: "0",
  summarize_concurrency: 3,
  transcribe_threads: 4,
  transcribe_fast: false,
  cpu_count: 10,
  ai_proofread: false,
  show_transcript: true,
};

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    title: "测试任务",
    author: "",
    source_url: "https://www.bilibili.com/video/BV1xx",
    source_type: "page",
    site_id: null,
    auth_profile_id: null,
    media_url: "",
    media_url_override: "",
    status: "running",
    stage: "resolving",
    progress: 8,
    error: "",
    transcript: [],
    summary: null,
    timing: {},
    started_at: "2026-09-02T06:00:00Z",
    source_created_at: null,
    created_at: "2026-09-02T06:00:00Z",
    updated_at: "2026-09-02T06:00:00Z",
    ...overrides,
  };
}

let root: HTMLElement | undefined;
let app: ReturnType<typeof createApp> | undefined;
let lastRouter: ReturnType<typeof createRouter> | undefined;

async function flush() {
  for (let i = 0; i < 8; i++) await Promise.resolve();
  await nextTick();
}

async function mountDetail(path = "/jobs/job-1") {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: { template: "<div />" } },
      { path: "/knowledge", component: { template: "<div />" } },
      { path: "/settings", component: { template: "<div />" } },
      { path: "/jobs/:id", component: JobDetailView },
    ],
  });
  lastRouter = router;
  await router.push(path);
  await router.isReady();
  root = document.createElement("div");
  document.body.appendChild(root);
  app = createApp(JobDetailView);
  app.use(router);
  app.mount(root);
  await flush();
  return root;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(api.settings).mockResolvedValue(settings);
  vi.mocked(api.jobMedia).mockResolvedValue({
    url: "",
    refreshed: false,
    message: "",
  });
});

afterEach(() => {
  app?.unmount();
  root?.remove();
  app = undefined;
  root = undefined;
  lastRouter = undefined;
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("任务详情播放器", () => {
  it("解析出媒体地址后立刻显示播放区域，无需刷新", async () => {
    vi.mocked(api.job)
      .mockResolvedValueOnce(makeJob())
      .mockResolvedValueOnce(
        makeJob({
          media_url: "https://cdn.example.com/play.mp4",
          stage: "extracting",
          progress: 25,
        })
      );

    const el = await mountDetail();
    expect(el.querySelector("video.player")).toBeNull();

    await vi.advanceTimersByTimeAsync(2000);
    await flush();

    const video = el.querySelector("video.player");
    expect(video).not.toBeNull();
  });

  it("B站解析出媒体后，转写总结进行中也显示播放器", async () => {
    vi.mocked(api.job).mockResolvedValue(
      makeJob({
        status: "running",
        stage: "extracting",
        progress: 25,
        source_type: "http_audio",
        media_url: "https://bilivideo.com/a.m4s?deadline=1",
      })
    );

    const el = await mountDetail();
    const video = el.querySelector("video.player") as HTMLVideoElement | null;
    expect(video).not.toBeNull();
    expect(video?.getAttribute("src") || video?.src || "").toContain(
      "/api/jobs/job-1/play"
    );
    expect(api.jobMedia).not.toHaveBeenCalled();
  });

  it("打开详情时若已有媒体地址则直接显示播放器", async () => {
    vi.mocked(api.job).mockResolvedValue(
      makeJob({
        media_url: "https://cdn.example.com/play.mp4",
        stage: "extracting",
        progress: 25,
      })
    );

    const el = await mountDetail();
    expect(el.querySelector("video.player")).not.toBeNull();
  });

  it("B站音轨地址不会直接塞进播放器，改用本机播放接口", async () => {
    vi.mocked(api.job).mockResolvedValue(
      makeJob({
        status: "done",
        stage: "done",
        progress: 100,
        source_type: "http_audio",
        media_url: "https://bilivideo.com/a.m4s?deadline=1",
      })
    );
    vi.mocked(api.jobMedia).mockResolvedValue({
      url: "/api/jobs/job-1/play",
      refreshed: true,
      message: "",
    });

    const el = await mountDetail();
    const video = el.querySelector("video.player") as HTMLVideoElement | null;
    expect(video).not.toBeNull();
    expect(video?.getAttribute("src") || video?.src || "").toContain(
      "/api/jobs/job-1/play"
    );
  });

  it("刷新播放地址接口返回的报错走 toast，不占用播放提示", async () => {
    vi.mocked(api.job).mockResolvedValue(
      makeJob({
        status: "done",
        stage: "done",
        progress: 100,
        source_type: "http_audio",
        media_url: "https://bilivideo.com/a.m4s?deadline=1",
      })
    );
    vi.mocked(api.jobMedia).mockResolvedValue({
      url: "/api/jobs/job-1/play",
      refreshed: false,
      message: "B站请求失败：Illegal header value",
    });

    const el = await mountDetail();
    expect(toast.error).toHaveBeenCalledWith(
      "B站请求失败：Illegal header value"
    );
    expect(el.textContent).not.toContain("Illegal header value");
    expect(el.textContent).toContain("首次播放会在本机转封装");
  });

  it("刷新播放地址请求失败时同样用 toast 提示", async () => {
    vi.mocked(api.job).mockResolvedValue(
      makeJob({
        status: "done",
        stage: "done",
        progress: 100,
        media_url: "https://cdn.example.com/play.mp4",
      })
    );
    vi.mocked(api.jobMedia).mockRejectedValue(new Error("502 Bad Gateway"));

    const el = await mountDetail();
    expect(toast.error).toHaveBeenCalledWith("502 Bad Gateway");
    expect(el.textContent).not.toContain("502 Bad Gateway");
  });

  it("显示原片创建时间", async () => {
    vi.mocked(api.job).mockResolvedValue(
      makeJob({
        status: "done",
        stage: "done",
        progress: 100,
        source_created_at: "2026-08-13T04:00:00Z",
        created_at: "2026-09-02T06:00:00Z",
      })
    );
    const el = await mountDetail();
    const sub = el.querySelector(".sub")?.textContent || "";
    expect(sub).toContain(`${formatDateTime("2026-08-13T04:00:00Z")}`);
    expect(sub).toContain("https://www.bilibili.com/video/BV1xx");
  });

  it("在地址前展示作者并用间隔符隔开", async () => {
    vi.mocked(api.job).mockResolvedValue(
      makeJob({
        status: "done",
        stage: "done",
        progress: 100,
        author: "加菲财经",
        source_created_at: "2026-08-13T04:00:00Z",
      })
    );
    const el = await mountDetail();
    expect(el.querySelector(".sub")?.textContent?.trim()).toBe(
      `${formatDateTime("2026-08-13T04:00:00Z")} · 加菲财经 · https://www.bilibili.com/video/BV1xx`
    );
  });
});

describe("回到顶部", () => {
  it("滚动后显示按钮，点击后滚回顶部", async () => {
    vi.mocked(api.job).mockResolvedValue(
      makeJob({
        status: "done",
        stage: "done",
        progress: 100,
        media_url: "https://cdn.example.com/play.mp4",
      })
    );
    const scrollTo = vi.fn();
    window.scrollTo = scrollTo as unknown as typeof window.scrollTo;
    document.documentElement.scrollTop = 0;

    await mountDetail();
    expect(document.querySelector(".back-to-top")).toBeNull();

    document.documentElement.scrollTop = 400;
    window.dispatchEvent(new Event("scroll"));
    await flush();

    const btn = document.querySelector(".back-to-top");
    expect(btn).not.toBeNull();
    expect(btn?.getAttribute("aria-label")).toBe("回到顶部");
    (btn as HTMLButtonElement).click();
    expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: "smooth" });
  });

  it("文档任务不显示播放器，正文可定位", async () => {
    vi.mocked(api.job).mockResolvedValue(
      makeJob({
        status: "done",
        stage: "done",
        progress: 100,
        source_type: "local_document",
        source_url: "/downloads/job-1/source.txt",
        media_url: "",
        transcript: [
          {
            id: 0,
            start: 0,
            end: 0,
            text: "文档第一段",
            locator: "第1段",
          },
        ],
      })
    );
    const el = await mountDetail();
    expect(el.querySelector("video.player")).toBeNull();
    expect(el.textContent).toContain("正文");
    expect(el.textContent).toContain("第1段");
    expect(el.textContent).toContain("本地文档");
    expect(el.textContent).toContain("生成总结");
    expect(el.textContent).toContain("重新提取");
    expect(el.textContent).not.toContain("重新校对转写");
    const preview = el.querySelector(
      "iframe.doc-preview"
    ) as HTMLIFrameElement | null;
    expect(preview).not.toBeNull();
    expect(preview?.getAttribute("src") || preview?.src || "").toContain(
      "/api/jobs/job-1/file"
    );
    expect(el.textContent).toContain("原件预览");
    expect(el.textContent).not.toContain("/downloads/job-1/source.txt");
  });

  it("文档章节点击滚到预览窗口", async () => {
    const scrollIntoView = vi.fn();
    HTMLElement.prototype.scrollIntoView = scrollIntoView;
    vi.mocked(api.job).mockResolvedValue(
      makeJob({
        status: "done",
        stage: "done",
        progress: 100,
        source_type: "local_document",
        media_url: "",
        transcript: [
          {
            id: 0,
            start: 0,
            end: 0,
            text: "文档第一段",
            locator: "第1段",
          },
        ],
        summary: {
          title: "笔记",
          overview: "概述",
          chapters: [
            {
              title: "开篇",
              start_segment: 0,
              end_segment: 0,
              start: 0,
              end: 0,
              locator: "第1段",
              bullets: ["要点"],
            },
          ],
          key_points: [],
        },
      })
    );
    const el = await mountDetail();
    const btn = [...el.querySelectorAll("button")].find((item) =>
      item.textContent?.includes("第1段")
    );
    expect(btn).toBeTruthy();
    (btn as HTMLButtonElement).click();
    await flush();
    expect(el.querySelector("#doc-preview")).not.toBeNull();
    expect(scrollIntoView).toHaveBeenCalled();
  });

  it("PDF 章节点击把预览跳到对应页", async () => {
    vi.mocked(api.job).mockResolvedValue(
      makeJob({
        status: "done",
        stage: "done",
        progress: 100,
        source_type: "local_document",
        source_url: "/tmp/report.pdf",
        media_url: "/tmp/report.pdf",
        transcript: [
          {
            id: 0,
            start: 0,
            end: 0,
            text: "第二页正文",
            locator: "第2页",
          },
        ],
        summary: {
          title: "研报",
          overview: "概述",
          chapters: [
            {
              title: "第二页",
              start_segment: 0,
              end_segment: 0,
              start: 0,
              end: 0,
              locator: "第2页",
              bullets: ["要点"],
            },
          ],
          key_points: [],
        },
      })
    );
    const el = await mountDetail();
    const btn = [...el.querySelectorAll("button")].find((item) =>
      item.textContent?.includes("第2页")
    );
    expect(btn).toBeTruthy();
    (btn as HTMLButtonElement).click();
    await flush();
    const preview = el.querySelector(
      "iframe.doc-preview"
    ) as HTMLIFrameElement | null;
    expect(preview?.getAttribute("src") || preview?.src || "").toContain(
      "#page=2"
    );
    expect(el.textContent).not.toContain("/tmp/report.pdf");
  });
});

describe("综述章节与片子时钟", () => {
  it("结构化综述后不重复展示分段章节，点击片子时钟跳转", async () => {
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.mocked(api.job).mockResolvedValue(
      makeJob({
        status: "done",
        stage: "done",
        progress: 100,
        media_url: "https://cdn.example.com/play.mp4",
        summary: {
          title: "复盘",
          overview: [
            "## 论证结构",
            "### 一、市场节奏（约 00:15:39–00:23:07）",
            "这一节讲低吸纪律。",
          ].join("\n"),
          chapters: [
            {
              title: "分段章节标题不应出现",
              start_segment: 0,
              end_segment: 0,
              start: 15,
              end: 40,
              bullets: ["分段章节要点不应出现"],
            },
          ],
          key_points: [
            {
              text: "关键一句",
              start_segment: 0,
              end_segment: 0,
              start: 20,
              end: 21,
            },
          ],
        },
      })
    );
    const el = await mountDetail();
    expect(el.textContent).toContain("市场节奏");
    expect(el.textContent).toContain("关键一句");
    expect(el.textContent).not.toContain("分段章节标题不应出现");
    expect(el.textContent).not.toContain("分段章节要点不应出现");
    const clock = el.querySelector(
      ".overview [data-seek]"
    ) as HTMLButtonElement | null;
    expect(clock).not.toBeNull();
    expect(clock?.getAttribute("data-seek")).toBe("939");
    expect(clock?.textContent).toBe("00:15:39");
    clock?.click();
    await flush();
    const video = el.querySelector("video.player") as HTMLVideoElement | null;
    expect(video?.currentTime).toBe(939);
  });

  it("纯文本综述仍显示分段章节", async () => {
    vi.mocked(api.job).mockResolvedValue(
      makeJob({
        status: "done",
        stage: "done",
        progress: 100,
        media_url: "https://cdn.example.com/play.mp4",
        summary: {
          title: "复盘",
          overview: "这是一段旧的纯文本综述。",
          chapters: [
            {
              title: "开场分段",
              start_segment: 0,
              end_segment: 0,
              start: 12,
              end: 40,
              bullets: ["要点甲"],
            },
          ],
          key_points: [],
        },
      })
    );
    const el = await mountDetail();
    expect(el.textContent).toContain("开场分段");
    expect(el.textContent).toContain("要点甲");
  });
});

describe("媒体地址覆盖", () => {
  it("默认不显示，解析失败后展开并随重试提交", async () => {
    const failed = makeJob({
      status: "failed",
      stage: "failed",
      progress: 0,
      error: "无法解析媒体地址，请填写媒体地址覆盖后重试",
    });
    vi.mocked(api.job).mockResolvedValue(failed);
    vi.mocked(api.retryJob).mockResolvedValue(
      makeJob({ status: "pending", stage: "queued", error: "" })
    );
    const el = await mountDetail();
    expect(el.textContent).toContain("媒体地址覆盖");
    const input = el.querySelector(
      "input[placeholder='登录后从 Network 复制的流地址']"
    ) as HTMLInputElement;
    expect(input).toBeTruthy();
    input.value = "https://cdn.example.com/live.m3u8";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    const retry = [...el.querySelectorAll("button")].find(
      (item) => item.textContent?.trim() === "重试"
    ) as HTMLButtonElement;
    retry.click();
    await flush();
    expect(api.retryJob).toHaveBeenCalledWith("job-1", {
      media_url_override: "https://cdn.example.com/live.m3u8",
    });
  });

  it("成功任务不显示媒体地址覆盖", async () => {
    vi.mocked(api.job).mockResolvedValue(
      makeJob({ status: "done", stage: "done", progress: 100 })
    );
    const el = await mountDetail();
    expect(el.textContent).not.toContain("媒体地址覆盖");
  });

  it("定时汇总只显示综述和原任务跳转", async () => {
    vi.mocked(api.job).mockResolvedValue(
      makeJob({
        title: "2026-09-16 08:00 定时汇总",
        status: "done",
        stage: "done",
        progress: 100,
        source_type: "schedule_digest",
        source_url: "schedule://log-1",
        media_url: "",
        transcript: [],
        summary: {
          title: "两场纪律汇总",
          overview:
            "## 一句话总结\n**先看分时再挂单。**\n\n## 主题与核心观点\n| 维度 | 内容 |\n|---|---|\n| 主题 | 纪律 |\n| 核心观点 | 走弱才卖 |\n| 手段 | 分时 |\n\n## 论证结构\n### 一、卖票\n走弱才卖（作者甲）。\n\n## 辨立场\n纪律可操作，信息只来自讲者。",
          chapters: [],
          key_points: [],
        },
        related_jobs: [
          {
            id: "src-1",
            title: "卖票课",
            author: "作者甲",
            status: "done",
          },
        ],
      })
    );
    const el = await mountDetail("/jobs/job-1?from=schedule");
    expect(el.querySelector("video.player")).toBeNull();
    expect(el.textContent).toContain("定时汇总");
    expect(el.textContent).toContain("原任务");
    expect(el.textContent).toContain("卖票课");
    expect(el.textContent).toContain("作者甲");
    expect(el.textContent).toContain("两场纪律汇总");
    expect(el.textContent).toContain("重新总结");
    expect(el.textContent).not.toContain("重新转写");
    expect(el.textContent).not.toContain("重新校对转写");
    expect(el.textContent).not.toContain("从头重试");
    const sourceLink = el.querySelector('a[href="/jobs/src-1?from=schedule"]');
    expect(sourceLink?.textContent).toContain("卖票课");
    expect(el.querySelector(".chapter-block")).toBeNull();
    expect(el.querySelector('a[aria-label="返回定时任务"]')).not.toBeNull();
  });
});

describe("详情返回入口", () => {
  it("默认返回任务列表", async () => {
    vi.mocked(api.job).mockResolvedValue(
      makeJob({ status: "done", stage: "done", progress: 100 })
    );
    const el = await mountDetail();
    const back = el.querySelector('a[aria-label="返回任务列表"]');
    expect(back?.getAttribute("href")).toBe("/");
  });

  it("从定时任务进入时返回定时任务", async () => {
    vi.mocked(api.job).mockResolvedValue(
      makeJob({ status: "done", stage: "done", progress: 100 })
    );
    const el = await mountDetail("/jobs/job-1?from=schedule");
    const back = el.querySelector('a[aria-label="返回定时任务"]');
    expect(back).not.toBeNull();
    expect(back?.getAttribute("href")).toBe("/settings?tab=schedule");
  });

  it("任务不存在时提示并在 3 秒后返回来源页", async () => {
    vi.mocked(api.job).mockRejectedValue(
      new Error(JSON.stringify({ detail: "任务不存在" }))
    );
    await mountDetail("/jobs/gone?from=schedule");
    expect(toast.error).toHaveBeenCalledWith("任务不存在");
    expect(lastRouter?.currentRoute.value.path).toBe("/jobs/gone");
    await vi.advanceTimersByTimeAsync(3000);
    await flush();
    expect(lastRouter?.currentRoute.value.fullPath).toBe(
      "/settings?tab=schedule"
    );
  });
});
