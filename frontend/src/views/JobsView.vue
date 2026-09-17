<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ArrowDown, ArrowUp, Info, Loader2, Upload, X } from "@lucide/vue";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { api, type CatalogPreviewItem, type Job, type JobCatalogResult, type ResolvePreview, type Site } from "../api";
import type { DomainPack } from "../utils/domain";
import { emptyDomainPack } from "../utils/domain";
import {
  isCatalogSourceUrl,
  isDigestSource,
  needsMediaOverrideError,
  parseSourceUrls,
  publicSourceUrl,
  SOURCE_URL_BATCH_LIMIT,
} from "../utils/source";
import CatalogImportDialog from "../components/CatalogImportDialog.vue";
import JobDeleteDialog from "../components/JobDeleteDialog.vue";
import JobTitleEditor from "../components/JobTitleEditor.vue";
import Pagination from "../components/Pagination.vue";
import { pageAfterSizeChange } from "../utils/pager";
import {
  formatDateStamp,
  formatDuration,
  isJobActive,
  jobElapsedSeconds,
  localDayBoundIso,
  statusLabel,
} from "../utils/time";
import { toast } from "vue-sonner";

const DEFAULT_PAGE_SIZE = 10;
const LOCAL_FILE_ACCEPT =
  "video/*,audio/*,.pdf,.doc,.docx,.md,.txt,.html,.htm,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown,text/html";
