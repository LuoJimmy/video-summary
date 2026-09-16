<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { useRoute, useRouter } from "vue-router";
import { useWindowScroll } from "@vueuse/core";
import { ChevronLeft, ChevronUp } from "@lucide/vue";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { api, type Job } from "../api";
import JobDeleteDialog from "../components/JobDeleteDialog.vue";
import JobTitleEditor from "../components/JobTitleEditor.vue";
import VideoPlayer from "../components/VideoPlayer.vue";
import DocumentPreview from "../components/DocumentPreview.vue";
import {
  formatOverviewDocument,
  overviewIsStructured,
  setOverviewHighlight,
} from "../utils/overview";
import { highlightFromPack, type DomainPack } from "../utils/domain";
import {
  STAGE_TIME_LABELS,
  formatDateTime,
  formatDuration,
  formatTimestamp,
  isJobActive,
  jobElapsedSeconds,
  statusLabel,
} from "../utils/time";
import { toast } from "vue-sonner";
import { documentPreviewKind, isDocumentSource, locatorPage, needsMediaOverrideError, publicSourceUrl, sourceTypeLabel } from "../utils/source";

const route = useRoute();
const router = useRouter();
const fromKnowledge = computed(() => {
  const raw = route.query.from;
  return (Array.isArray(raw) ? raw[0] : raw) === "knowledge";
});
const backTo = computed(() => (fromKnowledge.value ? "/knowledge" : "/"));
const backLabel = computed(() =>
  fromKnowledge.value ? "返回知识库" : "返回任务列表"
);
const job = ref<Job | null>(null);
const player = ref<{ seek: (n: number) => void } | null>(null);
const askingDelete = ref(false);
const mediaOverride = ref("");
const playSrc = ref("");
const playHint = ref("");
const nowMs = ref(Date.now());
let timer: number | undefined;
let clock: number | undefined;

const hasTranscript = computed(() => Boolean(job.value?.transcript.length));
const isDocument = computed(() =>
  isDocumentSource(job.value?.source_type)
);
const overviewHtml = computed(() =>
  formatOverviewDocument(job.value?.summary?.overview || "", {
    seekableClocks: !isDocument.value,
  })
);
const showChapterBlocks = computed(() => {
  if (isDocument.value) return true;
  return !overviewIsStructured(job.value?.summary?.overview || "");
});
const highlightedSeg = ref<number | null>(null);
const previewPage = ref<number | null>(null);
const previewSeg = ref<number | null>(null);
const showTranscript = ref(true);
const domainPresets = ref<DomainPack[]>([]);
const jobBusy = computed(() =>
  Boolean(job.value && isJobActive(job.value.status))
);
const playerSrc = computed(() => {
  if (isDocument.value) return "";
  return playSrc.value || playbackSrcFromJob(job.value);
});
const documentFileSrc = computed(() => {
  if (!job.value || !isDocument.value) return "";
  return `/api/jobs/${job.value.id}/file`;
});
const previewKind = computed(() =>
  documentPreviewKind(
    job.value?.source_type,
    job.value?.source_url,
    job.value?.media_url
  )
);
const originalHttpUrl = computed(() => publicSourceUrl(job.value?.source_url));
const elapsedLabel = computed(() => {
  if (!job.value || !jobBusy.value) return "";
  return formatDuration(jobElapsedSeconds(job.value, nowMs.value));
});
const sourceMeta = computed(() => {
  if (!job.value) return "";
  return [
    formatDateTime(job.value.source_created_at),
    job.value.author?.trim(),
    publicSourceUrl(job.value.source_url),
  ]
    .filter(Boolean)
    .join(" · ");
});
const canRetrySteps = computed(() => {
  const status = job.value?.status;
  return status === "done" || status === "failed" || status === "cancelled";
});
const canReuseTranscript = computed(() =>
  Boolean(hasTranscript.value && canRetrySteps.value)
);
const showMediaOverride = computed(
  () =>
    Boolean(mediaOverride.value.trim()) ||
    needsMediaOverrideError(job.value?.error)
);
const timingRows = computed(() => {
  const timing = job.value?.timing || {};
  const keys = [
    "resolving",
    "extracting",
    "extracting_text",
    "installing_plugin",
    "transcribing",
    "proofreading",
    "summarizing",
    "total",
  ];
  return keys
    .filter((key) => typeof timing[key] === "number")
    .map((key) => ({
      key,
      label: STAGE_TIME_LABELS[key] || key,
      seconds: timing[key],
    }));
});
const { y: windowScrollY } = useWindowScroll();
const showBackToTop = computed(
  () => Boolean(job.value) && windowScrollY.value > 240
);

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function applyJobHighlight(current: Job | null) {
  if (!current) return;
  const domain = current.domain_id || "a-share";
  const pack =
    domainPresets.value.find((item) => item.id === domain) ||
    domainPresets.value.find((item) => item.id === "a-share");
  setOverviewHighlight(highlightFromPack(pack));
}

