<script setup lang="ts">
import { ref, watch } from "vue";
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
}>();

const emit = defineEmits<{
  close: [];
  confirm: [];
}>();

const busy = ref(false);

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
          确定删除「{{
            title || "未命名任务"
          }}」？转写、总结和本地音频会一并删除，无法恢复。
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
