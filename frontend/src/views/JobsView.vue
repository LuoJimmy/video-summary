<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ArrowDown, ArrowUp } from "@lucide/vue";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api, type Job, type ResolvePreview, type Site } from "../api";
import type { DomainPack } from "../utils/domain";
import { emptyDomainPack } from "../utils/domain";
import JobDeleteDialog from "../components/JobDeleteDialog.vue";
import JobTitleEditor from "../components/JobTitleEditor.vue";
import {
  formatDateStamp,
  formatDuration,
  isJobActive,
  jobElapsedSeconds,
  localDayBoundIso,
  statusLabel,
} from "../utils/time";
import { toast } from "vue-sonner";

const PAGE_SIZE = 10;
const router = useRouter();
const jobs = ref<Job[]>([]);
const total = ref(0);
const page = ref(1);
const sites = ref<Site[]>([]);
const sourceUrl = ref("");
const mediaOverride = ref("");
const title = ref("");
const siteId = ref("");
const domainId = ref("a-share");
const domainPresets = ref<DomainPack[]>([emptyDomainPack()]);
const preview = ref<ResolvePreview | null>(null);
const file = ref<File | null>(null);
const deleting = ref<Job | null>(null);
const nowMs = ref(Date.now());
const filterTitle = ref("");
const filterStatus = ref("");
const filterDateFrom = ref("");
const filterDateTo = ref("");
const filterSortKey = ref("source_desc");
const appliedFilters = ref({
  title: "",
  status: "",
  dateFrom: "",
  dateTo: "",
  sort: "source",
  order: "desc",
});
let timer: number | undefined;
let clock: number | undefined;

const totalPages = computed(() =>
  Math.max(1, Math.ceil(total.value / PAGE_SIZE))
);
const hasFilters = computed(() =>
  Boolean(
    appliedFilters.value.title ||
    appliedFilters.value.status ||
    appliedFilters.value.dateFrom ||
    appliedFilters.value.dateTo
  )
);

function dateFilterBounds(from: string, to: string) {
  if (from && to && from > to) {
    return {
      dateFrom: localDayBoundIso(to),
      dateTo: localDayBoundIso(from, true),
    };
  }
  return {
    dateFrom: localDayBoundIso(from),
    dateTo: localDayBoundIso(to, true),
  };
}

function currentFilters() {
  const keyword = appliedFilters.value.title;
  const { dateFrom, dateTo } = dateFilterBounds(
    appliedFilters.value.dateFrom,
    appliedFilters.value.dateTo
  );
  return {
    ...(keyword ? { title: keyword } : {}),
    ...(appliedFilters.value.status
      ? { status: appliedFilters.value.status }
      : {}),
    ...(dateFrom ? { dateFrom } : {}),
    ...(dateTo ? { dateTo } : {}),
    ...(appliedFilters.value.sort && appliedFilters.value.sort !== "source"
      ? { sort: appliedFilters.value.sort }
      : {}),
    ...(appliedFilters.value.order && appliedFilters.value.order !== "desc"
      ? { order: appliedFilters.value.order }
      : {}),
  };
}

async function loadJobs() {
  const listed = await api.jobs(page.value, PAGE_SIZE, currentFilters());
  const pages = Math.max(1, Math.ceil(listed.total / listed.page_size));
  if (page.value > pages) {
    page.value = pages;
    const again = await api.jobs(page.value, PAGE_SIZE, currentFilters());
    jobs.value = again.items;
    total.value = again.total;
    return;
  }
  jobs.value = listed.items;
  total.value = listed.total;
}

function applyFilters() {
  appliedFilters.value = {
    title: filterTitle.value.trim(),
    status: filterStatus.value,
    dateFrom: filterDateFrom.value,
    dateTo: filterDateTo.value,
    ...parseSortKey(filterSortKey.value),
  };
  page.value = 1;
  void loadJobs();
}

function resetFilters() {
  filterTitle.value = "";
  filterStatus.value = "";
  filterDateFrom.value = "";
  filterDateTo.value = "";
  filterSortKey.value = "source_desc";
  appliedFilters.value = {
    title: "",
    status: "",
    dateFrom: "",
    dateTo: "",
    sort: "source",
    order: "desc",
  };
  page.value = 1;
  void loadJobs();
}

async function refresh() {
  await loadJobs();
  sites.value = await api.sites();
  try {
    const settings = await api.settings();
    if (settings.domain_presets?.length) {
      domainPresets.value = settings.domain_presets;
    }
    if (!domainPresets.value.some((item) => item.id === domainId.value)) {
      domainId.value = "a-share";
    }
  } catch {
    /* 领域列表保持默认 A 股 */
  }
}

function goPage(next: number) {
  if (next < 1 || next > totalPages.value || next === page.value) return;
  page.value = next;
  void loadJobs();
}