function isDirectPlayable(url: string) {
  const text = (url || "").trim();
  if (!text) return false;
  if (text.startsWith("/api/")) return true;
  const lower = text.toLowerCase();
  if (lower.includes(".m3u8")) return true;
  if (!/^https?:\/\//i.test(text)) return false;
  const path = text.split("?")[0];
  return /\.(mp4|webm|ogg|ogv|mov|m4v)$/i.test(path);
}

function playbackSrcFromJob(current: Job | null) {
  if (!current) return "";
  const raw = current.media_url || "";
  if (isDirectPlayable(raw)) return raw;
  if (raw) return `/api/jobs/${current.id}/play`;
  return "";
}

function assignPlaySrc(next: string, hint = "") {
  if (playSrc.value === next) return;
  playSrc.value = next;
  playHint.value = hint;
}

async function load() {
  job.value = await api.job(String(route.params.id));
  applyJobHighlight(job.value);
}

async function refreshPlayback() {
  if (!job.value || isDocument.value) {
    assignPlaySrc("");
    return;
  }
  if (jobBusy.value) {
    const next = playbackSrcFromJob(job.value);
    assignPlaySrc(
      next,
      next.startsWith("/api/") ? "首次播放会在本机转封装，请稍候。" : ""
    );
    return;
  }
  if (!job.value.media_url && !job.value.source_url.startsWith("http")) {
    assignPlaySrc("");
    return;
  }
  try {
    const media = await api.jobMedia(job.value.id);
    const next = media.url || playbackSrcFromJob(job.value);
    const hint =
      media.message ||
      (next.startsWith("/api/") ? "首次播放会在本机转封装，请稍候。" : "");
    assignPlaySrc(next, hint);
  } catch (err) {
    assignPlaySrc(
      playbackSrcFromJob(job.value) || `/api/jobs/${job.value.id}/play`,
      err instanceof Error ? err.message : "刷新播放地址失败"
    );
  }
}

async function loadAndSeek() {
  playSrc.value = "";
  playHint.value = "";
  await load();
  await refreshPlayback();
  await nextTick();
  seekFromQuery();
}

function placeLabel(item: {
  locator?: string;
  start?: number;
  start_segment?: number;
  id?: number;
}) {
  if (item.locator) return item.locator;
  if (isDocument.value) {
    const segId = item.start_segment ?? item.id;
    const seg = job.value?.transcript.find((row) => row.id === segId);
    return seg?.locator || "定位";
  }
  return formatTimestamp(item.start || 0);
}

function goTo(item: {
  start?: number;
  start_segment?: number;
  id?: number;
  locator?: string;
}) {
  if (isDocument.value) {
    const segId = item.start_segment ?? item.id;
    if (segId === undefined || segId === null) return;
    highlightedSeg.value = Number(segId);
    previewSeg.value = Number(segId);
    const loc =
      item.locator ||
      job.value?.transcript.find((row) => row.id === Number(segId))?.locator;
    previewPage.value = locatorPage(loc);
    document.getElementById("doc-preview")?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    window.setTimeout(() => {
      if (highlightedSeg.value === Number(segId)) highlightedSeg.value = null;
    }, 1600);
    return;
  }
  player.value?.seek(item.start || 0);
}

function onOverviewClick(event: MouseEvent) {
  const target = event.target;
  if (!(target instanceof Element)) return;
  const btn = target.closest("[data-seek]");
  if (!(btn instanceof HTMLElement)) return;
  const start = Number(btn.getAttribute("data-seek"));
  if (!Number.isFinite(start) || start < 0) return;
  event.preventDefault();
  goTo({ start });
}

function seekFromQuery() {
  const segRaw = route.query.seg;
  if (segRaw != null && String(segRaw)) {
    const value = Number(Array.isArray(segRaw) ? segRaw[0] : segRaw);
    if (Number.isFinite(value)) {
      goTo({ start: 0, id: value, start_segment: value });
      return;
    }
  }
  const raw = route.query.t;
  const value = Number(Array.isArray(raw) ? raw[0] : raw);
  if (!Number.isFinite(value) || value < 0) return;
  goTo({ start: value });
}

function onPlayerReady() {
  if (playHint.value.startsWith("首次播放")) playHint.value = "";
}

function onPlayerError(message: string) {
  playHint.value = message;
}

watch(
  () => job.value?.id,
  (id) => {
    mediaOverride.value = id ? job.value?.media_url_override || "" : "";
  }
);

async function retry() {
  if (!job.value) return;
  job.value = await api.retryJob(
    job.value.id,
    showMediaOverride.value
      ? { media_url_override: mediaOverride.value }
      : undefined
  );
}

async function cancel() {
  if (!job.value) return;
  job.value = await api.cancelJob(job.value.id);
}

async function resummarize() {
  if (!job.value) return;
  job.value = await api.resummarizeJob(job.value.id);
}

async function proofread() {
  if (!job.value) return;
  job.value = await api.proofreadJob(job.value.id);
}

async function retranscribe() {
  if (!job.value) return;
  job.value = await api.retranscribeJob(job.value.id);
}

async function rename(nextTitle: string) {
  if (!job.value) return;
  try {
    job.value = await api.updateJob(job.value.id, { title: nextTitle });
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "修改标题失败");
    throw err;
  }
}