const router = useRouter();
type CreateTab = "online" | "local";
const createTabs: { id: CreateTab; label: string }[] = [
  { id: "online", label: "在线任务" },
  { id: "local", label: "本地任务" },
];
const createTab = ref<CreateTab>("online");
const jobs = ref<Job[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(DEFAULT_PAGE_SIZE);
const sites = ref<Site[]>([]);
const sourceUrl = ref("");
const mediaOverride = ref("");
const title = ref("");
const author = ref("");
const siteId = ref("");
const domainId = ref("a-share");
const domainPresets = ref<DomainPack[]>([emptyDomainPack()]);
const preview = ref<ResolvePreview | null>(null);
const catalogOpen = ref(false);
const catalogContinuing = ref(false);
const catalogPreview = ref<ResolvePreview | null>(null);
const catalogSourceUrl = ref("");
const catalogResume = ref<{
  sourceUrl: string;
  cursor: string;
  label: string;
} | null>(null);
let catalogWait: ((items: CatalogPreviewItem[] | null) => void) | null = null;
const files = ref<File[]>([]);
const fileInput = ref<HTMLInputElement | null>(null);
const summarizeDocument = ref(false);
const creating = ref(false);
type ListingAction = "create" | "continue";
const listing = ref<ListingAction | null>(null);
const jobBusy = computed(() => creating.value || Boolean(listing.value));
const showMediaOverride = computed(
  () =>
    Boolean(mediaOverride.value.trim()) ||
    jobs.value.some((job) => needsMediaOverrideError(job.error))
);
const catalogSubmitting = ref(false);
const batchBusy = ref(false);
const selectedIds = ref<Set<string>>(new Set());
const deleting = ref<{ title: string; ids: string[] } | null>(null);
const nowMs = ref(Date.now());
const filterTitle = ref("");
const filterStatus = ref("");
const filterDateFrom = ref("");
const filterDateTo = ref("");
const filterSortKey = ref("created_desc");
const appliedFilters = ref({
  title: "",
  status: "",
  dateFrom: "",
  dateTo: "",
  sort: "created",
  order: "desc",
});
let timer: number | undefined;
let clock: number | undefined;

const totalPages = computed(() =>
  Math.max(1, Math.ceil(total.value / pageSize.value))
);
const hasFilters = computed(() =>
  Boolean(
    appliedFilters.value.title ||
    appliedFilters.value.status ||
    appliedFilters.value.dateFrom ||
    appliedFilters.value.dateTo
  )
);
const sourceUrls = computed(() => parseSourceUrls(sourceUrl.value));
const selectedCount = computed(() => selectedIds.value.size);
const selectedJobs = computed(() =>
  jobs.value.filter((job) => selectedIds.value.has(job.id))
);
const unknownSelectedCount = computed(
  () => selectedIds.value.size - selectedJobs.value.length
);
const pageSelectedCount = computed(() => selectedJobs.value.length);
const canBatchCancel = computed(
  () =>
    selectedJobs.value.some((job) => isJobActive(job.status)) ||
    unknownSelectedCount.value > 0
);
const canBatchRetry = computed(
  () =>
    selectedJobs.value.some((job) => canRetry(job.status)) ||
    unknownSelectedCount.value > 0
);
const canBatchDigest = computed(
  () =>
    selectedJobs.value.filter(canDigestJob).length + unknownSelectedCount.value >=
    2
);
const pageSelectState = computed(() => {
  if (!jobs.value.length || pageSelectedCount.value === 0) return false;
  if (pageSelectedCount.value === jobs.value.length) return true;
  return "indeterminate" as const;
});
const filePickerLabel = computed(() => {
  if (!files.value.length) return "未选择文件";
  if (files.value.length === 1) return files.value[0].name;
  return `已选 ${files.value.length} 个文件`;
});

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
  const listed = await api.jobs(page.value, pageSize.value, currentFilters());
  const pages = Math.max(1, Math.ceil(listed.total / listed.page_size));
  if (page.value > pages) {
    page.value = pages;
    const again = await api.jobs(page.value, pageSize.value, currentFilters());
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
  filterSortKey.value = "created_desc";
  appliedFilters.value = {
    title: "",
    status: "",
    dateFrom: "",
    dateTo: "",
    sort: "created",
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

function changePageSize(next: number) {
  if (next === pageSize.value) return;
  page.value = pageAfterSizeChange(page.value, pageSize.value, next);
  pageSize.value = next;
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

function canRetry(status: string) {
  return status === "failed" || status === "cancelled";
}

function canDigestJob(job: Job) {
  return job.status === "done" && !isDigestSource(job.source_type);
}

function pruneSelection(ids: string[]) {
  if (!ids.length) return;
  const remove = new Set(ids);
  selectedIds.value = new Set(
    [...selectedIds.value].filter((id) => !remove.has(id))
  );
}

function setJobSelected(id: string, checked: boolean | "indeterminate") {
  const next = new Set(selectedIds.value);
  if (checked === true) next.add(id);
  else next.delete(id);
  selectedIds.value = next;
}

function setPageSelect(value: boolean | "indeterminate") {
  const next = new Set(selectedIds.value);
  if (value === true) {
    for (const job of jobs.value) next.add(job.id);
  } else {
    for (const job of jobs.value) next.delete(job.id);
  }
  selectedIds.value = next;
}

function offPageSelectedIds() {
  const onPage = new Set(jobs.value.map((job) => job.id));
  return [...selectedIds.value].filter((id) => !onPage.has(id));
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
  deleting.value = { title: job.title, ids: [job.id] };
}

function askBatchDelete() {
  const ids = [...selectedIds.value];
  if (!ids.length) return;
  deleting.value = { title: "", ids };
}

async function confirmDelete() {
  if (!deleting.value) return;
  const ids = deleting.value.ids;
  try {
    if (ids.length === 1) {
      await api.deleteJob(ids[0]);
    } else {
      const result = await api.batchJobs("delete", ids);
      if (result.failed.length && !result.ok.length) {
        toast.error(result.failed[0]?.reason || "删除失败");
      } else if (result.failed.length) {
        toast.warning(`成功 ${result.ok.length}，失败 ${result.failed.length}`);
      }
    }
    pruneSelection(ids);
    deleting.value = null;
    await loadJobs();
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "删除失败");
    deleting.value = null;
  }
}

function toastBatchAction(
  ok: number,
  failed: number,
  emptyMessage: string,
  doneLabel: string
) {
  if (!ok && !failed) {
    toast.error(emptyMessage);
    return;
  }
  if (!ok) {
    toast.error(emptyMessage);
    return;
  }
  if (!failed) {
    toast.success(`${doneLabel} ${ok} 个任务`);
    return;
  }
    toast.warning(`成功 ${ok}，失败 ${failed}`);
}

async function batchDigest() {
  const ids = [...selectedIds.value];
  if (ids.length < 2) {
    toast.error("请至少选择 2 个任务");
    return;
  }
  if (batchBusy.value) return;
  batchBusy.value = true;
  try {
    const job = await api.digestJobs(ids);
    selectedIds.value = new Set();
    toast.success("已创建汇总任务");
    await router.push(`/jobs/${job.id}`);
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "汇总失败");
  } finally {
    batchBusy.value = false;
  }
}

async function batchCancel() {
  const ids = [
    ...jobs.value
      .filter((job) => selectedIds.value.has(job.id) && isJobActive(job.status))
      .map((job) => job.id),
    ...offPageSelectedIds(),
  ];
  if (!ids.length) {
    toast.error("所选任务没有可取消的");
    return;
  }
  if (batchBusy.value) return;
  batchBusy.value = true;
  try {
    const result = await api.batchJobs("cancel", ids);
    pruneSelection(result.ok);
    toastBatchAction(
      result.ok.length,
      result.failed.length,
      "所选任务没有可取消的",
      "已取消"
    );
    await loadJobs();
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "取消失败");
  } finally {
    batchBusy.value = false;
  }
}

async function batchRetry() {
  const ids = [
    ...jobs.value
      .filter((job) => selectedIds.value.has(job.id) && canRetry(job.status))
      .map((job) => job.id),
    ...offPageSelectedIds(),
  ];
  if (!ids.length) {
    toast.error("所选任务没有可重试的");
    return;
  }
  if (batchBusy.value) return;
  batchBusy.value = true;
  try {
    const result = await api.batchJobs("retry", ids);
    pruneSelection(result.ok);
    toastBatchAction(
      result.ok.length,
      result.failed.length,
      "所选任务没有可重试的",
      "已重试"
    );
    await loadJobs();
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "重试失败");
  } finally {
    batchBusy.value = false;
  }
}

