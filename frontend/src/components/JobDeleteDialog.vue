<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const props = defineProps<{
  open: boolean;
  title: string;
  count?: number;
}>();

const emit = defineEmits<{
  close: [];
  confirm: [];
}>();

const busy = ref(false);
const itemCount = computed(() => Math.max(1, props.count || 1));

watch(
  () => props.open,
  (open) => {
    if (open) busy.value = false;
  }
);

function confirm() {
  if (busy.value) return;
  busy.value = true;
  emit("confirm");
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
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>确认删除</DialogTitle>
        <DialogDescription>
          <template v-if="itemCount > 1">
            确定删除 {{ itemCount }} 个任务？转写、总结和本地音频会一并删除，无法恢复。
          </template>
          <template v-else>
            确定删除「{{
              title || "未命名任务"
            }}」？转写、总结和本地音频会一并删除，无法恢复。
          </template>
        </DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <Button
          variant="outline"
          type="button"
          :disabled="busy"
          @click="emit('close')"
          >取消</Button
        >
        <Button
          variant="destructive"
          type="button"
          :disabled="busy"
          @click="confirm"
          >确认删除</Button
        >
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
