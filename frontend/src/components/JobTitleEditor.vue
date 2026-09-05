<script setup lang="ts">
import { nextTick, ref } from "vue";
import { Pencil } from "@lucide/vue";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const props = defineProps<{
  title: string;
  href?: string;
  heading?: boolean;
  save: (title: string) => Promise<void>;
}>();

const editing = ref(false);
const saving = ref(false);
const draft = ref("");
const input = ref<HTMLInputElement | null>(null);

const displayTitle = () =>
  props.title || (props.heading ? "任务详情" : "未命名任务");

function nativeInput() {
  const inst = input.value as unknown as
    { $el?: HTMLInputElement } | HTMLInputElement | null;
  if (!inst) return null;
  if (inst instanceof HTMLInputElement) return inst;
  return inst.$el instanceof HTMLInputElement ? inst.$el : null;
}

async function startEdit() {
  draft.value = props.title;
  editing.value = true;
  await nextTick();
  const el = nativeInput();
  el?.focus();
  el?.select();
}

async function commit() {
  if (saving.value) return;
  const next = draft.value.trim();
  if (next === (props.title || "").trim()) {
    editing.value = false;
    return;
  }
  saving.value = true;
  try {
    await props.save(next);
    editing.value = false;
  } finally {
    saving.value = false;
  }
}

function cancel() {
  if (saving.value) return;
  editing.value = false;
  draft.value = props.title;
}

function onKey(event: KeyboardEvent) {
  if (event.key === "Enter") {
    event.preventDefault();
    void commit();
  } else if (event.key === "Escape") {
    event.preventDefault();
    cancel();
  }
}
</script>

<template>
  <div class="title-editor" :class="{ heading, editing }">
    <template v-if="editing">
      <Input
        ref="input"
        v-model="draft"
        class="title-editor-input"
        maxlength="255"
        :disabled="saving"
        aria-label="任务标题"
        @keydown="onKey"
      />
      <Button type="button" :disabled="saving" @click="commit">保存</Button>
      <Button variant="outline" type="button" :disabled="saving" @click="cancel"
        >取消</Button
      >
    </template>
    <template v-else>
      <h1 v-if="heading">{{ displayTitle() }}</h1>
      <router-link v-else-if="href" :to="href"
        ><strong>{{ displayTitle() }}</strong></router-link
      >
      <strong v-else>{{ displayTitle() }}</strong>
      <Button
        variant="ghost"
        size="icon"
        class="title-edit-btn"
        type="button"
        aria-label="修改标题"
        title="修改标题"
        @click="startEdit"
      >
        <Pencil />
      </Button>
    </template>
  </div>
</template>
