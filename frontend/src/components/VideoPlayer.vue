<script setup lang="ts">
import Hls from "hls.js";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps<{ src: string }>();
const emit = defineEmits<{
  ready: [];
  error: [message: string];
}>();
const videoRef = ref<HTMLVideoElement | null>(null);
let hls: Hls | null = null;

function attach(src: string) {
  const video = videoRef.value;
  if (!video || !src) return;
  if (hls) {
    hls.destroy();
    hls = null;
  }
  if (src.includes(".m3u8") && Hls.isSupported()) {
    hls = new Hls();
    hls.loadSource(src);
    hls.attachMedia(video);
    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (data.fatal) {
        emit("error", "HLS 播放失败，可按时间轴回原站定位。");
      }
    });
    video.oncanplay = () => emit("ready");
    return;
  }
  video.src = src;
}

function onReady() {
  emit("ready");
}

function onError() {
  emit("error", "浏览器无法播放该地址，可按时间轴回原站定位。");
}

onMounted(() => attach(props.src));
watch(
  () => props.src,
  (src) => attach(src)
);

onBeforeUnmount(() => {
  hls?.destroy();
});

defineExpose({
  seek(seconds: number) {
    const video = videoRef.value;
    if (!video) return;
    video.currentTime = seconds;
    void video.play();
  },
});
</script>

<template>
  <video
    ref="videoRef"
    class="player"
    controls
    playsinline
    preload="metadata"
    @canplay="onReady"
    @error="onError"
  />
</template>