function hasActiveJobs() {
  return jobs.value.some((job) => isJobActive(job.status));
}

function syncClock() {
  if (hasActiveJobs()) {
    nowMs.value = Date.now();
    if (clock === undefined) {
      clock = window.setInterval(() => {
        nowMs.value = Date.now();
      }, 1000);
    }
    return;
  }
  if (clock !== undefined) {
    window.clearInterval(clock);
    clock = undefined;
  }
}

async function rename(job: Job, nextTitle: string) {
  try {
    const updated = await api.updateJob(job.id, { title: nextTitle });
    const index = jobs.value.findIndex((item) => item.id === job.id);
    if (index >= 0)
      jobs.value[index] = { ...jobs.value[index], title: updated.title };
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "修改标题失败");
    throw err;
  }
}

async function cancel(job: Job) {
  try {
    await api.cancelJob(job.id);
    await loadJobs();
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "取消失败");
  }
}

function askDelete(job: Job) {
  deleting.value = job;
}

async function confirmDelete() {
  if (!deleting.value) return;
  try {
    await api.deleteJob(deleting.value.id);
    deleting.value = null;
    await loadJobs();
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "删除失败");
    deleting.value = null;
  }
}

async function doPreview() {
  preview.value = await api.preview({
    source_url: sourceUrl.value,
    media_url_override: mediaOverride.value,
    site_id: siteId.value || null,
  });
}

async function createFromUrl() {
  try {
    const job = await api.createJob({
      source_url: sourceUrl.value,
      media_url_override: mediaOverride.value,
      title: title.value,
      site_id: siteId.value || null,
      domain_id: domainId.value || "a-share",
    });
    await router.push(`/jobs/${job.id}`);
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "创建失败");
  }
}

async function createFromFile() {
  if (!file.value) return;
  const job = await api.uploadJob(
    file.value,
    title.value || file.value.name,
    domainId.value || "a-share"
  );
  await router.push(`/jobs/${job.id}`);
}

function setSiteId(value: string | null) {
  siteId.value = !value || value === "__auto" ? "" : value;
}

function setDomainId(value: string | null) {
  domainId.value = value || "a-share";
}

function setFilterStatus(value: string | null) {
  filterStatus.value = !value || value === "__all" ? "" : value;
}

function parseSortKey(value: string | null) {
  const [sortRaw, orderRaw] = (value || "source_desc").split("_");
  const sort =
    sortRaw === "created" || sortRaw === "title" ? sortRaw : "source";
  const order = orderRaw === "asc" ? "asc" : "desc";
  return { sort, order };
}

function setFilterSort(value: string | null) {
  const { sort, order } = parseSortKey(value);
  filterSortKey.value = `${sort}_${order}`;
  appliedFilters.value = { ...appliedFilters.value, sort, order };
  page.value = 1;
  void loadJobs();
}

onMounted(async () => {
  await refresh();
  syncClock();
  timer = window.setInterval(async () => {
    if (hasActiveJobs()) {
      await loadJobs();
    }
    syncClock();
  }, 2000);
});

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer);
  if (clock !== undefined) window.clearInterval(clock);
});
</script>