function closeCatalogDialog() {
  catalogOpen.value = false;
  catalogWait?.(null);
  catalogWait = null;
}

function confirmCatalogDialog(items: CatalogPreviewItem[]) {
  catalogOpen.value = false;
  catalogWait?.(items);
  catalogWait = null;
}

function askCatalogConfirm(
  listed: ResolvePreview,
  url: string,
  continuing: boolean
): Promise<CatalogPreviewItem[] | null> {
  catalogPreview.value = listed;
  catalogSourceUrl.value = url;
  catalogContinuing.value = continuing;
  catalogOpen.value = true;
  return new Promise((resolve) => {
    catalogWait = resolve;
  });
}

function applyCatalogResult(result: JobCatalogResult, url: string) {
  preview.value = {
    adapter: preview.value?.adapter || "",
    title: result.catalog_label,
    source_type: "catalog",
    media_url: "",
    needs_media_url: false,
    message: result.message,
    catalog: true,
    catalog_label: result.catalog_label,
  };
  if (result.next_cursor) {
    catalogResume.value = {
      sourceUrl: url,
      cursor: result.next_cursor,
      label: result.catalog_label,
    };
    toast.warning(
      result.message || "已创建任务。创建区可继续拉取下一批。"
    );
    return;
  }
  catalogResume.value = null;
  if (result.truncated) {
    toast.warning(result.message || "已创建任务，更早内容无法继续自动拉取。");
    return;
  }
  toast.success(result.message || `已创建 ${result.created} 个任务，目录已拉完。`);
}

