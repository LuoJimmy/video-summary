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
import { Progress } from "@/components/ui/progress";
import { api, type Job } from "../api";
import JobDeleteDialog from "../components/JobDeleteDialog.vue";
import JobTitleEditor from "../components/JobTitleEditor.vue";
import VideoPlayer from "../components/VideoPlayer.vue";
import {
  formatOverviewDocument,
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

const route = useRoute();
const router = useRouter();
const job = ref<Job | null>(null);
const player = ref<{ seek: (n: number) => void } | null>(null);
const askingDelete = ref(false);
const playSrc = ref("");
const playHint = ref("");
const nowMs = ref(Date.now());
let timer: number | undefined;
let clock: number | undefined;

const overviewHtml = computed(() =>
  formatOverviewDocument(job.value?.summary?.overview || "")
);
const hasTranscript = computed(() => Boolean(job.value?.transcript.length));
const showTranscript = ref(true);
const domainPresets = ref<DomainPack[]>([]);
const jobBusy = computed(() =>
  Boolean(job.value && isJobActive(job.value.status))
);
const playerSrc = computed(
  () => playSrc.value || playbackSrcFromJob(job.value)
);
const elapsedLabel = computed(() => {
  if (!job.value || !jobBusy.value) return "";
  return formatDuration(jobElapsedSeconds(job.value, nowMs.value));
});
const canRetrySteps = computed(() => {
  const status = job.value?.status;
  return status === "done" || status === "failed" || status === "cancelled";
});
const canReuseTranscript = computed(() =>
  Boolean(hasTranscript.value && canRetrySteps.value)
);
const timingRows = computed(() => {
  const timing = job.value?.timing || {};
  const keys = [
    "resolving",
    "extracting",
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
  if (!job.value) return;
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

function seek(seconds: number) {
  player.value?.seek(seconds);
}

function seekFromQuery() {
  const raw = route.query.t;
  const value = Number(Array.isArray(raw) ? raw[0] : raw);
  if (!Number.isFinite(value) || value < 0) return;
  player.value?.seek(value);
}

function onPlayerReady() {
  if (playHint.value.startsWith("首次播放")) playHint.value = "";
}

function onPlayerError(message: string) {
  playHint.value = message;
}

async function retry() {
  if (!job.value) return;
  job.value = await api.retryJob(job.value.id);
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
    await router.push("/");
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

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer);
  if (clock !== undefined) window.clearInterval(clock);
});
</script>

<template>
  <div class="page-title">
    <Button variant="ghost" size="icon" class="icon-btn" as-child>
      <router-link to="/" aria-label="返回任务列表" title="返回任务列表">
        <ChevronLeft />
      </router-link>
    </Button>
    <JobTitleEditor v-if="job" heading :title="job.title" :save="rename" />
    <h1 v-else>任务详情</h1>
  </div>
  <div v-if="job">
    <p class="sub">
      <template v-if="formatDateTime(job.source_created_at)">{{
        formatDateTime(job.source_created_at)
      }}</template>
      <template v-if="formatDateTime(job.source_created_at) && job.source_url">
        ·
      </template>
      {{ job.source_url }}
    </p>
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
        <Badge variant="secondary">{{ job.source_type || "未知类型" }}</Badge>
        <Button
          v-if="jobBusy"
          variant="destructive"
          type="button"
          @click="cancel"
          >取消任务</Button
        >
        <Button v-if="canRetrySteps" type="button" @click="retranscribe"
          >重新转写</Button
        >
        <Button
          v-if="canReuseTranscript"
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
          >重新总结</Button
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

    <section v-if="job.summary" class="card">
      <h2>{{ job.summary.title }}</h2>
      <div class="overview" v-html="overviewHtml" />
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
            @click="seek(chapter.start)"
            >{{ formatTimestamp(chapter.start) }}</Button
          >
          <strong>{{ chapter.title }}</strong>
        </p>
        <ul>
          <li v-for="(bullet, bIndex) in chapter.bullets" :key="bIndex">
            {{ bullet }}
          </li>
        </ul>
      </div>
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
            @click="seek(point.start)"
            >{{ formatTimestamp(point.start) }}</Button
          >
          <span>{{ point.text }}</span>
        </p>
      </div>
    </section>

    <section v-if="showTranscript && job.transcript.length" class="card">
      <h3>转写</h3>
      <p v-for="seg in job.transcript" :key="seg.id" class="text-line">
        <Button
          class="time-btn"
          variant="secondary"
          size="sm"
          type="button"
          @click="seek(seg.start)"
          >{{ formatTimestamp(seg.start) }}</Button
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
