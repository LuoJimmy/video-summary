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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const props = defineProps<{
  open: boolean;
  title: string;
  author: string;
  busy?: boolean;
}>();

const emit = defineEmits<{
  close: [];
  save: [payload: { title: string; author: string }];
}>();

const titleDraft = ref("");
const authorDraft = ref("");

watch(
  () => props.open,
  (open) => {
    if (!open) return;
    titleDraft.value = props.title;
    authorDraft.value = props.author;
  }
);

function save() {
  if (props.busy) return;
  emit("save", {
    title: titleDraft.value.trim(),
    author: authorDraft.value.trim(),
  });
}

function close() {
  if (props.busy) return;
  emit("close");
}
</script>

<template>
  <Dialog
    :open="open"
    @update:open="
      (next: boolean) => {
        if (!next) close();
      }
    "
  >
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>编辑任务</DialogTitle>
        <DialogDescription>修改任务标题和视频作者。</DialogDescription>
      </DialogHeader>
      <div class="field">
        <Label>标题</Label>
        <Input
          v-model="titleDraft"
          maxlength="255"
          aria-label="任务标题"
          :disabled="busy"
          @keydown.enter="save"
        />
      </div>
      <div class="field">
        <Label>视频作者（可选）</Label>
        <Input
          v-model="authorDraft"
          maxlength="120"
          aria-label="任务作者"
          :disabled="busy"
          @keydown.enter="save"
        />
      </div>
      <DialogFooter>
        <Button variant="outline" type="button" :disabled="busy" @click="close"
          >取消</Button
        >
        <Button type="button" :disabled="busy" @click="save">保存</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