async function importCatalog(
  url: string,
  continuing: boolean,
  action: ListingAction = "create"
) {
  listing.value = action;
  let listed: ResolvePreview;
  try {
    listed = await api.preview({
      source_url: url,
      site_id: siteId.value || null,
      cursor: continuing ? catalogResume.value?.cursor || "" : "",
    });
  } finally {
    listing.value = null;
  }
  preview.value = listed;
  if (!listed.catalog) {
    toast.error("不是可展开的空间/店铺/站点地址");
    return false;
  }
  if (!listed.items?.length) {
    toast.error(listed.message || "没有可拉取的视频");
    if (listed.truncated) {
      catalogResume.value = listed.next_cursor
        ? { sourceUrl: url, cursor: listed.next_cursor, label: listed.catalog_label || "" }
        : catalogResume.value;
    }
    return false;
  }
  const picked = await askCatalogConfirm(listed, url, continuing);
  if (!picked) return false;
  catalogSubmitting.value = true;
  try {
    const result = await api.fromCatalog({
      source_url: url,
      author: author.value,
      site_id: siteId.value || null,
      domain_id: domainId.value || "a-share",
      items: picked,
      next_cursor: listed.next_cursor || "",
      truncated: listed.truncated || false,
      catalog_label: listed.catalog_label || "",
    });
    applyCatalogResult(result, url);
    await loadJobs();
    return true;
  } finally {
    catalogSubmitting.value = false;
  }
}

async function continueCatalog() {
  if (!catalogResume.value || jobBusy.value) return;
  try {
    await importCatalog(catalogResume.value.sourceUrl, true, "continue");
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "继续拉取失败");
  }
}

function endCatalogResume() {
  catalogResume.value = null;
  preview.value = {
    adapter: "",
    title: "",
    source_type: "",
    media_url: "",
    needs_media_url: false,
    message: "已结束本次拉取，已创建的任务会继续处理。",
  };
}

watch(sourceUrl, () => {
  catalogResume.value = null;
});

watch(createTab, (tab) => {
  if (tab === "local") catalogResume.value = null;
});

async function finishCreated(created: Job[], failed: number, verb: string) {
  if (created.length === 1 && failed === 0) {
    await router.push(`/jobs/${created[0].id}`);
    return;
  }
  if (created.length) await loadJobs();
  if (!failed) {
    toast.success(`已${verb} ${created.length} 个任务`);
    return;
  }
  if (!created.length) {
    toast.error(`${verb}失败`);
    return;
  }
  toast.warning(`成功 ${created.length}，失败 ${failed}`);
}

async function createFromUrl() {
  const urls = sourceUrls.value;
  if (!urls.length) {
    toast.error("请提供页面地址或媒体地址");
    return;
  }
  if (urls.length > SOURCE_URL_BATCH_LIMIT) {
    toast.error(`一次最多创建 ${SOURCE_URL_BATCH_LIMIT} 个任务`);
    return;
  }
  if (urls.length > 1 && mediaOverride.value.trim()) {
    toast.error("批量创建时请先清空媒体地址覆盖");
    return;
  }
  if (jobBusy.value) return;
  creating.value = true;
  const created: Job[] = [];
  let failed = 0;
  let importedCatalog = false;
  try {
    for (const url of urls) {
      if (isCatalogSourceUrl(url)) {
        try {
          importedCatalog = (await importCatalog(url, false)) || importedCatalog;
        } catch (err) {
          failed += 1;
          toast.error(err instanceof Error ? err.message : "拉取目录失败");
        }
        continue;
      }
      try {
        created.push(
          await api.createJob({
            source_url: url,
            media_url_override: urls.length === 1 ? mediaOverride.value : "",
            title: urls.length === 1 ? title.value : "",
            author: author.value,
            site_id: siteId.value || null,
            domain_id: domainId.value || "a-share",
            summarize_document: summarizeDocument.value,
          })
        );
      } catch (err) {
        failed += 1;
        if (urls.length === 1) {
          toast.error(err instanceof Error ? err.message : "创建失败");
        }
      }
    }
    if (importedCatalog) return;
    if (urls.length === 1) {
      if (created[0]) await router.push(`/jobs/${created[0].id}`);
      return;
    }
    await finishCreated(created, failed, "创建");
  } finally {
    creating.value = false;
  }
}

