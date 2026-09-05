import { createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type AppSettings, type Job } from "../api";
import { formatDateTime } from "../utils/time";
import JobDetailView from "./JobDetailView.vue";

vi.mock("../api", () => ({
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
}));

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

async function flush() {
  for (let i = 0; i < 8; i++) await Promise.resolve();
  await nextTick();
}

async function mountDetail() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: { template: "<div />" } },
      { path: "/jobs/:id", component: JobDetailView },
    ],
  });
  await router.push("/jobs/job-1");
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
});