async function confirmDelete() {
  if (!job.value) return;
  try {
    await api.deleteJob(job.value.id);
    askingDelete.value = false;
    await router.push(backTo.value);
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "删除失败");
    askingDelete.value = false;
  }
}

onMounted(async () => {
  try {
    const settings = await api.settings();
    showTranscript.value = settings.show_transcript !== false;
    domainPresets.value = settings.domain_presets || [];
    applyJobHighlight(job.value);
  } catch {
    showTranscript.value = true;
  }
  await loadAndSeek();
  timer = window.setInterval(async () => {
    if (jobBusy.value) {
      await load();
      await refreshPlayback();
    }
  }, 2000);
});

watch(
  jobBusy,
  (active) => {
    if (active) {
      nowMs.value = Date.now();
      if (clock === undefined) {
        clock = window.setInterval(() => {
          nowMs.value = Date.now();
        }, 1000);
      }
      return;
    }
    if (clock !== undefined) {
      window.clearInterval(clock);
      clock = undefined;
    }
  },
  { immediate: true }
);

watch(() => route.params.id, loadAndSeek);
watch(
  () => route.query.t,
  () => {
    if (job.value) seekFromQuery();
  }
);
watch(
  () => route.query.seg,
  () => {
    if (job.value) seekFromQuery();
  }
);

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer);
  if (clock !== undefined) window.clearInterval(clock);
});
</script>