async function createFromFile() {
  const picked = files.value;
  if (!picked.length) return;
  if (picked.length > SOURCE_URL_BATCH_LIMIT) {
    toast.error(`一次最多创建 ${SOURCE_URL_BATCH_LIMIT} 个任务`);
    return;
  }
  if (jobBusy.value) return;
  creating.value = true;
  const created: Job[] = [];
  let failed = 0;
  try {
    for (const item of picked) {
      try {
        created.push(
          await api.uploadJob(
            item,
            picked.length === 1 ? title.value || item.name : item.name,
            domainId.value || "a-share",
            author.value,
            summarizeDocument.value
          )
        );
      } catch (err) {
        failed += 1;
        if (picked.length === 1) {
          toast.error(err instanceof Error ? err.message : "上传失败");
        }
      }
    }
    if (picked.length === 1) {
      if (created[0]) await router.push(`/jobs/${created[0].id}`);
      return;
    }
    await finishCreated(created, failed, "上传");
  } finally {
    creating.value = false;
  }
}

function pickLocalFile() {
  const input = fileInput.value;
  if (!input) return;
  input.value = "";
  input.click();
}

function onLocalFileChange(event: Event) {
  files.value = Array.from((event.target as HTMLInputElement).files || []);
}

function removeLocalFile(index: number) {
  files.value = files.value.filter((_, itemIndex) => itemIndex !== index);
  const input = fileInput.value;
  if (input) input.value = "";
}

function localFileKey(item: File, index: number) {
  return `${item.name}-${item.size}-${item.lastModified}-${index}`;
}

