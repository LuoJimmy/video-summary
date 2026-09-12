<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Plus, Trash2 } from "@lucide/vue";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, type AuthProfile, type Site } from "../api";
import { toast } from "vue-sonner";

const COOKIE_HINTS: Record<string, string> = {
  xiaoe:
    "把浏览器里 xetslk.com / xiaoeknow.com 的 Cookie 粘到这里，可同时打通短链与店铺域。",
  yueniu:
    "把 jf.yueniuzq.com 的 Cookie 粘到这里，直播域 jflive.yueniuzq.com 会一并带上。",
  bilibili:
    "公开视频可不填。大会员或需登录的稿件，把 www.bilibili.com 的 Cookie（含 SESSDATA）粘到这里。",
  generic: "一般不需要 Cookie。若直链需要登录，再把 Cookie 粘到这里。",
};

const profiles = ref<AuthProfile[]>([]);
const sites = ref<Site[]>([]);
const selectedId = ref("");
const saving = ref(false);
const adding = ref(false);
const deleting = ref(false);
const askingDelete = ref(false);

const orderedSites = computed(() =>
  [...sites.value].sort(
    (a, b) => Number(a.adapter === "generic") - Number(b.adapter === "generic")
  )
);

const current = computed(
  () =>
    orderedSites.value.find((item) => item.id === selectedId.value) ||
    orderedSites.value[0] ||
    null
);

const isGeneric = computed(() => current.value?.adapter === "generic");
const adapterCount = computed(() => {
  const counts: Record<string, number> = {};
  for (const site of sites.value) {
    counts[site.adapter] = (counts[site.adapter] || 0) + 1;
  }
  return counts;
});
const canDelete = computed(() => {
  const site = current.value;
  if (!site) return false;
  if (site.adapter === "generic") return true;
  return (adapterCount.value[site.adapter] || 0) > 1;
});
const addLabel = computed(() => {
  const adapter = current.value?.adapter || "generic";
  if (adapter === "xiaoe") return "添加小鹅通店铺";
  if (adapter === "bilibili") return "添加 B 站 UP";
  if (adapter === "yueniu") return "添加约牛账号";
  return "添加通用直链";
});
const deleteLabel = computed(() =>
  isGeneric.value ? "删除当前通用直链" : "删除当前站点"
);

const siteSelect = computed({
  get: () => current.value?.id || "",
  set: (value: string) => {
    selectedId.value = value;
  },
});

function profileOf(site: Site | null) {
  if (!site?.auth_profile_id) return null;
  return (
    profiles.value.find((item) => item.id === site.auth_profile_id) || null
  );
}

function cookiePlaceholder(site: Site | null) {
  const notes = profileOf(site)?.notes.trim();
  if (notes) return notes;
  if (site) return COOKIE_HINTS[site.adapter] || COOKIE_HINTS.generic;
  return COOKIE_HINTS.generic;
}

function hydrateCookies() {
  for (const site of sites.value) {
    if (site.cookie_override.trim()) continue;
    const cookie = profileOf(site)?.cookie.trim();
    if (cookie) site.cookie_override = cookie;
  }
}

function selectSite(preferred?: string) {
  const next = preferred || selectedId.value;
  if (next && sites.value.some((item) => item.id === next)) {
    selectedId.value = next;
    return;
  }
  selectedId.value = orderedSites.value[0]?.id || "";
}

async function refresh(preferred?: string) {
  const [nextProfiles, nextSites] = await Promise.all([
    api.profiles(),
    api.sites(),
  ]);
  profiles.value = nextProfiles;
  sites.value = nextSites;
  hydrateCookies();
  selectSite(preferred);
}

function nextName(adapter: string) {
  const labels: Record<string, string> = {
    xiaoe: "小鹅通",
    yueniu: "加菲财经/约牛",
    bilibili: "B站",
    generic: "通用直链",
  };
  const base = labels[adapter] || "站点";
  const used = new Set(
    sites.value.filter((item) => item.adapter === adapter).map((item) => item.name)
  );
  if (!used.has(base)) return base;
  let index = 2;
  while (used.has(`${base} ${index}`)) index += 1;
  return `${base} ${index}`;
}

function patternsText(site: Site) {
  return site.domain_patterns.join(", ");
}

function setPatterns(site: Site, value: string) {
  site.domain_patterns = value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

async function saveCurrent() {
  const site = current.value;
  if (!site || saving.value) return;
  saving.value = true;
  try {
    await api.saveSite(
      {
        name: site.name,
        adapter: site.adapter,
        domain_patterns: site.domain_patterns,
        auth_profile_id: site.auth_profile_id,
        cookie_override: site.cookie_override,
        extra_headers: site.extra_headers,
        enabled: site.enabled,
        notes: site.notes,
      },
      site.id
    );
    const profile = profileOf(site);
    if (profile) {
      await api.saveProfile(
        {
          name: profile.name,
          cookie: site.cookie_override,
          extra_headers: profile.extra_headers,
          notes: profile.notes,
        },
        profile.id
      );
    }
    toast.success(`已保存站点：${site.name}`);
    await refresh(site.id);
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "保存站点失败");
  } finally {
    saving.value = false;
  }
}

