<script setup lang="ts">
import { ref, watch } from "vue";
import { ChevronUp, Folder, Loader2, X } from "@lucide/vue";
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
import { api, apiErrorMessage, type LocalEntry, type LocalPick } from "../api";
import { pageAfterSizeChange } from "../utils/pager";
import { formatFileSize } from "../utils/size";
import Pagination from "./Pagination.vue";
import { toast } from "vue-sonner";

const PAGE_SIZE_OPTIONS = [20, 50, 100, 200];

const props = withDefaults(
  defineProps<{
    open: boolean;
    root: string;
    selected: LocalPick[];
    limit: number;
    scanLimit?: number;
  }>(),
  { scanLimit: 1000 }
);

const emit = defineEmits<{
  close: [];
  confirm: [items: LocalPick[]];
}>();

const currentPath = ref("");
const parentPath = ref("");
const queryDraft = ref("");
const appliedQuery = ref("");
const entries = ref<LocalEntry[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const loading = ref(false);
const error = ref("");
const expanding = ref("");
const picked = ref<LocalPick[]>([]);
const pickedDirs = ref<Set<string>>(new Set());
const truncated = ref(false);

async function load(target: string, nextPage: number) {
  loading.value = true;
  error.value = "";
  try {
    const payload = await api.localEntries(target, {
      query: appliedQuery.value,
      page: nextPage,
      pageSize: pageSize.value,
    });
    currentPath.value = payload.path;
    parentPath.value = payload.parent;
    entries.value = payload.entries;
    total.value = payload.total;
    page.value = payload.page;
    pageSize.value = payload.page_size;
    truncated.value = payload.truncated;
  } catch (err) {
    entries.value = [];
    total.value = 0;
    error.value = apiErrorMessage(err, "读取挂载目录失败");
  } finally {
    loading.value = false;
  }
}

function reload() {
  void load(currentPath.value || props.root, page.value);
}

function enterDir(entry: LocalEntry) {
  queryDraft.value = "";
  appliedQuery.value = "";
  page.value = 1;
  void load(entry.path, 1);
}

function goParent() {
  if (!parentPath.value) return;
  queryDraft.value = "";
  appliedQuery.value = "";
  page.value = 1;
  void load(parentPath.value, 1);
}

function runSearch() {
  appliedQuery.value = queryDraft.value.trim();
  page.value = 1;
  void load(currentPath.value || props.root, 1);
}

function clearSearch() {
  queryDraft.value = "";
  if (!appliedQuery.value) return;
  appliedQuery.value = "";
  page.value = 1;
  void load(currentPath.value || props.root, 1);
}

function goPage(next: number) {
  void load(currentPath.value, next);
}

function changePageSize(next: number) {
  if (next === pageSize.value) return;
  const target = pageAfterSizeChange(page.value, pageSize.value, next);
  pageSize.value = next;
  void load(currentPath.value, target);
}

function isPicked(entry: LocalEntry) {
  return picked.value.some((item) => item.path === entry.path);
}

function addPicked(items: LocalPick[]) {
  const seen = new Set(picked.value.map((item) => item.path));
  const added = items.filter((item) => {
    if (seen.has(item.path)) return false;
    seen.add(item.path);
    return true;
  });
  if (added.length) picked.value = [...picked.value, ...added];
  return added.length;
}

function togglePick(entry: LocalEntry) {
  if (isPicked(entry)) {
    picked.value = picked.value.filter((item) => item.path !== entry.path);
    return;
  }
  if (picked.value.length >= props.limit) {
    toast.error(`一次最多选 ${props.limit} 个文件`);
    return;
  }
  addPicked([{ path: entry.path, name: entry.name }]);
}

function isDirPicked(entry: LocalEntry) {
  return pickedDirs.value.has(entry.path);
}

async function toggleDir(entry: LocalEntry) {
  if (isDirPicked(entry)) {
    removeDir(entry.path);
    return;
  }
  const room = props.limit - picked.value.length;
  if (room <= 0) {
    toast.error(`一次最多选 ${props.limit} 个文件`);
    return;
  }
  expanding.value = entry.path;
  try {
    const payload = await api.localEntries(entry.path, { recursive: true });
    const found = payload.entries.filter((item) => item.kind === "file");
    if (!found.length) {
      toast.error("这个文件夹里没有可处理的文件");
      return;
    }
    const added = addPicked(
      found.slice(0, room).map((item) => ({ path: item.path, name: item.name }))
    );
    pickedDirs.value = new Set([...pickedDirs.value, entry.path]);
    if (payload.truncated) {
      toast.warning(`该文件夹文件较多，只加入前 ${props.scanLimit} 个`);
      return;
    }
    toast.success(`已加入 ${added} 个文件`);
  } catch (err) {
    toast.error(apiErrorMessage(err, "读取文件夹失败"));
  } finally {
    expanding.value = "";
  }
}

function removeDir(dirPath: string) {
  const prefix = `${dirPath}/`;
  picked.value = picked.value.filter((item) => !item.path.startsWith(prefix));
  const next = new Set(pickedDirs.value);
  next.delete(dirPath);
  pickedDirs.value = next;
}

function removePicked(path: string) {
  picked.value = picked.value.filter((item) => item.path !== path);
}

function confirm() {
  if (!picked.value.length) return;
  emit("confirm", picked.value);
}

watch(
  () => props.open,
  (open) => {
    if (!open) return;
    picked.value = [...props.selected];
    pickedDirs.value = new Set();
    queryDraft.value = "";
    appliedQuery.value = "";
    page.value = 1;
    pageSize.value = 50;
    truncated.value = false;
    currentPath.value = "";
    parentPath.value = "";
    void load(props.root || "", 1);
  },
  { immediate: true }
);
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
    <DialogContent class="local-picker-dialog sm:max-w-4xl">
      <DialogHeader>
        <DialogTitle>从挂载目录选择</DialogTitle>
        <DialogDescription>
          浏览容器内
          {{ root || "MEDIA_DIR" }}
          的内容。勾选文件即选中，勾选文件夹会把其中的视频 / 音频 /
          文档一次加入；一次最多
          {{ limit }} 个，单个文件夹最多扫 {{ scanLimit }} 个。
        </DialogDescription>
      </DialogHeader>

      <div class="local-picker-bar">
        <Button
          variant="outline"
          size="sm"
          type="button"
          :disabled="!parentPath || loading"
          @click="goParent"
        >
          <ChevronUp aria-hidden="true" />上一级
        </Button>
        <Button
          variant="outline"
          size="sm"
          type="button"
          :disabled="loading"
          @click="reload"
          >刷新</Button
        >
        <span class="local-path" :title="currentPath">{{
          currentPath || "…"
        }}</span>
      </div>

      <div class="local-picker-search">
        <div class="field">
          <Input
            v-model="queryDraft"
            placeholder="按名称搜索当前文件夹"
            aria-label="搜索当前文件夹"
            @keydown.enter.prevent="runSearch"
          />
        </div>
        <Button variant="outline" type="button" @click="runSearch">搜索</Button>
        <Button
          v-if="appliedQuery"
          variant="ghost"
          type="button"
          @click="clearSearch"
          >清除</Button
        >
      </div>

      <div class="local-picker-table-wrap">
        <table class="local-picker-table">
          <thead>
            <tr>
              <th class="local-picker-check">
                <span class="sr-only">选择</span>
              </th>
              <th>名称</th>
              <th class="local-picker-size">大小</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="error">
              <td colspan="3" class="msg">{{ error }}</td>
            </tr>
            <tr v-else-if="loading">
              <td colspan="3" class="msg">正在读取…</td>
            </tr>
            <tr v-else-if="!entries.length">
              <td colspan="3" class="msg">
                {{
                  appliedQuery
                    ? "没有匹配的文件或文件夹。"
                    : "这里没有可处理的视频 / 音频 / 文档。"
                }}
              </td>
            </tr>
            <tr v-for="entry in entries" :key="entry.path">
              <td class="local-picker-check">
                <Loader2
                  v-if="entry.kind === 'dir' && expanding === entry.path"
                  class="size-4 animate-spin"
                />
                <Checkbox
                  v-else
                  :model-value="
                    entry.kind === 'dir' ? isDirPicked(entry) : isPicked(entry)
                  "
                  :aria-label="
                    entry.kind === 'dir'
                      ? `选择文件夹 ${entry.name}`
                      : `选择 ${entry.name}`
                  "
                  @update:model-value="
                    entry.kind === 'dir' ? toggleDir(entry) : togglePick(entry)
                  "
                />
              </td>
              <td>
                <button
                  v-if="entry.kind === 'dir'"
                  type="button"
                  class="local-picker-dir"
                  :title="entry.name"
                  @click="enterDir(entry)"
                >
                  <Folder aria-hidden="true" />
                  <span class="file-name-text">{{ entry.name }}</span>
                </button>
                <button
                  v-else
                  type="button"
                  class="local-picker-file"
                  :title="entry.path"
                  @click="togglePick(entry)"
                >
                  <span class="file-name-text">{{ entry.name }}</span>
                </button>
              </td>
              <td class="local-picker-size">
                {{
                  entry.kind === "dir" ? "文件夹" : formatFileSize(entry.size)
                }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <Pagination
        :total="total"
        :page="page"
        :page-size="pageSize"
        :page-size-options="PAGE_SIZE_OPTIONS"
        @update:page="goPage"
        @update:page-size="changePageSize"
      />
      <p v-if="truncated" class="msg">
        该文件夹文件较多，只加入了前 {{ scanLimit }} 个。
      </p>

      <div v-if="picked.length" class="local-picker-selected">
        <Badge
          v-for="item in picked"
          :key="item.path"
          variant="secondary"
          class="local-picker-chip"
          :title="item.path"
        >
          <span class="file-name-text">{{ item.name }}</span>
          <button
            type="button"
            class="catalog-selected-remove"
            :aria-label="`移除 ${item.name}`"
            @click="removePicked(item.path)"
          >
            <X aria-hidden="true" />
          </button>
        </Badge>
      </div>
      <p class="msg">
        已选 {{ picked.length }} / {{ limit }} 个文件{{
          picked.length ? "，确认后加入创建区。" : "。"
        }}
      </p>

      <DialogFooter>
        <Button variant="outline" type="button" @click="emit('close')"
          >取消</Button
        >
        <Button type="button" :disabled="!picked.length" @click="confirm"
          >确定</Button
        >
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