function setCreateTab(id: CreateTab) {
  createTab.value = id;
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
  const [sortRaw, orderRaw] = (value || "created_desc").split("_");
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

function jobSourceLine(job: Job) {
  return [job.author?.trim(), publicSourceUrl(job.source_url)]
    .filter(Boolean)
    .join(" · ");
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
    支持本地文件、线上视频、HLS、B 站，以及 PDF / Word / Markdown /
    网页。文档默认直接入库原文。
  </p>
  <div class="tablist" role="tablist" aria-label="创建任务方式">
    <button
      v-for="item in createTabs"
      :id="`create-tab-${item.id}`"
      :key="item.id"
      type="button"
      role="tab"
      class="tab"
      :aria-selected="createTab === item.id"
      :aria-controls="`create-panel-${item.id}`"
      :tabindex="createTab === item.id ? 0 : -1"
      @click="setCreateTab(item.id)"
    >
      {{ item.label }}
    </button>
  </div>
  <section class="card">
    <div
      v-show="createTab === 'online'"
      id="create-panel-online"
      role="tabpanel"
      aria-labelledby="create-tab-online"
    >
      <div class="field field-full">
        <Label>页面或媒体地址</Label>
        <Textarea
          v-model="sourceUrl"
          rows="3"
          placeholder="每行一个地址。支持视频页、B 站空间、小鹅通店铺、约牛首页"
        />
      </div>
      <div class="grid two">
        <div v-if="showMediaOverride" class="field field-lg">
          <Label>媒体地址覆盖（m3u8/mp4，可选）</Label>
          <Input
            v-model="mediaOverride"
            placeholder="登录后从 Network 复制的流地址"
          />
        </div>
        <div v-if="sourceUrls.length <= 1" class="field field-md">
          <Label>标题（可选）</Label>
          <Input v-model="title" />
        </div>
        <div class="field field-md">
          <Label>视频作者（可选）</Label>
          <Input v-model="author" />
        </div>
        <div class="field field-md">
          <Label>指定站点（可留空自动匹配）</Label>
          <Select
            :model-value="siteId || '__auto'"
            @update:model-value="setSiteId"
          >
            <SelectTrigger>
              <SelectValue placeholder="自动匹配" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__auto">自动匹配</SelectItem>
              <SelectItem
                v-for="site in sites"
                :key="site.id"
                :value="site.id"
                >{{ site.name }}</SelectItem
              >
            </SelectContent>
          </Select>
        </div>
        <div class="field field-md">
          <Label>内容领域</Label>
          <Select :model-value="domainId" @update:model-value="setDomainId">
            <SelectTrigger>
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
    </div>

    <div
      v-show="createTab === 'local'"
      id="create-panel-local"
      role="tabpanel"
      aria-labelledby="create-tab-local"
    >
      <div class="field">
        <Label for="local-file">上传本地视频 / 音频 / 文档</Label>
        <div class="upload-picker">
          <input
            id="local-file"
            ref="fileInput"
            class="sr-only"
            type="file"
            multiple
            :accept="LOCAL_FILE_ACCEPT"
            tabindex="-1"
            aria-hidden="true"
            @change="onLocalFileChange"
          />
          <Button variant="outline" type="button" @click="pickLocalFile">
            <Upload aria-hidden="true" />
            选择文件
          </Button>
          <span class="msg">{{ filePickerLabel }}</span>
        </div>
        <ul v-if="files.length > 1" class="file-name-list">
          <li
            v-for="(item, index) in files"
            :key="localFileKey(item, index)"
            class="file-name-item"
          >
            <span class="file-name-text">{{ item.name }}</span>
            <button
              type="button"
              class="file-remove"
              :aria-label="`移除 ${item.name}`"
              @click="removeLocalFile(index)"
            >
              <X aria-hidden="true" />
            </button>
          </li>
        </ul>
      </div>
      <div class="grid two mt-4">
        <div v-if="files.length <= 1" class="field field-md">
          <Label>标题（可选）</Label>
          <Input v-model="title" />
        </div>
        <div class="field field-md">
          <Label>作者（可选）</Label>
          <Input v-model="author" />
        </div>
        <div class="field field-md">
          <Label>内容领域</Label>
          <Select :model-value="domainId" @update:model-value="setDomainId">
            <SelectTrigger>
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
    </div>

    <div class="mt-4 flex items-center gap-2">
      <Checkbox id="summarize-document" v-model="summarizeDocument" />
      <Label for="summarize-document">文档生成 AI 总结</Label>
      <button
        type="button"
        class="info-tip"
        aria-label="文档总结说明"
        aria-describedby="summarize-document-hint"
      >
        <Info aria-hidden="true" />
        <span id="summarize-document-hint" class="info-tip-text" role="tooltip">
          文档/网页默认直接入库原文；勾选后才调用总结模型。音视频始终会总结。
        </span>
      </button>
    </div>
    <div v-show="createTab === 'online'" class="row mt-4">
      <Button
        v-if="!catalogResume"
        type="button"
        :disabled="jobBusy"
        :aria-busy="listing === 'create'"
        @click="createFromUrl"
      >
        <Loader2 v-if="listing === 'create'" class="size-4 animate-spin" />
        {{ listing === "create" ? "解析中…" : "开始转写总结" }}
      </Button>
      <Button
        v-if="catalogResume"
        type="button"
        :disabled="jobBusy"
        :aria-busy="listing === 'continue'"
        @click="continueCatalog"
      >
        <Loader2 v-if="listing === 'continue'" class="size-4 animate-spin" />
        {{ listing === "continue" ? "拉取中…" : "继续拉取下一批" }}
      </Button>
      <Button
        v-if="catalogResume"
        variant="outline"
        type="button"
        :disabled="jobBusy"
        @click="endCatalogResume"
        >结束本次拉取</Button
      >
    </div>
    <p v-if="catalogResume && createTab === 'online'" class="msg mt-3">
      {{
        preview?.message ||
        `该${catalogResume.label}还有后续内容。`
      }}
    </p>
    <p
      v-else-if="preview && createTab === 'online'"
      class="msg mt-3"
    >
      <template v-if="preview.catalog">
        识别为 {{ preview.catalog_label }}，本批 {{ preview.listed }} 条，已存在
        {{ preview.existing }} 条将跳过。
        <br />
        {{ preview.message }}
      </template>
      <template v-else>
        适配器 {{ preview.adapter }} / {{ preview.source_type }}
        <br />
        {{ preview.message || preview.media_url || "已解析到媒体地址" }}
      </template>
    </p>
    <div v-show="createTab === 'local'" class="row mt-4">
      <Button type="button" :disabled="jobBusy" @click="createFromFile"
        >上传并处理</Button
      >
    </div>
  </section>

  <section class="card pt-0!">
    <div class="job-filters">
      <div class="field field-title">
        <Input
          v-model="filterTitle"
          placeholder="标题 / 作者"
          aria-label="标题或作者"
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
            <SelectItem value="created_desc">任务时间 降序</SelectItem>
            <SelectItem value="created_asc">任务时间 升序</SelectItem>
            <SelectItem value="source_desc">原片时间 降序</SelectItem>
            <SelectItem value="source_asc">原片时间 升序</SelectItem>
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
    <div v-if="jobs.length" class="list-toolbar">
      <Checkbox
        :model-value="pageSelectState"
        aria-label="全选当前页"
        @update:model-value="setPageSelect"
      />
      <div
        class="list-toolbar-meta"
        :class="{ 'is-idle': !selectedCount }"
        :aria-hidden="selectedCount ? undefined : true"
      >
        <span class="msg">已选 {{ selectedCount }}</span>
        <div class="list-actions">
          <Button
            variant="outline"
            type="button"
            :disabled="batchBusy || !selectedCount || !canBatchDigest"
            @click="batchDigest"
            >汇总总结</Button
          >
          <Button
            variant="outline"
            type="button"
            :disabled="batchBusy || !selectedCount || !canBatchCancel"
            @click="batchCancel"
            >取消</Button
          >
          <Button
            variant="outline"
            type="button"
            :disabled="batchBusy || !selectedCount || !canBatchRetry"
            @click="batchRetry"
            >重试</Button
          >
          <Button
            variant="outline"
            class="text-destructive"
            type="button"
            :disabled="batchBusy || !selectedCount"
            @click="askBatchDelete"
            >删除</Button
          >
        </div>
      </div>
    </div>
    <div v-if="!jobs.length" class="msg empty-list">
      {{ hasFilters ? "没有符合条件的任务。" : "还没有任务。" }}
    </div>
    <div v-for="job in jobs" :key="job.id" class="list-item">
      <div class="list-body">
        <Checkbox
          class="list-check"
          :model-value="selectedIds.has(job.id)"
          :aria-label="`选择 ${job.title || '未命名任务'}`"
          @update:model-value="
            (value: boolean | 'indeterminate') => setJobSelected(job.id, value)
          "
        />
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
          <div class="msg">{{ jobSourceLine(job) }}</div>
        </div>
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
    <Pagination
      v-if="total > 0 || hasFilters"
      :total="total"
      :page="page"
      :page-size="pageSize"
      @update:page="goPage"
      @update:page-size="changePageSize"
    />
  </section>

  <CatalogImportDialog
    :open="catalogOpen"
    :continuing="catalogContinuing"
    :catalog-label="catalogPreview?.catalog_label || ''"
    :listed="catalogPreview?.listed || 0"
    :items="catalogPreview?.items || []"
    :next-cursor="catalogPreview?.next_cursor || ''"
    :truncated="catalogPreview?.truncated || false"
    :message="catalogPreview?.message || ''"
    :busy="catalogSubmitting"
    @close="closeCatalogDialog"
    @confirm="confirmCatalogDialog"
  />
  <JobDeleteDialog
    :open="Boolean(deleting)"
    :title="deleting?.title || ''"
    :count="deleting?.ids.length || 0"
    @close="deleting = null"
    @confirm="confirmDelete"
  />
</template>
