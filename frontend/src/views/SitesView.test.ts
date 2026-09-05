import { createApp, nextTick } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import { toast } from "vue-sonner";
import { api, type AuthProfile, type Site } from "../api";
import SitesView from "./SitesView.vue";

vi.mock("vue-sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}));

vi.mock("../api", () => ({
  api: {
    profiles: vi.fn(),
    sites: vi.fn(),
    saveProfile: vi.fn(),
    saveSite: vi.fn(),
    deleteSite: vi.fn(),
  },
}));

function makeProfile(overrides: Partial<AuthProfile> = {}): AuthProfile {
  return {
    id: "p-xiaoe",
    name: "小鹅通登录档案",
    cookie: "",
    extra_headers: {},
    notes: "把浏览器里 xetslk.com / xiaoeknow.com 的 Cookie 粘到这里。",
    ...overrides,
  };
}

function makeSite(overrides: Partial<Site> = {}): Site {
  return {
    id: "s-xiaoe",
    name: "小鹅通",
    adapter: "xiaoe",
    domain_patterns: ["xetslk.com", "xiaoeknow.com"],
    auth_profile_id: "p-xiaoe",
    cookie_override: "",
    extra_headers: {},
    enabled: true,
    notes: "示例：https://etrsz.xetslk.com/sl/q1M06",
    ...overrides,
  };
}

const seedProfiles = [
  makeProfile(),
  makeProfile({
    id: "p-bili",
    name: "B站登录档案",
    notes: "公开视频可不填。",
  }),
];

const seedSites = [
  makeSite(),
  makeSite({
    id: "s-bili",
    name: "B站",
    adapter: "bilibili",
    domain_patterns: ["bilibili.com"],
    auth_profile_id: "p-bili",
    notes: "示例：https://www.bilibili.com/video/BV1a4awzsENn",
  }),
  makeSite({
    id: "s-generic",
    name: "通用直链",
    adapter: "generic",
    domain_patterns: [],
    auth_profile_id: null,
    notes: "本地文件、公开 mp4/m3u8，或不匹配其他站点时使用。",
  }),
];

let root: HTMLElement | undefined;
let app: ReturnType<typeof createApp> | undefined;

async function flush() {
  for (let i = 0; i < 8; i++) await Promise.resolve();
  await nextTick();
}

async function mountSites(
  sites: Site[] = seedSites,
  profiles: AuthProfile[] = seedProfiles
) {
  vi.mocked(api.profiles).mockResolvedValue(profiles);
  vi.mocked(api.sites).mockResolvedValue(sites.map((item) => ({ ...item })));
  root = document.createElement("div");
  document.body.appendChild(root);
  app = createApp(SitesView);
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
  vi.mocked(api.saveSite).mockReset();
  vi.mocked(api.saveProfile).mockReset();
  vi.mocked(api.deleteSite).mockReset();
});

describe("站点页", () => {
  it("不再单独列出档案，适配器不可选，站点用下拉切换", async () => {
    const el = await mountSites();
    expect(el.textContent).not.toContain("保存档案");
    expect(el.textContent).not.toContain("绑定登录档案");
    expect(el.textContent).toContain("当前站点");
    expect(el.querySelectorAll('[data-slot="textarea"]').length).toBe(1);
    expect(el.querySelectorAll("h3").length).toBe(0);
    const addBtn = el.querySelector(
      '[aria-label="添加通用直链"]'
    ) as HTMLButtonElement;
    const deleteBtn = el.querySelector(
      '[aria-label="删除当前通用直链"]'
    ) as HTMLButtonElement;
    expect(addBtn).toBeTruthy();
    expect(deleteBtn.disabled).toBe(true);
    const cookie = el.querySelector("textarea") as HTMLTextAreaElement;
    expect(cookie.placeholder).toContain("xetslk.com");
  });

  it("档案 Cookie 会填到当前站点，空值时用原备注做 placeholder", async () => {
    const el = await mountSites(
      [makeSite({ cookie_override: "" })],
      [makeProfile({ cookie: "sid=from-profile" })]
    );
    const cookie = el.querySelector("textarea") as HTMLTextAreaElement;
    expect(cookie.value).toBe("sid=from-profile");
  });

  it("可以添加通用直链并切到新建项", async () => {
    const created = makeSite({
      id: "s-generic-2",
      name: "通用直链 2",
      adapter: "generic",
      auth_profile_id: null,
      domain_patterns: [],
    });
    const el = await mountSites();
    vi.mocked(api.saveSite).mockResolvedValue(created);
    vi.mocked(api.sites).mockResolvedValue(
      [...seedSites, created].map((item) => ({ ...item }))
    );
    const addBtn = el.querySelector(
      '[aria-label="添加通用直链"]'
    ) as HTMLButtonElement;
    addBtn.click();
    await flush();
    expect(api.saveSite).toHaveBeenCalledWith(
      expect.objectContaining({
        adapter: "generic",
        name: "通用直链 2",
      })
    );
    expect(toast.success).toHaveBeenCalled();
  });

  it("当前是通用直链时可以删除", async () => {
    const generic = makeSite({
      id: "s-generic",
      name: "通用直链",
      adapter: "generic",
      auth_profile_id: null,
      domain_patterns: [],
    });
    const el = await mountSites([generic], []);
    const deleteBtn = el.querySelector(
      '[aria-label="删除当前通用直链"]'
    ) as HTMLButtonElement;
    expect(deleteBtn.disabled).toBe(false);
    deleteBtn.click();
    await flush();
    expect(document.body.textContent).toContain("确认删除");
    vi.mocked(api.deleteSite).mockResolvedValue({ ok: true });
    vi.mocked(api.sites).mockResolvedValue([]);
    const confirm = [...document.body.querySelectorAll("button")].find(
      (item) => item.textContent === "确认删除"
    );
    confirm?.click();
    await flush();
    expect(api.deleteSite).toHaveBeenCalledWith("s-generic");
  });
});
