<script setup lang="ts">
import { computed, ref, watch } from "vue";

const props = defineProps<{
  src: string;
  kind: string;
  page?: number | null;
  segmentId?: number | null;
}>();

const iframeRef = ref<HTMLIFrameElement | null>(null);
const iframeSrc = computed(() => {
  if (props.kind === "pdf" && props.page) {
    return `${props.src}#page=${props.page}`;
  }
  return props.src;
});
const iframeBind = computed(() =>
  props.kind === "pdf"
    ? { src: iframeSrc.value, title: "文档预览" }
    : {
        src: iframeSrc.value,
        title: "文档预览",
        sandbox: "allow-popups allow-popups-to-escape-sandbox allow-same-origin",
      }
);

function scrollPreviewSegment(segmentId: number | null | undefined) {
  if (segmentId == null || props.kind === "pdf") return;
  const doc = iframeRef.value?.contentDocument;
  doc?.getElementById(`seg-${segmentId}`)?.scrollIntoView({
    behavior: "smooth",
    block: "center",
  });
}

watch(
  () => props.segmentId,
  (value) => {
    scrollPreviewSegment(value);
  }
);
</script>

<template>
  <iframe
    :key="iframeSrc"
    ref="iframeRef"
    class="doc-preview"
    v-bind="iframeBind"
    @load="scrollPreviewSegment(segmentId)"
  />
</template>