<template>
  <h1>任务</h1>
  <p class="sub">
    支持本地文件、线上视频、HLS、B 站，以及已配置登录态的站点页面。
  </p>

  <section class="card">
    <div class="grid two">
      <div class="field">
        <Label>页面或媒体地址</Label>
        <Input
          v-model="sourceUrl"
          placeholder="https://www.bilibili.com/video/BV1a4awzsENn"
        />
      </div>
      <div class="field">
        <Label>媒体地址覆盖（m3u8/mp4，可选）</Label>
        <Input
          v-model="mediaOverride"
          placeholder="登录后从 Network 复制的流地址"
        />
      </div>
      <div class="field">
        <Label>标题（可选）</Label>
        <Input v-model="title" />
      </div>
      <div class="field">
        <Label>指定站点（可留空自动匹配）</Label>
        <Select
          :model-value="siteId || '__auto'"
          @update:model-value="setSiteId"
        >
          <SelectTrigger class="w-full">
            <SelectValue placeholder="自动匹配" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__auto">自动匹配</SelectItem>
            <SelectItem v-for="site in sites" :key="site.id" :value="site.id">{{
              site.name
            }}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div class="field">
        <Label>内容领域</Label>
        <Select :model-value="domainId" @update:model-value="setDomainId">
          <SelectTrigger class="w-full">
            <SelectValue placeholder="A股盘面课" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem
              v-for="item in domainPresets"
              :key="item.id"
              :value="item.id"
            >
              {{ item.name }}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
    <div class="row mt-4">
      <Button variant="outline" type="button" @click="doPreview">预解析</Button>
      <Button type="button" @click="createFromUrl">开始转写总结</Button>
    </div>
    <p v-if="preview" class="msg mt-3">
      适配器 {{ preview.adapter }} / {{ preview.source_type }}
      <br />
      {{ preview.message || preview.media_url || "已解析到媒体地址" }}
    </p>
  </section>

  <section class="card">
    <div class="field">
      <Label>或上传本地视频/音频</Label>
      <Input
        type="file"
        accept="video/*,audio/*"
        @change="file = ($event.target as HTMLInputElement).files?.[0] || null"
      />
    </div>
    <div class="row mt-3">
      <Button type="button" @click="createFromFile">上传并处理</Button>
    </div>
  </section>

  <section class="card pt-0!">
    <div class="job-filters">
      <div class="field field-title">
        <Input
          v-model="filterTitle"
          placeholder="标题"
          aria-label="标题"
          @keydown.enter="applyFilters"
        />
      </div>
      <div class="field field-dates">
        <div class="date-range">
          <Input v-model="filterDateFrom" type="date" aria-label="开始日期" />
          <span class="date-range-sep">至</span>
          <Input v-model="filterDateTo" type="date" aria-label="结束日期" />
        </div>
      </div>
      <div class="field field-status">
        <Select
          :model-value="filterStatus || '__all'"
          @update:model-value="setFilterStatus"
        >
          <SelectTrigger class="w-full" aria-label="状态">
            <SelectValue placeholder="状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all">状态</SelectItem>
            <SelectItem value="active">处理中</SelectItem>
            <SelectItem value="done">已完成</SelectItem>
            <SelectItem value="failed">失败</SelectItem>
            <SelectItem value="cancelled">已取消</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div class="field field-sort">
        <Select
          :model-value="filterSortKey"
          @update:model-value="setFilterSort"
        >
          <SelectTrigger class="sort-trigger" aria-label="排序">
            <ArrowDown v-if="filterSortKey.endsWith('_desc')" class="size-4" />
            <ArrowUp v-else class="size-4" />
            <SelectValue placeholder="排序" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="source_desc">原片时间 降序</SelectItem>
            <SelectItem value="source_asc">原片时间 升序</SelectItem>
            <SelectItem value="created_desc">任务时间 降序</SelectItem>
            <SelectItem value="created_asc">任务时间 升序</SelectItem>
            <SelectItem value="title_desc">标题名称 降序</SelectItem>
            <SelectItem value="title_asc">标题名称 升序</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div class="filter-actions">
        <Button type="button" @click="applyFilters">查询</Button>
        <Button variant="outline" type="button" @click="resetFilters"
          >重置</Button
        >
      </div>
    </div>
    <div v-if="!jobs.length" class="msg empty-list">
      {{ hasFilters ? "没有符合条件的任务。" : "还没有任务。" }}
    </div>
    <div v-for="job in jobs" :key="job.id" class="list-item">
      <div class="list-main">
        <div class="list-title-row">
          <Badge
            v-if="formatDateStamp(job.source_created_at)"
            variant="secondary"
            class="date-badge"
          >
            {{ formatDateStamp(job.source_created_at) }}
          </Badge>
          <JobTitleEditor
            :title="job.title"
            :href="`/jobs/${job.id}`"
            :save="(next) => rename(job, next)"
          />
        </div>
        <div class="msg">{{ job.source_url }}</div>
      </div>
      <div class="list-actions">
        <Badge
          variant="outline"
          class="tag"
          :class="{
            ok: job.status === 'done',
            bad: job.status === 'failed',
            warn: isJobActive(job.status),
          }"
        >
          {{ statusLabel(job.status, job.stage) }}
          <template v-if="isJobActive(job.status)">
            {{ job.progress }}% ·
            {{ formatDuration(jobElapsedSeconds(job, nowMs)) }}</template
          >
        </Badge>
        <Button
          v-if="isJobActive(job.status)"
          variant="destructive"
          type="button"
          @click.prevent="cancel(job)"
        >
          取消
        </Button>
        <Button
          variant="outline"
          class="text-destructive"
          type="button"
          @click.prevent="askDelete(job)"
        >
          删除
        </Button>
      </div>
    </div>
    <div v-if="total > 0 || hasFilters" class="pager">
      <span class="msg"
        >共 {{ total }} 条<template v-if="totalPages > 1"
          >，第 {{ page }} / {{ totalPages }} 页</template
        ></span
      >
      <template v-if="totalPages > 1">
        <Button
          variant="outline"
          type="button"
          :disabled="page <= 1"
          @click="goPage(page - 1)"
          >上一页</Button
        >
        <Button
          variant="outline"
          type="button"
          :disabled="page >= totalPages"
          @click="goPage(page + 1)"
          >下一页</Button
        >
      </template>
    </div>
  </section>

  <JobDeleteDialog
    :open="Boolean(deleting)"
    :title="deleting?.title || ''"
    @close="deleting = null"
    @confirm="confirmDelete"
  />
</template>
