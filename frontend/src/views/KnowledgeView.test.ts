import { createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type KnowledgeDoc } from "../api";
import KnowledgeView from "./KnowledgeView.vue";

vi.mock("../api", () => ({
  api: {
    settings: vi.fn(),
    knowledge: vi.fn(),
    knowledgeChat: vi.fn(),
  },
}));

function makeDoc(overrides: Partial<KnowledgeDoc> = {}): KnowledgeDoc {
  return {
    job_id: "job-1",
    title: "行情课",
    source_url: "",
    status: "done",
    segment_count: 2,
    updated_at: "2026-09-05T02:00:00Z",
    preview: "今天重点看贵州茅台",
    ...overrides,
  };
}

let root: HTMLElement | undefined;
let app: ReturnType<typeof createApp> | undefined;

async function flush() {
  for (let i = 0; i < 8; i++) await Promise.resolve();
  await nextTick();
}

async function mountKnowledge(
  documents: KnowledgeDoc[] = [makeDoc()],
  total = documents.length
) {
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
  vi.mocked(api.knowledge).mockResolvedValue({
    query: "",
    job_count: total,
    hit_count: 0,
    documents,
    hits: [],
    page: 1,
    page_size: 10,
  });
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/knowledge", component: KnowledgeView },
      { path: "/jobs/:id", component: { template: "<div />" } },
    ],
  });
  await router.push("/knowledge");
  await router.isReady();
  root = document.createElement("div");
  document.body.appendChild(root);
  app = createApp(KnowledgeView);
  app.use(router);
  app.mount(root);
  await flush();
  return root;
}

function clickNamed(el: HTMLElement, name: string) {
  const btn = [...el.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === name
  ) as HTMLButtonElement;
  btn.click();
}

afterEach(() => {
  app?.unmount();
  root?.remove();
  root = undefined;
  app = undefined;
});

beforeEach(() => {
  vi.mocked(api.settings).mockReset();
  vi.mocked(api.knowledge).mockReset();
});

describe("知识库任务列表分页", () => {
  it("按页请求任务并翻到下一页", async () => {
    const firstPage = Array.from({ length: 10 }, (_, index) =>
      makeDoc({ job_id: `job-${index}`, title: `课${index}` })
    );
    const el = await mountKnowledge(firstPage, 12);
    expect(api.knowledge).toHaveBeenCalledWith("", "a-share", 1, 10);
    expect(el.textContent).toContain("当前领域已收录 12 个任务");
    expect(el.querySelector(".pager")?.textContent).toContain("第 1 / 2 页");
    expect(el.textContent).toContain("课0");
    expect(el.textContent).not.toContain("课10");

    vi.mocked(api.knowledge).mockResolvedValue({
      query: "",
      job_count: 12,
      hit_count: 0,
      documents: [
        makeDoc({ job_id: "job-10", title: "课10" }),
        makeDoc({ job_id: "job-11", title: "课11" }),
      ],
      hits: [],
      page: 2,
      page_size: 10,
    });
    clickNamed(el, "下一页");
    await flush();
    expect(api.knowledge).toHaveBeenCalledWith("", "a-share", 2, 10);
    expect(el.textContent).toContain("课10");
    expect(el.querySelector(".pager")?.textContent).toContain("第 2 / 2 页");
  });

  it("任务不超过一页时不显示翻页按钮", async () => {
    const el = await mountKnowledge([makeDoc()], 1);
    expect(el.textContent).toContain("当前领域已收录 1 个任务");
    expect(el.querySelector(".pager")?.textContent).toContain("共 1 条");
    expect(el.querySelector(".pager")?.textContent).not.toContain("下一页");
  });
});