async function addCurrentKind() {
  if (adding.value) return;
  const template =
    current.value ||
    sites.value.find((item) => item.adapter === "generic") ||
    sites.value[0] ||
    null;
  const adapter = template?.adapter || "generic";
  adding.value = true;
  try {
    const created = await api.saveSite({
      name: nextName(adapter),
      adapter,
      domain_patterns: template?.domain_patterns || [],
      auth_profile_id: template?.auth_profile_id || null,
      cookie_override: template?.cookie_override || "",
      extra_headers: template?.extra_headers || {},
      enabled: true,
      notes: template?.notes || "",
    });
    toast.success(`已添加站点：${created.name}`);
    await refresh(created.id);
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "添加站点失败");
  } finally {
    adding.value = false;
  }
}

function askDelete() {
  if (!canDelete.value || deleting.value || adding.value) return;
  askingDelete.value = true;
}

async function deleteCurrent() {
  const site = current.value;
  if (!site || !canDelete.value || deleting.value) return;
  askingDelete.value = false;
  deleting.value = true;
  try {
    await api.deleteSite(site.id);
    toast.success(`已删除站点：${site.name}`);
    selectedId.value = "";
    await refresh();
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "删除站点失败");
  } finally {
    deleting.value = false;
  }
}

onMounted(refresh);
</script>

<template>
  <h1>站点</h1>
  <p class="sub">
    小鹅通、约牛、B 站可添加多条：每个店铺或 UP
    单独命名。Cookie 可共用同一登录档案。通用直链也可以自行增减。
  </p>

  <section class="card">
    <div class="grid two">
      <div class="field">
        <div class="flex items-center gap-1">
          <Label>当前站点</Label>
          <Button
            variant="ghost"
            size="icon-xs"
            class="icon-btn disabled:pointer-events-auto disabled:cursor-not-allowed"
            type="button"
            aria-label="添加站点"
            :title="addLabel"
            :disabled="adding || deleting"
            @click="addCurrentKind"
          >
            <Plus class="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon-xs"
            class="icon-btn text-destructive disabled:pointer-events-auto disabled:cursor-not-allowed"
            type="button"
            aria-label="删除当前站点"
            :title="deleteLabel"
            :disabled="adding || deleting || !canDelete"
            @click="askDelete"
          >
            <Trash2 class="size-4" />
          </Button>
        </div>
        <Select v-if="orderedSites.length" v-model="siteSelect">
          <SelectTrigger class="w-full">
            <SelectValue placeholder="选择站点" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem
              v-for="item in orderedSites"
              :key="item.id"
              :value="item.id"
            >
              {{ item.name }}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div v-if="current" class="field">
        <Label>名称</Label>
        <Input v-model="current.name" placeholder="站点名称" />
      </div>
    </div>

    <template v-if="current">
      <p v-if="current.notes" class="msg mt-3">{{ current.notes }}</p>
      <div class="field mt-3">
        <Label>域名规则（逗号分隔）</Label>
        <Input
          :model-value="patternsText(current)"
          placeholder="example.com, cdn.example.com"
          @update:model-value="setPatterns(current, String($event ?? ''))"
        />
      </div>
      <div class="field mt-3">
        <Label>Cookie</Label>
        <Textarea
          v-model="current.cookie_override"
          :placeholder="cookiePlaceholder(current)"
        />
      </div>
      <div class="row mt-3">
        <Button type="button" :disabled="saving" @click="saveCurrent"
          >保存站点</Button
        >
      </div>
    </template>
    <p v-else class="msg mt-3">还没有站点。可以先添加一条通用直链。</p>
  </section>

  <Dialog
    :open="askingDelete"
    @update:open="
      (next: boolean) => {
        if (!next) askingDelete = false;
      }
    "
  >
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>确认删除</DialogTitle>
        <DialogDescription>
          确定删除站点「{{
            current?.name || "当前站点"
          }}」？已有任务仍保留记录。定时任务里对应的内容源也会去掉。
        </DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <Button
          variant="outline"
          type="button"
          :disabled="deleting"
          @click="askingDelete = false"
          >取消</Button
        >
        <Button
          variant="destructive"
          type="button"
          :disabled="deleting"
          @click="deleteCurrent"
          >确认删除</Button
        >
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
