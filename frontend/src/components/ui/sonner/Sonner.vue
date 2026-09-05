<script lang="ts" setup>
import type { ToasterProps } from "vue-sonner";
import { Toaster as Sonner } from "vue-sonner";

const props = withDefaults(defineProps<ToasterProps>(), {
  position: "top-center",
  richColors: true,
  closeButton: true,
  duration: 4000,
});
</script>

<template>
  <Sonner
    class="toaster group"
    v-bind="props"
    :style="{
      '--normal-bg': 'var(--panel)',
      '--normal-text': 'var(--text)',
      '--normal-border': 'var(--line)',
      '--success-bg': 'var(--panel)',
      '--success-border': 'var(--line)',
      '--success-text': 'var(--ok)',
      '--error-bg': 'var(--panel)',
      '--error-border': 'var(--line)',
      '--error-text': 'var(--bad)',
      '--info-bg': 'var(--panel)',
      '--info-border': 'var(--line)',
      '--info-text': 'var(--accent)',
    }"
  />
</template>