<template>
  <div class="page-title">
    <Button variant="ghost" size="icon" class="icon-btn" as-child>
      <router-link :to="backTo" :aria-label="backLabel" :title="backLabel">
        <ChevronLeft />
      </router-link>
    </Button>
    <JobTitleEditor v-if="job" heading :title="job.title" :save="rename" />
    <h1 v-else>任务详情</h1>
  </div>
  <div v-if="job">
    <p class="sub">{{ sourceMeta }}</p>
    <section class="card">
      <div class="row">
        <Badge
          variant="outline"
          class="tag"
          :class="{
            ok: job.status === 'done',
            bad: job.status === 'failed',
            warn: jobBusy,
          }"
        >
          {{ statusLabel(job.status, job.stage) }}
        </Badge>
        <Badge variant="secondary">{{
          sourceTypeLabel(job.source_type)
        }}</Badge>
        <Button
          v-if="jobBusy"
          variant="destructive"
          type="button"
          @click="cancel"
          >取消任务</Button
        >
        <Button v-if="canRetrySteps" type="button" @click="retranscribe">{{
          isDocument ? "重新提取" : "重新转写"
        }}</Button>
        <Button
          v-if="canReuseTranscript && !isDocument"
          variant="outline"
          type="button"
          @click="proofread"
          >重新校对转写</Button
        >
        <Button
          v-if="canReuseTranscript"
          variant="outline"
          type="button"
          @click="resummarize"
          >{{ job.summary ? "重新总结" : "生成总结" }}</Button
        >
        <Button
          v-if="job.status === 'failed' || job.status === 'cancelled'"
          variant="outline"
          type="button"
          @click="retry"
          >{{ hasTranscript ? "从头重试" : "重试" }}</Button
        >
        <Button
          variant="outline"
          class="text-destructive"
          type="button"
          @click="askingDelete = true"
          >删除</Button
        >
      </div>
      <div class="progress-row">
        <Progress :model-value="job.progress" class="h-1.5" />
        <strong class="progress-pct">{{ job.progress }}%</strong>
        <strong v-if="elapsedLabel" class="progress-elapsed"
          >已用时 {{ elapsedLabel }}</strong
        >
      </div>
      <p
        v-if="
          timingRows.length &&
          (job.status === 'done' || job.status === 'failed')
        "
        class="timing"
      >
        <span v-for="item in timingRows" :key="item.key"
          >{{ item.label }} {{ formatDuration(item.seconds) }}</span
        >
      </p>
      <p v-if="job.error" class="error">{{ job.error }}</p>
      <div v-if="showMediaOverride" class="field media-override">
        <Label>媒体地址覆盖（m3u8/mp4）</Label>
        <Input
          v-model="mediaOverride"
          placeholder="登录后从 Network 复制的流地址"
        />
      </div>
    </section>

    <section v-if="playerSrc" class="card">
      <VideoPlayer
        v-if="playerSrc"
        ref="player"
        :src="playerSrc"
        @ready="onPlayerReady"
        @error="onPlayerError"
      />
      <p
        v-if="playHint"
        :class="playHint.startsWith('首次播放') ? 'msg' : 'error'"
      >
        {{ playHint }}
      </p>
      <p class="msg">
        若浏览器因跨域无法播放，仍可按时间轴回原站定位。小鹅通等带签名的地址会在打开时自动刷新。
      </p>
    </section>

    <section
      v-if="isDocument && documentFileSrc"
      id="doc-preview"
      class="card"
    >
      <div class="row mb-3">
        <strong>原件预览</strong>
        <Button v-if="originalHttpUrl" variant="outline" size="sm" as-child>
          <a :href="originalHttpUrl" target="_blank" rel="noreferrer"
            >打开原文</a
          >
        </Button>
        <Button variant="outline" size="sm" as-child>
          <a
            :href="`${documentFileSrc}?raw=1`"
            target="_blank"
            rel="noreferrer"
            >下载原文件</a
          >
        </Button>
      </div>
      <DocumentPreview
        :src="documentFileSrc"
        :kind="previewKind"
        :page="previewPage"
        :segment-id="previewSeg"
      />
      <p class="msg">
        点击章节、要点或正文标签可定位对应段落；PDF 会跳到对应页。
      </p>
    </section>

    <section v-if="job.summary" class="card">
      <h2>{{ job.summary.title }}</h2>
      <div class="overview" @click="onOverviewClick" v-html="overviewHtml" />
      <template v-if="showChapterBlocks">
        <div
          v-for="(chapter, index) in job.summary.chapters"
          :key="index"
          class="chapter-block"
        >
          <p class="text-line">
            <Button
              class="time-btn"
              variant="secondary"
              size="sm"
              type="button"
              @click="goTo(chapter)"
              >{{ placeLabel(chapter) }}</Button
            >
            <strong>{{ chapter.title }}</strong>
          </p>
          <ul>
            <li v-for="(bullet, bIndex) in chapter.bullets" :key="bIndex">
              {{ bullet }}
            </li>
          </ul>
        </div>
      </template>
      <div v-if="job.summary.key_points.length" class="chapter-block">
        <h3>关键定位</h3>
        <p
          v-for="(point, index) in job.summary.key_points"
          :key="index"
          class="text-line"
        >
          <Button
            class="time-btn"
            variant="secondary"
            size="sm"
            type="button"
            @click="goTo(point)"
            >{{ placeLabel(point) }}</Button
          >
          <span>{{ point.text }}</span>
        </p>
      </div>
    </section>

    <section v-if="showTranscript && job.transcript.length" class="card">
      <h3>{{ isDocument ? "正文" : "转写" }}</h3>
      <p
        v-for="seg in job.transcript"
        :id="`seg-${seg.id}`"
        :key="seg.id"
        class="text-line"
        :class="{ 'seg-active': highlightedSeg === seg.id }"
      >
        <Button
          class="time-btn"
          variant="secondary"
          size="sm"
          type="button"
          @click="goTo(seg)"
          >{{ placeLabel(seg) }}</Button
        >
        <span>{{ seg.text }}</span>
      </p>
    </section>
  </div>

  <JobDeleteDialog
    :open="askingDelete"
    :title="job?.title || ''"
    @close="askingDelete = false"
    @confirm="confirmDelete"
  />

  <Teleport to="body">
    <Button
      v-if="showBackToTop"
      class="back-to-top"
      variant="secondary"
      size="icon-lg"
      type="button"
      aria-label="回到顶部"
      title="回到顶部"
      @click="scrollToTop"
    >
      <ChevronUp />
    </Button>
  </Teleport>
</template>
