import { createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { toast } from "vue-sonner";
import { version as appVersion } from "../../package.json";
import { api, type AppSettings, type PluginInfo } from "../api";
import { emptyDomainPack } from "../utils/domain";
import SettingsView from "./SettingsView.vue";

vi.mock("vue-sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}));

vi.mock("../api", () => ({
  api: {
    settings: vi.fn(),
    saveSettings: vi.fn(),
    saveDomainPack: vi.fn(),
    addDomainPreset: vi.fn(),
    deleteDomainPreset: vi.fn(),
    lexicon: vi.fn(),
    saveLexicon: vi.fn(),
    resetLexicon: vi.fn(),
    schedule: vi.fn(),
    saveSchedule: vi.fn(),
    runSchedule: vi.fn(),
    scheduleLogs: vi.fn(),
    clearScheduleLogs: vi.fn(),
    plugins: vi.fn(),
    installPlugin: vi.fn(),
    cancelPlugin: vi.fn(),
    uninstallPlugin: vi.fn(),
  },
}));

const sampleSchedule = {
  enabled: false,
  time: "08:00",
  since: "2026-08-01",
  max_jobs: 5,
  domain_id: "a-share",
  digest_enabled: true,
  sites: [
    {
      site_id: "xiaoe-1",
      name: "小鹅通",
      adapter: "xiaoe",
      enabled: false,
      catalog_id: "",
      catalog_hint: "店铺 app_id，或店铺 H5 地址",
    },
    {
      site_id: "yueniu-1",
      name: "加菲财经/约牛",
      adapter: "yueniu",
      enabled: false,
      catalog_id: "",
      catalog_hint: "可空；填写则按作者 authorId 过滤",
    },
  ],
};

const samplePlugins: PluginInfo[] = [
  {
    id: "ocr",
    title: "扫描件 OCR",
    description: "识别扫描 PDF",
    size_hint: "约 100MB",
    status: "missing",
    error: "",
    soffice: "",
  },
  {
    id: "legacy-doc",
    title: "旧版 Word",
    description: "转换 .doc",
    size_hint: "约 30MB",
    status: "ready",
    error: "",
    soffice: "/usr/bin/soffice",
  },
];

const localSettings: AppSettings = {
  transcribe_base_url: "",
  transcribe_api_key: "",
  transcribe_model: "sensevoice-small-q8",
  summarize_base_url: "https://api.deepseek.com/v1",
  summarize_api_key: "",
  summarize_model: "deepseek-v4-flash",
  capture_seconds: "180",
  summarize_concurrency: 3,
  transcribe_threads: 4,
  transcribe_fast: false,
  cpu_count: 10,
  ai_proofread: true,
  show_transcript: true,
};

let root: HTMLElement | undefined;
let app: ReturnType<typeof createApp> | undefined;

async function flush() {
  for (let i = 0; i < 8; i++) await Promise.resolve();
  await nextTick();
}

async function mountSettings(
  settings: AppSettings,
  logs: Array<{
    id: string;
    started_at: string;
    finished_at: string | null;
    trigger: string;
    status: string;
    summary: string;
    detail: unknown[];
    digest_job_id?: string;
  }> = [],
  plugins: PluginInfo[] = samplePlugins,
  path = "/settings"
) {
  vi.mocked(api.settings).mockResolvedValue(settings);
  vi.mocked(api.lexicon).mockResolvedValue({
    terms: [],
    fixes: [],
    customized: false,
  });
  vi.mocked(api.schedule).mockResolvedValue(sampleSchedule);
  vi.mocked(api.scheduleLogs).mockResolvedValue(logs);
  vi.mocked(api.plugins).mockResolvedValue(plugins);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/settings", component: SettingsView },
      { path: "/jobs/:id", component: { template: "<div>job</div>" } },
      {
        path: "/settings/changelog",
        component: { template: "<div>changelog</div>" },
      },
    ],
  });
  await router.push(path);
  await router.isReady();
  root = document.createElement("div");
  document.body.appendChild(root);
  app = createApp(SettingsView);
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
  vi.mocked(toast.success).mockClear();
  vi.mocked(toast.error).mockClear();
});

function clickSettingsTab(el: HTMLElement, label: string) {
  const tab = [...el.querySelectorAll('[role="tab"]')].find((item) =>
    item.textContent?.includes(label)
  ) as HTMLButtonElement | undefined;
  expect(tab).toBeTruthy();
  tab?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
}

