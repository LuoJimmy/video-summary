<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { X } from "@lucide/vue";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import Pagination from "./Pagination.vue";
import type { CatalogPreviewItem } from "../api";
import { pageAfterSizeChange } from "../utils/pager";

const PAGE_SIZE_OPTIONS = [20, 50, 200];

const props = defineProps<{
  open: boolean;
  continuing?: boolean;
  catalogLabel: string;
  listed: number;
  items: CatalogPreviewItem[];
  nextCursor?: string;
  truncated?: boolean;
  message?: string;
  busy?: boolean;
}>();

const emit = defineEmits<{
  close: [];
  confirm: [items: CatalogPreviewItem[]];
}>();

const titleQuery = ref("");
const dateFrom = ref("");
const dateTo = ref("");
const page = ref(1);
const pageSize = ref(20);
const selected = ref<Set<string>>(new Set());

function catalogDate(iso?: string | null): string {
  const raw = (iso || "").trim();
  if (!raw) return "";
  const ms = Date.parse(raw.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(raw) ? raw : `${raw}Z`);
  if (!Number.isFinite(ms)) return "";
  const date = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

const filtered = computed(() => {
  const query = titleQuery.value.trim().toLowerCase();
  const from = dateFrom.value;
  const to = dateTo.value;
  return props.items.filter((item) => {
    if (query && !(item.title || "").toLowerCase().includes(query)) return false;
    const day = catalogDate(item.created_at);
    if ((from || to) && !day) return false;
    if (from && day < from) return false;
    if (to && day > to) return false;
    return true;
  });
});

const totalPages = computed(() =>
  Math.max(1, Math.ceil(filtered.value.length / Math.max(1, pageSize.value)))
);
const pageItems = computed(() => {
  const start = (page.value - 1) * pageSize.value;
  return filtered.value.slice(start, start + pageSize.value);
});
const selectedItems = computed(() =>
  props.items.filter((item) => selected.value.has(item.source_url))
);
const newCount = computed(
  () => selectedItems.value.filter((item) => !item.exists).length
);
const existingSelected = computed(
  () => selectedItems.value.filter((item) => item.exists).length
);
const filteredSelectedCount = computed(
  () => filtered.value.filter((item) => selected.value.has(item.source_url)).length
);
const headerState = computed(() => {
  if (!filtered.value.length || filteredSelectedCount.value === 0) return false;
  if (filteredSelectedCount.value === filtered.value.length) return true;
  return "indeterminate" as const;
});

watch(
  () => [props.open, props.items] as const,
  ([open]) => {
    if (!open) return;
    selected.value = new Set(props.items.map((item) => item.source_url));
    titleQuery.value = "";
    dateFrom.value = "";
    dateTo.value = "";
    page.value = 1;
    pageSize.value = 20;
  },
  { immediate: true }
);

watch([titleQuery, dateFrom, dateTo], () => {
  page.value = 1;
});

watch(filtered, () => {
  if (page.value > totalPages.value) page.value = totalPages.value;
});

function setFilteredSelect(checked: boolean | "indeterminate") {
  const next = new Set(selected.value);
  for (const item of filtered.value) {
    if (checked === true) next.add(item.source_url);
    else next.delete(item.source_url);
  }
  selected.value = next;
}

function setRowSelected(url: string, checked: boolean | "indeterminate") {
  const next = new Set(selected.value);
  if (checked === true) next.add(url);
  else next.delete(url);
  selected.value = next;
}

function removeSelected(url: string) {
  const next = new Set(selected.value);
  next.delete(url);
  selected.value = next;
}

function goPage(next: number) {
  if (next < 1 || next > totalPages.value || next === page.value) return;
  page.value = next;
}

function changePageSize(next: number) {
  if (next === pageSize.value) return;
  page.value = pageAfterSizeChange(page.value, pageSize.value, next);
  pageSize.value = next;
}

function confirm() {
  if (props.busy || newCount.value <= 0) return;
  emit(
    "confirm",
    selectedItems.value.filter((item) => !item.exists)
  );
}
</script>

<template>
  <Dialog
    :open="open"
    @update:open="
      (next: boolean) => {
        if (!next) emit('close');
      }
    "
  >
    <DialogContent class="catalog-import-dialog sm:max-w-5xl lg:max-w-6xl">
      <DialogHeader>
        <DialogTitle>
          {{ continuing ? "继续拉取下一批" : `确认拉取${catalogLabel}` }}
        </DialogTitle>
        <DialogDescription>
          本批 {{ listed }} 条。已存在的创建时会跳过。
          <template v-if="nextCursor">
            确认后若还有后续，会在创建区提示继续拉取。
          </template>
          <template v-if="truncated && message">
            {{ message }}
          </template>
        </DialogDescription>
      </DialogHeader>

      <div class="catalog-import-filters">
        <div class="field field-title">
          <Label class="sr-only" for="catalog-title-filter">标题</Label>
          <Input
            id="catalog-title-filter"
            v-model="titleQuery"
            placeholder="标题"
            aria-label="按标题筛选"
          />
        </div>
        <div class="field field-dates">
          <div class="date-range">
            <Input v-model="dateFrom" type="date" aria-label="开始日期" />
            <span class="date-range-sep">至</span>
            <Input v-model="dateTo" type="date" aria-label="结束日期" />
          </div>
        </div>
      </div>

      <div class="catalog-import-table-wrap">
        <table class="catalog-import-table">
          <thead>
            <tr>
              <th class="catalog-import-check">
                <Checkbox
                  :model-value="headerState"
                  :disabled="!filtered.length"
                  aria-label="全选筛选结果"
                  @update:model-value="setFilteredSelect"
                />
              </th>
              <th>标题</th>
              <th class="catalog-import-date">日期</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!pageItems.length">
              <td colspan="3" class="msg">没有符合筛选的视频</td>
            </tr>
            <tr v-for="item in pageItems" :key="item.source_url">
              <td class="catalog-import-check">
                <Checkbox
                  :model-value="selected.has(item.source_url)"
                  :aria-label="`选择 ${item.title || '未命名'}`"
                  @update:model-value="
                    (value: boolean | 'indeterminate') =>
                      setRowSelected(item.source_url, value)
                  "
                />
              </td>
              <td>
                <div class="catalog-import-title-cell">
                  <span
                    class="catalog-import-title"
                    :title="item.title || '未命名'"
                    >{{ item.title || "未命名" }}</span
                  >
                  <Badge
                    v-if="item.exists"
                    variant="outline"
                    class="catalog-exists"
                    >已存在</Badge
                  >
                </div>
              </td>
              <td class="catalog-import-date">
                {{ catalogDate(item.created_at) || "—" }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <Pagination
        :total="filtered.length"
        :page="page"
        :page-size="pageSize"
        :page-size-options="PAGE_SIZE_OPTIONS"
        @update:page="goPage"
        @update:page-size="changePageSize"
      />

      <div v-if="selectedItems.length" class="catalog-selected">
        <div class="catalog-selected-list">
          <Badge
            v-for="item in selectedItems"
            :key="item.source_url"
            variant="secondary"
            class="catalog-selected-chip"
            :title="item.title || item.source_url"
          >
            <span class="catalog-selected-text">{{ item.title || "未命名" }}</span>
            <button
              type="button"
              class="catalog-selected-remove"
              :aria-label="`移除 ${item.title || '未命名'}`"
              @click="removeSelected(item.source_url)"
            >
              <X aria-hidden="true" />
            </button>
          </Badge>
        </div>
      </div>

      <p class="msg">
        已选 {{ selectedItems.length }} 条，将新建 {{ newCount }} 个任务，跳过
        {{ existingSelected }} 条已存在。
      </p>

      <DialogFooter>
        <Button
          variant="outline"
          type="button"
          :disabled="busy"
          @click="emit('close')"
          >取消</Button
        >
        <Button
          type="button"
          :disabled="busy || newCount <= 0"
          @click="confirm"
          >创建本批</Button
        >
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
