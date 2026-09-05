import { createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { toast } from "vue-sonner";
import { version as appVersion } from "../../package.json";
import { api, type AppSettings } from "../api";
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
  },
}));

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

async function mountSettings(settings: AppSettings) {
  vi.mocked(api.settings).mockResolvedValue(settings);
  vi.mocked(api.lexicon).mockResolvedValue({
    terms: [],
    fixes: [],
    customized: false,
  });
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/settings", component: SettingsView },
      {
        path: "/settings/changelog",
        component: { template: "<div>changelog</div>" },
      },
    ],
  });
  await router.push("/settings");
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

describe("设置页模型限制说明", () => {
  it("本地转写时展示协议限制和本机说明", async () => {
    const el = await mountSettings(localSettings);
    expect(el.textContent).toContain("内容领域");
    expect(el.textContent).toContain("A 股盘面课");
    expect(el.textContent).toContain("词表跟领域走");
    const notes = [...el.querySelectorAll(".note")]
      .map((item) => item.textContent || "")
      .join("\n");
    expect(notes).toContain("/v1/audio/transcriptions");
    expect(notes).toContain("聊天模型不能用来转写");
    expect(notes).toContain("Chat Completions");
    expect(notes).toContain("原生接口不支持");
    expect(el.textContent).toContain("分段并发数");
    expect(el.textContent).toContain("默认 3 路");
    expect(el.textContent).toContain("转写线程");
    expect(el.textContent).toContain("默认用 80%");
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
});