describe("设置页模型限制说明", () => {
  it("用 tab 切换各设置区块", async () => {
    const el = await mountSettings(localSettings);
    const tabs = [...el.querySelectorAll('[role="tab"]')].map(
      (item) => item.textContent?.trim() || ""
    );
    expect(tabs).toEqual([
      "转写与总结",
      "内容领域",
      "定时任务",
      "插件",
      "外观",
      "关于",
    ]);
    const appearance = el.querySelector(
      "#settings-panel-appearance"
    ) as HTMLElement;
    const models = el.querySelector("#settings-panel-models") as HTMLElement;
    expect(models.style.display).not.toBe("none");
    expect(appearance.style.display).toBe("none");
    clickSettingsTab(el, "外观");
    await flush();
    expect(models.style.display).toBe("none");
    expect(appearance.style.display).not.toBe("none");
    expect(
      el
        .querySelector("#settings-tab-appearance")
        ?.getAttribute("aria-selected")
    ).toBe("true");
  });

  it("本地转写时展示协议限制和本机说明", async () => {
    const el = await mountSettings(localSettings);
    expect(el.textContent).toContain("内容领域");
    expect(el.textContent).toContain("当前 0 个正确词");
    expect(el.textContent).toContain("仍是该领域的默认词表");
    const notes = [...el.querySelectorAll(".info-tip-text")]
      .map((item) => item.textContent || "")
      .join("\n");
    expect(el.querySelectorAll(".note").length).toBe(0);
    expect(el.querySelector(".section-title .info-tip")).toBeTruthy();
    expect(notes).toContain("/v1/audio/transcriptions");
    expect(notes).toContain("聊天模型不能用来转写");
    expect(notes).toContain("Chat Completions");
    expect(notes).toContain("原生接口不支持");
    expect(el.textContent).toContain("分段并发数");
    expect(el.textContent).toContain("默认 3 路");
    expect(el.textContent).toContain("转写线程");
    expect(el.textContent).toContain("快速转写");
    expect(el.textContent).not.toContain("不要填 tiny / small / large");
    expect(el.textContent).toContain("展开领域规则");
    expect(el.textContent).toContain("保存领域");
    expect(el.querySelector('[aria-label="添加预设"]')).toBeTruthy();
    expect(el.querySelector('[aria-label="删除当前预设"]')).toBeTruthy();
    expect(el.textContent).toContain("转写词汇表");
    const details = el.querySelector(".domain-details") as HTMLElement | null;
    expect(details).toBeTruthy();
    expect(details?.style.display).toBe("none");
  });

  it("自定义转写时展示音频接口填写限制", async () => {
    const el = await mountSettings({
      ...localSettings,
      transcribe_model: "whisper-1",
      transcribe_base_url: "https://api.openai.com/v1",
      transcribe_api_key: "sk-test",
    });
    expect(el.textContent).toContain("三项都要填");
    expect(el.textContent).toContain("会退回默认的本机 SenseVoice");
    expect(el.textContent).toContain("不要填 tiny / small / large");
    expect(el.textContent).not.toContain("本地转写不使用 Base URL 和 API Key");
  });

  it("保存领域只提交当前领域包", async () => {
    const pack = emptyDomainPack();
    const el = await mountSettings({
      ...localSettings,
      domain_pack: pack,
    });
    vi.mocked(api.saveDomainPack).mockResolvedValue({
      ...localSettings,
      domain_pack: pack,
    });
    const button = [...el.querySelectorAll("button")].find((item) =>
      item.textContent?.includes("保存领域")
    );
    expect(button).toBeTruthy();
    button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    expect(api.saveDomainPack).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.saveDomainPack).mock.calls[0][0].id).toBe("a-share");
    expect(api.saveSettings).not.toHaveBeenCalled();
    expect(api.saveLexicon).not.toHaveBeenCalled();
    expect(el.textContent).not.toContain("领域已保存");
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining("领域已保存")
    );
  });

  it("设置页末尾展示关于区块", async () => {
    const el = await mountSettings(localSettings);
    const cards = [...el.querySelectorAll("section.card")];
    const about = cards.at(-1);
    expect(about?.textContent).toContain("关于");
    expect(about?.textContent).toContain("版本");
    expect(about?.textContent).toContain(appVersion);
    expect(about?.textContent).toContain("免责声明");
    expect(about?.textContent).toContain(
      "若内容来自付费渠道，仅供个人使用，切勿用于商业用途"
    );
    expect(about?.textContent).toContain("更新日志");
    const changelog = about?.querySelector('a[href="/settings/changelog"]');
    expect(changelog?.textContent).toContain("查看本版本更新");
  });

  it("从更新日志返回时停留在关于 tab", async () => {
    const el = await mountSettings(
      localSettings,
      [],
      samplePlugins,
      "/settings?tab=about"
    );
    const about = el.querySelector("#settings-panel-about") as HTMLElement;
    const models = el.querySelector("#settings-panel-models") as HTMLElement;
    expect(about.style.display).not.toBe("none");
    expect(models.style.display).toBe("none");
    expect(
      el.querySelector("#settings-tab-about")?.getAttribute("aria-selected")
    ).toBe("true");
  });

  it("展示定时任务站点与日志区", async () => {
    const el = await mountSettings(localSettings, [
      {
        id: "log-1",
        started_at: "2026-09-10T01:00:00Z",
        finished_at: "2026-09-10T01:00:02Z",
        trigger: "manual",
        status: "ok",
        summary: "小鹅通：新建 1，跳过 2",
        detail: [],
        digest_job_id: "digest-1",
      },
    ]);
    expect(el.textContent).toContain("定时任务");
    expect(el.textContent).toContain("生成汇总总结");
    expect(el.textContent).toContain("查看汇总");
    expect(
      el.querySelector(".schedule-digest-link")?.getAttribute("href")
    ).toBe("/jobs/digest-1?from=schedule");
    expect(el.textContent).toContain("小鹅通");
    expect(el.textContent).toContain("从哪天开始");
    expect(el.textContent).toContain("立即执行");
    expect(el.textContent).toContain("当天发布");
    expect(el.textContent).toContain("多个 UP");
    expect(el.textContent).toContain("小鹅通：新建 1，跳过 2");
    const saveBtn = [...el.querySelectorAll("button")].find((item) =>
      item.textContent?.includes("保存定时")
    );
    expect(saveBtn).toBeTruthy();
    vi.mocked(api.saveSchedule).mockResolvedValue({
      ...sampleSchedule,
      enabled: true,
    });
    saveBtn?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    expect(api.saveSchedule).toHaveBeenCalledTimes(1);
    const clearBtn = [...el.querySelectorAll("button")].find((item) =>
      item.textContent?.includes("清除日志")
    );
    expect(clearBtn).toBeTruthy();
    expect((clearBtn as HTMLButtonElement).disabled).toBe(false);
    expect(el.querySelector(".schedule-log-list")).toBeTruthy();
    vi.mocked(api.clearScheduleLogs).mockResolvedValue({ ok: true });
    clearBtn?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    expect(document.body.textContent).toContain("确定清除全部定时运行记录");
    const confirm = [...document.body.querySelectorAll("button")].find(
      (item) => item.textContent === "确认清除"
    );
    confirm?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    expect(api.clearScheduleLogs).toHaveBeenCalledTimes(1);
  });

  it("立即执行时立刻展示扫描中，完成后写入日志", async () => {
    let finishRun:
      | ((value: {
          id: string;
          started_at: string;
          finished_at: string | null;
          trigger: string;
          status: string;
          summary: string;
          detail: unknown[];
        }) => void)
      | undefined;
    vi.mocked(api.runSchedule).mockImplementation(
      () =>
        new Promise((resolve) => {
          finishRun = resolve;
        })
    );
    const el = await mountSettings(localSettings);
    const runBtn = [...el.querySelectorAll("button")].find(
      (item) =>
        !item.classList.contains("info-tip") &&
        item.textContent?.includes("立即执行")
    ) as HTMLButtonElement | undefined;
    expect(runBtn).toBeTruthy();
    runBtn?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    expect(runBtn?.disabled).toBe(true);
    expect(runBtn?.textContent).toContain("正在扫描");
    expect(runBtn?.getAttribute("aria-busy")).toBe("true");
    expect(el.textContent).toContain("正在扫描站点");
    expect(el.textContent).toContain("进行中");
    finishRun?.({
      id: "log-run",
      started_at: "2026-09-11T09:41:00Z",
      finished_at: "2026-09-11T09:41:08Z",
      trigger: "manual",
      status: "partial",
      summary: "B站：跳过 1，请求过于频繁，请稍后再试",
      detail: [],
      digest_job_id: "",
    });
    await flush();
    expect(el.textContent).toContain("请求过于频繁");
    expect(el.textContent).toContain("部分成功");
    expect(toast.error).not.toHaveBeenCalled();
    expect(runBtn?.disabled).toBe(false);
    expect(runBtn?.textContent).toContain("立即执行");
  });

  it("立即执行不会把上一轮日志当成这一轮结果", async () => {
    const oldLog = {
      id: "log-old",
      started_at: "2026-09-10T01:00:00Z",
      finished_at: "2026-09-10T01:00:02Z",
      trigger: "manual",
      status: "ok",
      summary: "小鹅通：新建 1，跳过 2",
      detail: [],
      digest_job_id: "",
    };
    const newLog = {
      id: "log-new",
      started_at: "2026-09-16T10:00:00Z",
      finished_at: "2026-09-16T10:00:08Z",
      trigger: "manual",
      status: "ok",
      summary: "B站：新建 2",
      detail: [],
      digest_job_id: "",
    };
    const el = await mountSettings(localSettings, [oldLog]);
    vi.mocked(api.runSchedule).mockResolvedValue(oldLog);
    vi.mocked(api.scheduleLogs).mockResolvedValue([newLog, oldLog]);
    const runBtn = [...el.querySelectorAll("button")].find(
      (item) =>
        !item.classList.contains("info-tip") &&
        item.textContent?.includes("立即执行")
    ) as HTMLButtonElement | undefined;
    runBtn?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    await flush();
    expect(el.textContent).toContain("B站：新建 2");
    expect(el.textContent).toContain("小鹅通：新建 1，跳过 2");
  });
});

