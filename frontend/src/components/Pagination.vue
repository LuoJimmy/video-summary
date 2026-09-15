<script setup lang="ts">
import { computed, ref, watch } from "vue";
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from "@lucide/vue";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { pagerItems } from "../utils/pager";

const props = withDefaults(
  defineProps<{
    total: number;
    page: number;
    pageSize: number;
    pageSizeOptions?: number[];
  }>(),
  {
    pageSizeOptions: () => [10, 20, 50, 100],
  }
);

const emit = defineEmits<{
  "update:page": [page: number];
  "update:pageSize": [pageSize: number];
}>();

const jumpDraft = ref("");

const totalPages = computed(() =>
  Math.max(1, Math.ceil(Math.max(0, props.total) / Math.max(1, props.pageSize)))
);
const items = computed(() => pagerItems(props.page, totalPages.value));
const sizeOptions = computed(() => {
  const sizes = new Set(props.pageSizeOptions);
  sizes.add(props.pageSize);
  return [...sizes].sort((a, b) => a - b);
});

watch(
  () => props.page,
  () => {
    jumpDraft.value = "";
  }
);

function goPage(next: number) {
  const clamped = Math.min(
    totalPages.value,
    Math.max(1, Math.round(Number(next) || 0))
  );
  if (clamped === props.page) return;
  emit("update:page", clamped);
}

function changePageSize(value: string | number | bigint | boolean | null) {
  const next = Number(value);
  if (!Number.isFinite(next) || next < 1 || next === props.pageSize) return;
  emit("update:pageSize", next);
}

function onJumpInput(value: string | number) {
  jumpDraft.value = String(value ?? "").replace(/\D/g, "");
}

function commitJump() {
  const raw = jumpDraft.value.trim();
  if (!raw) return;
  const next = Number(raw);
  jumpDraft.value = "";
  if (!Number.isFinite(next)) return;
  goPage(next);
}
</script>

<template>
  <div class="pager">
    <span class="msg pager-total">共 {{ total }} 条数据</span>
    <div class="pager-pages">
      <Button
        variant="outline"
        size="icon-sm"
        class="pager-btn"
        type="button"
        aria-label="上一页"
        :disabled="page <= 1"
        @click="goPage(page - 1)"
      >
        <ChevronLeft />
      </Button>
      <template v-for="(item, index) in items" :key="`${item.type}-${index}`">
        <Button
          v-if="item.type === 'page'"
          variant="outline"
          size="icon-sm"
          class="pager-btn pager-item"
          :class="{ 'is-active': item.value === page }"
          type="button"
          :aria-current="item.value === page ? 'page' : undefined"
          :aria-label="`第 ${item.value} 页`"
          @click="goPage(item.value)"
        >
          {{ item.value }}
        </Button>
        <Button
          v-else
          variant="outline"
          size="icon-sm"
          class="pager-btn pager-ellipsis"
          type="button"
          :aria-label="item.jump < page ? '向前 5 页' : '向后 5 页'"
          @click="goPage(item.jump)"
        >
          <span class="pager-ellipsis-dots" aria-hidden="true">···</span>
          <ChevronsLeft
            v-if="item.jump < page"
            class="pager-ellipsis-icon"
            aria-hidden="true"
          />
          <ChevronsRight
            v-else
            class="pager-ellipsis-icon"
            aria-hidden="true"
          />
        </Button>
      </template>
      <Button
        variant="outline"
        size="icon-sm"
        class="pager-btn"
        type="button"
        aria-label="下一页"
        :disabled="page >= totalPages"
        @click="goPage(page + 1)"
      >
        <ChevronRight />
      </Button>
    </div>
    <Select
      :model-value="String(pageSize)"
      @update:model-value="changePageSize"
    >
      <SelectTrigger class="pager-size" size="sm" aria-label="每页条数">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem
          v-for="size in sizeOptions"
          :key="size"
          :value="String(size)"
        >
          {{ size }}条/页
        </SelectItem>
      </SelectContent>
    </Select>
    <label class="pager-jump">
      <span>跳至</span>
      <Input
        :model-value="jumpDraft"
        class="pager-jump-input"
        inputmode="numeric"
        aria-label="跳至页码"
        @update:model-value="onJumpInput"
        @keydown.enter.prevent="commitJump"
        @blur="commitJump"
      />
      <span>页</span>
    </label>
  </div>
</template>
