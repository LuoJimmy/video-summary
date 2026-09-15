import { createApp, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  api,
  type KnowledgeConversationSummary,
  type KnowledgeDoc,
} from "../api";
import KnowledgeView from "./KnowledgeView.vue";

vi.mock("../api", () => ({
  api: {
    settings: vi.fn(),
    knowledge: vi.fn(),
    knowledgeChat: vi.fn(),
    knowledgeConversations: vi.fn(),
    knowledgeConversation: vi.fn(),
    renameKnowledgeConversation: vi.fn(),
    deleteKnowledgeConversation: vi.fn(),
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

function makeConversation(
  overrides: Partial<KnowledgeConversationSummary> = {}
): KnowledgeConversationSummary {
  return {
    id: "conv-1",
    domain_id: "a-share",
    title: "茅台怎么看",
    preview: "量能放大可以低吸",
    updated_at: "2026-09-11T02:00:00Z",
    created_at: "2026-09-11T02:00:00Z",
    message_count: 2,
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
  total = documents.length,
  conversations: KnowledgeConversationSummary[] = []
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
  vi.mocked(api.knowledgeConversations).mockResolvedValue({
    items: conversations,
    total: conversations.length,
    page: 1,
    page_size: 30,
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
  vi.mocked(api.knowledgeChat).mockReset();
  vi.mocked(api.knowledgeConversations).mockReset();
  vi.mocked(api.knowledgeConversation).mockReset();
  vi.mocked(api.renameKnowledgeConversation).mockReset();
  vi.mocked(api.deleteKnowledgeConversation).mockReset();
});

describe("知识库任务列表分页", () => {
  it("按页请求任务并翻到下一页", async () => {
    const firstPage = Array.from({ length: 10 }, (_, index) =>
      makeDoc({ job_id: `job-${index}`, title: `课${index}` })
    );
    const el = await mountKnowledge(firstPage, 12);
    expect(api.knowledge).toHaveBeenCalledWith("", "a-share", 1, 10);
    expect(el.textContent).toContain("当前领域已收录 12 个任务");
    expect(el.querySelector(".pager")?.textContent).toContain("共 12 条数据");
    expect(
      el.querySelector('.pager [aria-current="page"]')?.textContent?.trim()
    ).toBe("1");
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
    (el.querySelector('[aria-label="下一页"]') as HTMLButtonElement).click();
    await flush();
    expect(api.knowledge).toHaveBeenCalledWith("", "a-share", 2, 10);
    expect(el.textContent).toContain("课10");
    expect(
      el.querySelector('.pager [aria-current="page"]')?.textContent?.trim()
    ).toBe("2");
  });

  it("任务不超过一页时翻页按钮不可用", async () => {
    const el = await mountKnowledge([makeDoc()], 1);
    expect(el.textContent).toContain("当前领域已收录 1 个任务");
    expect(el.querySelector(".pager")?.textContent).toContain("共 1 条数据");
    expect(el.querySelectorAll(".pager-item")).toHaveLength(1);
    expect(
      (el.querySelector('[aria-label="上一页"]') as HTMLButtonElement).disabled
    ).toBe(true);
    expect(
      (el.querySelector('[aria-label="下一页"]') as HTMLButtonElement).disabled
    ).toBe(true);
  });

  it("文档引用显示 locator 并链到段落", async () => {
    const el = await mountKnowledge();
    vi.mocked(api.knowledgeChat).mockResolvedValue({
      answer: "利率下行对估值有支撑",
      conversation_id: "conv-1",
      title: "利率",
      citations: [
        {
          job_id: "job-1",
          title: "研报",
          kind: "transcript",
          kind_label: "转写",
          text: "利率下行对估值有支撑",
          snippet: "利率下行对估值有支撑",
          start: 0,
          end: 0,
          segment_id: 0,
          locator: "第3页",
        },
      ],
    });
    const input = el.querySelector("textarea") as HTMLTextAreaElement;
    input.value = "利率";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    clickNamed(el, "发送");
    await flush();
    expect(el.textContent).toContain("第3页");
    expect(el.textContent).not.toContain("00:00");
    const link = el.querySelector(".cite-link") as HTMLAnchorElement | null;
    expect(link?.getAttribute("href")).toContain("/jobs/job-1");
    expect(link?.getAttribute("href")).toContain("seg=0");
    expect(link?.getAttribute("href")).toContain("from=knowledge");
  });

  it("任务标题链到对应详情并带回知识库来源", async () => {
    const el = await mountKnowledge();
    const link = [...el.querySelectorAll("a")].find((item) =>
      item.textContent?.includes("行情课")
    );
    expect(link?.getAttribute("href")).toBe("/jobs/job-1?from=knowledge");
  });
});

describe("知识库问答历史", () => {
  it("列出历史并打开后恢复对话", async () => {
    const conv = makeConversation();
    const el = await mountKnowledge([makeDoc()], 1, [conv]);
    expect(api.knowledgeConversations).toHaveBeenCalledWith(
      "",
      "a-share",
      1,
      30
    );
    expect(el.querySelector(".chat-title")?.textContent).toBe("新对话");
    expect(el.querySelector('button[aria-label="新对话"]')).toBeNull();
    expect(el.textContent).toContain("茅台怎么看");
    expect(el.querySelector(".kb-history-item")?.textContent).not.toContain(
      "2026-09-11"
    );
    vi.mocked(api.knowledgeConversation).mockResolvedValue({
      ...conv,
      messages: [
        { role: "user", content: "茅台怎么看" },
        { role: "assistant", content: "量能放大可以低吸", citations: [] },
      ],
    });
    (el.querySelector(".kb-history-open") as HTMLButtonElement).click();
    await flush();
    expect(api.knowledgeConversation).toHaveBeenCalledWith("conv-1");
    expect(el.textContent).toContain("量能放大可以低吸");
    expect(el.querySelector(".chat-title")?.textContent).toBe("茅台怎么看");
    expect(el.querySelector('button[aria-label="新对话"]')).not.toBeNull();
    expect(
      el.querySelector(".kb-history-item")?.classList.contains("active")
    ).toBe(true);
  });

  it("按关键词搜索历史记录", async () => {
    const el = await mountKnowledge();
    vi.mocked(api.knowledgeConversations).mockClear();
    const search = el.querySelector(
      'input[aria-label="搜索历史记录"]'
    ) as HTMLInputElement;
    search.value = "茅台";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 300));
    await flush();
    expect(api.knowledgeConversations).toHaveBeenCalledWith(
      "茅台",
      "a-share",
      1,
      30
    );
  });

  it("删除历史记录并在删除当前对话后回到空白", async () => {
    const conv = makeConversation();
    const el = await mountKnowledge([makeDoc()], 1, [conv]);
    vi.mocked(api.knowledgeConversation).mockResolvedValue({
      ...conv,
      messages: [
        { role: "user", content: "茅台怎么看" },
        { role: "assistant", content: "量能放大可以低吸", citations: [] },
      ],
    });
    (el.querySelector(".kb-history-open") as HTMLButtonElement).click();
    await flush();
    (el.querySelector('[aria-label="更多操作"]') as HTMLButtonElement).click();
    await flush();
    const remove = [...el.querySelectorAll("button")].find(
      (item) => item.textContent?.trim() === "删除"
    );
    remove?.click();
    await flush();
    expect(document.body.textContent).toContain("确认删除");
    vi.mocked(api.deleteKnowledgeConversation).mockResolvedValue({ ok: true });
    vi.mocked(api.knowledgeConversations).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 30,
    });
    const confirm = [...document.body.querySelectorAll("button")].find(
      (item) => item.textContent === "确认删除"
    );
    confirm?.click();
    await flush();
    expect(api.deleteKnowledgeConversation).toHaveBeenCalledWith("conv-1");
    expect(el.textContent).not.toContain("量能放大可以低吸");
    expect(el.textContent).toContain("还没有问答记录");
  });

  it("新对话会清空当前线程但保留历史列表", async () => {
    const conv = makeConversation();
    const el = await mountKnowledge([makeDoc()], 1, [conv]);
    vi.mocked(api.knowledgeConversation).mockResolvedValue({
      ...conv,
      messages: [
        { role: "user", content: "茅台怎么看" },
        { role: "assistant", content: "量能放大可以低吸", citations: [] },
      ],
    });
    (el.querySelector(".kb-history-open") as HTMLButtonElement).click();
    await flush();
    const newChat = el.querySelector(
      'button[aria-label="新对话"]'
    ) as HTMLButtonElement;
    newChat.click();
    await flush();
    expect(el.textContent).not.toContain("量能放大可以低吸");
    expect(el.querySelector(".chat-title")?.textContent).toBe("新对话");
    expect(el.querySelector('button[aria-label="新对话"]')).toBeNull();
    expect(el.textContent).toContain("茅台怎么看");
  });

  it("可以收起和展开历史面板", async () => {
    const conv = makeConversation();
    const el = await mountKnowledge([makeDoc()], 1, [conv]);
    expect(el.textContent).toContain("茅台怎么看");
    (
      el.querySelector('button[aria-label="收起历史"]') as HTMLButtonElement
    ).click();
    await flush();
    expect(
      el.querySelector(".kb-chat-layout")?.classList.contains("is-collapsed")
    ).toBe(true);
    expect((el.querySelector(".kb-history") as HTMLElement).style.display).toBe(
      "none"
    );
    (
      el.querySelector('button[aria-label="展开历史"]') as HTMLButtonElement
    ).click();
    await flush();
    expect(
      el.querySelector(".kb-chat-layout")?.classList.contains("is-collapsed")
    ).toBe(false);
    expect(el.textContent).toContain("茅台怎么看");
  });

  it("可以从更多菜单重命名历史记录", async () => {
    const conv = makeConversation();
    const el = await mountKnowledge([makeDoc()], 1, [conv]);
    (el.querySelector('[aria-label="更多操作"]') as HTMLButtonElement).click();
    await flush();
    const rename = [...el.querySelectorAll("button")].find(
      (item) => item.textContent?.trim() === "重命名"
    );
    rename?.click();
    await flush();
    expect(document.body.textContent).toContain("重命名对话");
    const titleInput = document.body.querySelector(
      'input[aria-label="对话标题"]'
    ) as HTMLInputElement;
    titleInput.value = "茅台复盘";
    titleInput.dispatchEvent(new Event("input", { bubbles: true }));
    await flush();
    vi.mocked(api.renameKnowledgeConversation).mockResolvedValue({
      ...conv,
      title: "茅台复盘",
      messages: [],
    });
    const save = [...document.body.querySelectorAll("button")].find(
      (item) => item.textContent === "保存"
    );
    save?.click();
    await flush();
    expect(api.renameKnowledgeConversation).toHaveBeenCalledWith(
      "conv-1",
      "茅台复盘"
    );
    expect(el.textContent).toContain("茅台复盘");
  });
});