describe("插件", () => {
  it("展示插件卡片和未安装状态", async () => {
    const el = await mountSettings(localSettings);
    expect(el.textContent).toContain("插件");
    expect(el.textContent).toContain("扫描件 OCR");
    expect(el.textContent).toContain("未安装");
    expect(el.querySelector(".plugin-grid")).toBeTruthy();
    expect(el.querySelectorAll(".plugin-card").length).toBe(2);
    expect(el.querySelectorAll(".plugin-card-actions").length).toBe(2);
  });

  it("已安装插件显示成功色标签", async () => {
    const el = await mountSettings(localSettings);
    expect(el.textContent).toContain("已安装");
    expect(el.textContent).not.toContain("已就绪");
    const badge = [...el.querySelectorAll(".plugin-card .tag")].find((item) =>
      item.textContent?.includes("已安装")
    );
    expect(badge).toBeTruthy();
    expect(badge?.classList.contains("ok")).toBe(true);
  });

  it("卸载插件先弹窗确认", async () => {
    const el = await mountSettings(localSettings);
    clickSettingsTab(el, "插件");
    await flush();
    const uninstallBtn = [...el.querySelectorAll("button")].find(
      (item) => item.textContent === "卸载" && !item.disabled
    );
    expect(uninstallBtn).toBeTruthy();
    uninstallBtn?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    expect(api.uninstallPlugin).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain("确定卸载「旧版 Word」");
    const cancel = [...document.body.querySelectorAll("button")].find(
      (item) => item.textContent === "取消"
    );
    cancel?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    expect(api.uninstallPlugin).not.toHaveBeenCalled();

    uninstallBtn?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    vi.mocked(api.uninstallPlugin).mockResolvedValue({
      ...samplePlugins[1],
      status: "missing",
      soffice: "",
    });
    const confirm = [...document.body.querySelectorAll("button")].find(
      (item) => item.textContent === "确认卸载"
    );
    confirm?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    expect(api.uninstallPlugin).toHaveBeenCalledWith("legacy-doc");
  });

  it("安装中只能取消，取消后变成未安装", async () => {
    vi.mocked(api.uninstallPlugin).mockClear();
    vi.mocked(api.cancelPlugin).mockClear();
    const installing: PluginInfo = {
      ...samplePlugins[0],
      status: "installing",
    };
    const el = await mountSettings(localSettings, [], [
      installing,
      samplePlugins[1],
    ]);
    clickSettingsTab(el, "插件");
    await flush();
    expect(el.textContent).toContain("安装中");
    const ocrCard = [...el.querySelectorAll(".plugin-card")].find((item) =>
      item.textContent?.includes("扫描件 OCR")
    );
    expect(ocrCard).toBeTruthy();
    expect(ocrCard?.textContent).toContain("取消");
    expect(
      [...(ocrCard?.querySelectorAll("button") || [])].some(
        (item) => item.textContent === "卸载" && !item.disabled
      )
    ).toBe(false);
    const cancelBtn = [...(ocrCard?.querySelectorAll("button") || [])].find(
      (item) => item.textContent === "取消"
    );
    vi.mocked(api.cancelPlugin).mockResolvedValue({
      ...installing,
      status: "missing",
    });
    vi.mocked(api.plugins).mockResolvedValue([
      { ...installing, status: "missing" },
      samplePlugins[1],
    ]);
    cancelBtn?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    expect(api.cancelPlugin).toHaveBeenCalledWith("ocr");
    expect(api.uninstallPlugin).not.toHaveBeenCalled();
    expect(ocrCard?.textContent).toContain("未安装");
    expect(ocrCard?.textContent).not.toContain("安装中");
  });
});
