<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  api,
  type AppSettings,
  type LexiconFix,
  type PluginInfo,
  type ScheduleConfig,
  type ScheduleLog,
} from "../api";
import { emptyDomainPack, type DomainPack } from "../utils/domain";
import {
  ChevronRight,
  Loader2,
  Plus,
  SquareArrowOutUpRight,
  Trash2,
} from "@lucide/vue";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  CUSTOM_MODEL,
  LOCAL_TRANSCRIBE_MODELS,
  isLocalTranscribeModel,
  transcribeChoice,
} from "../utils/settings";
import { version as appVersion } from "../../package.json";
import {
  parseLexiconTerms,
  sanitizeLexiconFixes,
  serializeLexiconTerms,
} from "../utils/lexicon";
import { THEMES, applyTheme, readTheme, type ThemeId } from "../utils/theme";
import { formatDateTime } from "../utils/time";
import { toast } from "vue-sonner";
import InfoTip from "../components/InfoTip.vue";

const form = ref<AppSettings>({
  transcribe_base_url: "",
  transcribe_api_key: "",
  transcribe_model: "",
  summarize_base_url: "",
  summarize_api_key: "",
  summarize_model: "",
  capture_seconds: "180",
  summarize_concurrency: 3,
  transcribe_threads: 1,
  transcribe_fast: false,
  cpu_count: 1,
  ai_proofread: true,
  show_transcript: true,
  domain_pack: emptyDomainPack(),
  domain_presets: [],
});
const savingDomain = ref(false);
const savingPreset = ref(false);
const askingDeletePreset = ref(false);
const showDomainDetails = ref(false);
const showDomainAdvanced = ref(false);
const lexiconCustomized = ref(false);
const termsText = ref("");
const fixes = ref<LexiconFix[]>([]);
const savingLexicon = ref(false);
const themeId = ref<ThemeId>(readTheme());
const transcribeSource = ref<"local" | "custom">("local");
const schedule = ref<ScheduleConfig>({
  enabled: false,
  time: "08:00",
  since: "",
  max_jobs: 5,
  domain_id: "a-share",
  sites: [],
});
const scheduleLogs = ref<ScheduleLog[]>([]);
const savingSchedule = ref(false);
const runningSchedule = ref(false);
const PENDING_RUN_ID = "pending-run";
let runWatching = false;
const askingClearLogs = ref(false);
const clearingLogs = ref(false);
const plugins = ref<PluginInfo[]>([]);
const pluginBusyId = ref("");
const askingUninstall = ref(false);
const uninstallTarget = ref<PluginInfo | null>(null);
type SettingsTab =
  "appearance" | "models" | "domain" | "schedule" | "plugins" | "about";
const settingsTabs: { id: SettingsTab; label: string }[] = [
  { id: "models", label: "转写与总结" },
  { id: "domain", label: "内容领域" },
  { id: "schedule", label: "定时任务" },
  { id: "plugins", label: "插件" },
  { id: "appearance", label: "外观" },
  { id: "about", label: "关于" },
];
const route = useRoute();
const router = useRouter();

function isSettingsTab(value: unknown): value is SettingsTab {
  return settingsTabs.some((item) => item.id === value);
}

function settingsTabFromQuery(raw: unknown): SettingsTab {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return isSettingsTab(value) ? value : "models";
}

const settingsTab = ref<SettingsTab>(settingsTabFromQuery(route.query.tab));

function selectSettingsTab(id: SettingsTab) {
  settingsTab.value = id;
  const nextTab = id === "models" ? undefined : id;
  const current = Array.isArray(route.query.tab)
    ? route.query.tab[0]
    : route.query.tab;
  if (current === nextTab) return;
  const query = { ...route.query };
  if (nextTab) {
    query.tab = nextTab;
  } else {
    delete query.tab;
  }
  void router.replace({ query });
}
let pluginTimer: number | undefined;
const maxJobOptions = Array.from({ length: 20 }, (_, index) =>
  String(index + 1)
);

const termCount = computed(() => parseLexiconTerms(termsText.value).length);
const fixCount = computed(() => sanitizeLexiconFixes(fixes.value).length);
const concurrencyOptions = ["1", "2", "3", "4", "5", "6", "7", "8"];
const cpuCount = computed(() => Math.max(1, Number(form.value.cpu_count) || 1));
const defaultThreadHint = computed(() =>
  Math.max(1, Math.min(cpuCount.value, Math.floor(cpuCount.value * 0.8) || 1))
);
const threadOptions = computed(() =>
  Array.from({ length: cpuCount.value }, (_, index) => String(index + 1))
);
const concurrencySelect = computed({
  get: () => {
    const value = Number(form.value.summarize_concurrency);
    if (!Number.isFinite(value)) return "3";
    return String(Math.max(1, Math.min(8, Math.round(value))));
  },
  set: (value: string) => {
    const parsed = Number(value);
    form.value.summarize_concurrency = Number.isFinite(parsed)
      ? Math.max(1, Math.min(8, Math.round(parsed)))
      : 3;
  },
});
const threadSelect = computed({
  get: () => {
    const max = cpuCount.value;
    const value = Number(form.value.transcribe_threads);
    if (!Number.isFinite(value) || value <= 0)
      return String(defaultThreadHint.value);
    return String(Math.max(1, Math.min(max, Math.round(value))));
  },
  set: (value: string) => {
    const parsed = Number(value);
    const max = cpuCount.value;
    form.value.transcribe_threads = Number.isFinite(parsed)
      ? Math.max(1, Math.min(max, Math.round(parsed)))
      : defaultThreadHint.value;
  },
});
const maxJobsSelect = computed({
  get: () => String(Math.max(1, Math.min(20, schedule.value.max_jobs || 5))),
  set: (value: string) => {
    const parsed = Number(value);
    schedule.value.max_jobs = Number.isFinite(parsed)
      ? Math.max(1, Math.min(20, Math.round(parsed)))
      : 5;
  },
});

const presets = [
  {
    id: "deepseek-flash",
    name: "DeepSeek V4 Flash（推荐）",
    summarize_base_url: "https://api.deepseek.com/v1",
    summarize_model: "deepseek-v4-flash",
  },
  {
    id: "deepseek-pro",
    name: "DeepSeek V4 Pro",
    summarize_base_url: "https://api.deepseek.com/v1",
    summarize_model: "deepseek-v4-pro",
  },
];

const transcribeSelect = computed({
  get: () =>
    transcribeSource.value === "custom"
      ? CUSTOM_MODEL
      : transcribeChoice(form.value.transcribe_model),
  set: (value: string) => {
    if (value === CUSTOM_MODEL) {
      transcribeSource.value = "custom";
      if (
        isLocalTranscribeModel(form.value.transcribe_model) ||
        !form.value.transcribe_model.trim()
      ) {
        form.value.transcribe_model = "";
      }
      return;
    }
    transcribeSource.value = "local";
    applyLocalTranscribe(value);
  },
});

const localTranscribe = computed(() => transcribeSource.value === "local");

onMounted(async () => {
  themeId.value = readTheme();
  form.value = await api.settings();
  if (!form.value.domain_pack) {
    form.value.domain_pack = emptyDomainPack();
  }
  if (!form.value.domain_presets) {
    form.value.domain_presets = [];
  }
  if (
    !form.value.transcribe_model.trim() ||
    isLocalTranscribeModel(form.value.transcribe_model)
  ) {
    transcribeSource.value = "local";
    applyLocalTranscribe(
      form.value.transcribe_model || LOCAL_TRANSCRIBE_MODELS[0].value
    );
  } else {
    transcribeSource.value = "custom";
  }
  await loadLexicon();
  await loadSchedule();
  await loadPlugins();
});

onBeforeUnmount(() => {
  runWatching = false;
  if (pluginTimer) window.clearInterval(pluginTimer);
});

function applyLocalTranscribe(model: string) {
  form.value.transcribe_model = model || LOCAL_TRANSCRIBE_MODELS[0].value;
  form.value.transcribe_base_url = "";
  form.value.transcribe_api_key = "";
}

function pickTheme(id: ThemeId) {
  themeId.value = applyTheme(id);
}

function applyPreset(id: string) {
  const preset = presets.find((item) => item.id === id);
  if (!preset) return;
  form.value.summarize_base_url = preset.summarize_base_url;
  form.value.summarize_model = preset.summarize_model;
}

async function save() {
  if (transcribeSource.value === "local") {
    applyLocalTranscribe(form.value.transcribe_model);
  }
  form.value = await api.saveSettings(form.value);
  if (!form.value.domain_pack) {
    form.value.domain_pack = emptyDomainPack();
  }
  toast.success(
    "设置已保存，仅存在本地。改领域会同时换总结口径和转写词汇表，只影响之后的任务。"
  );
  const preset = currentPack().id;
  try {
    applyLexicon(
      await api.saveLexicon(
        {
          terms: parseLexiconTerms(termsText.value),
          fixes: sanitizeLexiconFixes(fixes.value),
        },
        preset
      )
    );
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "保存词汇表失败");
  }
}

function applyLexicon(data: {
  terms: string[];
  fixes: LexiconFix[];
  customized: boolean;
}) {
  termsText.value = serializeLexiconTerms(data.terms);
  fixes.value = data.fixes.length
    ? data.fixes.map((item) => ({ ...item }))
    : [{ wrong: "", right: "" }];
  lexiconCustomized.value = data.customized;
}

async function loadLexicon(preset?: string) {
  try {
    applyLexicon(await api.lexicon(preset || currentPack().id));
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "无法加载词汇表");
  }
}

async function loadSchedule() {
  try {
    const [next, logs] = await Promise.all([
      api.schedule(),
      api.scheduleLogs(),
    ]);
    schedule.value = next;
    scheduleLogs.value = logs;
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "无法加载定时任务设置");
  }
}

function pluginStatusLabel(status: string) {
  if (status === "ready") return "已安装";
  if (status === "installing") return "安装中";
  if (status === "failed") return "失败";
  return "未安装";
}

function syncPluginPoll(items: PluginInfo[]) {
  const installing = items.some((item) => item.status === "installing");
  if (installing && pluginTimer === undefined) {
    pluginTimer = window.setInterval(() => {
      void loadPlugins();
    }, 2000);
  }
  if (!installing && pluginTimer !== undefined) {
    window.clearInterval(pluginTimer);
    pluginTimer = undefined;
  }
}

async function loadPlugins() {
  try {
    plugins.value = await api.plugins();
    syncPluginPoll(plugins.value);
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "无法加载插件");
  }
}

async function installDocPlugin(id: string) {
  pluginBusyId.value = id;
  try {
    await api.installPlugin(id);
    await loadPlugins();
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "安装插件失败");
  } finally {
    pluginBusyId.value = "";
  }
}

function askUninstallPlugin(item: PluginInfo) {
  if (
    pluginBusyId.value === item.id ||
    item.status === "missing" ||
    item.status === "installing"
  )
    return;
  uninstallTarget.value = item;
  askingUninstall.value = true;
}

function closeUninstallPlugin() {
  askingUninstall.value = false;
}

async function cancelDocPlugin(id: string) {
  pluginBusyId.value = id;
  try {
    const info = await api.cancelPlugin(id);
    plugins.value = plugins.value.map((item) => (item.id === id ? info : item));
    await loadPlugins();
    toast.success("已取消安装");
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "取消安装失败");
    await loadPlugins();
  } finally {
    pluginBusyId.value = "";
  }
}

async function uninstallDocPlugin() {
  const item = uninstallTarget.value;
  if (!item) return;
  askingUninstall.value = false;
  pluginBusyId.value = item.id;
  try {
    await api.uninstallPlugin(item.id);
    await loadPlugins();
    toast.success("已卸载插件");
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "卸载插件失败");
  } finally {
    pluginBusyId.value = "";
  }
}

async function saveSchedule() {
  if (savingSchedule.value) return;
  savingSchedule.value = true;
  try {
    schedule.value = await api.saveSchedule(schedule.value);
    toast.success(
      schedule.value.enabled
        ? "定时任务已保存。到点会扫描已启用站点，跳过已有任务。"
        : "已保存。未开启每天定时，启动和后台都不会自动扫描。"
    );
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "保存定时任务失败");
  } finally {
    savingSchedule.value = false;
  }
}

async function runScheduleNow() {
  if (runningSchedule.value) return;
  runningSchedule.value = true;
  runWatching = true;
  const pending: ScheduleLog = {
    id: PENDING_RUN_ID,
    started_at: new Date().toISOString(),
    finished_at: null,
    trigger: "manual",
    status: "running",
    summary: "正在扫描站点…",
    detail: [],
  };
  scheduleLogs.value = [
    pending,
    ...scheduleLogs.value.filter((item) => item.id !== PENDING_RUN_ID),
  ];
  await nextTick();
  try {
    let log = await api.runSchedule();
    upsertScheduleLog(log);
    const started = Date.now();
    while (
      log.status === "running" &&
      runWatching &&
      Date.now() - started < 180000
    ) {
      await sleep(500);
      if (!runWatching) return;
      const logs = await api.scheduleLogs();
      scheduleLogs.value = logs;
      log = logs.find((item) => item.id === log.id) || logs[0] || log;
    }
    if (!runWatching) return;
    if (log.status === "running") {
      toast.error("仍在扫描，请稍后查看日志");
      return;
    }
    if (log.status === "failed") {
      toast.error(log.summary || "定时任务失败");
    } else if (log.status === "partial") {
      toast.error(log.summary || "部分站点未拉完");
    } else {
      toast.success(log.summary || "已执行一轮定时任务");
    }
  } catch (err) {
    scheduleLogs.value = scheduleLogs.value.filter(
      (item) => item.id !== PENDING_RUN_ID
    );
    toast.error(err instanceof Error ? err.message : "立即执行失败");
  } finally {
    runningSchedule.value = false;
  }
}

function upsertScheduleLog(log: ScheduleLog) {
  scheduleLogs.value = [
    log,
    ...scheduleLogs.value.filter(
      (item) => item.id !== log.id && item.id !== PENDING_RUN_ID
    ),
  ].slice(0, 20);
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function askClearLogs() {
  if (!scheduleLogs.value.length || clearingLogs.value) return;
  askingClearLogs.value = true;
}

async function clearScheduleLogs() {
  if (clearingLogs.value) return;
  askingClearLogs.value = false;
  clearingLogs.value = true;
  try {
    await api.clearScheduleLogs();
    scheduleLogs.value = [];
    toast.success("定时日志已清除");
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "清除日志失败");
  } finally {
    clearingLogs.value = false;
  }
}

function scheduleTriggerLabel(trigger: string) {
  if (trigger === "manual") return "手动";
  if (trigger === "startup") return "启动补跑";
  return "定时";
}

function scheduleStatusLabel(status: string) {
  if (status === "failed") return "失败";
  if (status === "partial") return "部分成功";
  if (status === "running") return "进行中";
  return "成功";
}

function addFix() {
  fixes.value = [...fixes.value, { wrong: "", right: "" }];
}

function removeFix(index: number) {
  const next = fixes.value.filter((_, itemIndex) => itemIndex !== index);
  fixes.value = next.length ? next : [{ wrong: "", right: "" }];
}

async function saveLexicon() {
  savingLexicon.value = true;
  try {
    applyLexicon(
      await api.saveLexicon(
        {
          terms: parseLexiconTerms(termsText.value),
          fixes: sanitizeLexiconFixes(fixes.value),
        },
        currentPack().id
      )
    );
    toast.success("词汇表已保存，后续转写校对会使用这份词。");
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "保存词汇表失败");
  } finally {
    savingLexicon.value = false;
  }
}

async function resetLexicon() {
  if (!window.confirm("恢复默认词汇表？当前增删改都会丢掉。")) return;
  savingLexicon.value = true;
  try {
    applyLexicon(await api.resetLexicon(currentPack().id));
    toast.success("已恢复当前领域的默认词汇。");
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "恢复默认词汇失败");
  } finally {
    savingLexicon.value = false;
  }
}

function currentPack(): DomainPack {
  if (!form.value.domain_pack) {
    form.value.domain_pack = emptyDomainPack();
  }
  return form.value.domain_pack;
}

const domainPack = computed(() => currentPack());

function clonePack(pack: DomainPack): DomainPack {
  return {
    ...pack,
    example_questions: [...(pack.example_questions || [])],
    content_keywords: [...(pack.content_keywords || [])],
    highlight_phrases: [...(pack.highlight_phrases || [])],
  };
}

function markDomainCustom() {
  /* 改规则保留当前预设 id，保存时写回该领域 */
}

const domainSelect = computed({
  get: () => currentPack().id || "a-share",
  set: (value: string) => {
    applyDomainPreset(value);
  },
});

function applyDomainPreset(id: string) {
  if (id === "custom") {
    return;
  }
  const preset = (form.value.domain_presets || []).find(
    (item) => item.id === id
  );
  if (!preset) return;
  form.value.domain_pack = clonePack(preset);
  toast.success(
    `已套用「${preset.name}」。词汇表已换成该领域的，点「保存领域」后用于转写和总结。`
  );
  void loadLexicon(preset.id);
}

function applySettingsPack(saved: AppSettings) {
  if (saved.domain_pack) {
    form.value.domain_pack = saved.domain_pack;
  }
  if (saved.domain_presets) {
    form.value.domain_presets = saved.domain_presets;
  }
}

async function addDomainPreset() {
  savingPreset.value = true;
  try {
    const saved = await api.addDomainPreset(currentPack().id);
    applySettingsPack(saved);
    toast.success(
      `已添加「${currentPack().name}」。可改名称和规则后点保存领域。`
    );
    void loadLexicon(currentPack().id);
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "添加领域失败");
  } finally {
    savingPreset.value = false;
  }
}

async function deleteDomainPreset() {
  const pack = currentPack();
  if (pack.id === "a-share") return;
  askingDeletePreset.value = false;
  savingPreset.value = true;
  try {
    const saved = await api.deleteDomainPreset(pack.id);
    applySettingsPack(saved);
    toast.success("领域已删除，已切回 A 股盘面课。");
    void loadLexicon(currentPack().id);
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "删除领域失败");
  } finally {
    savingPreset.value = false;
  }
}

function askDeletePreset() {
  if (currentPack().id === "a-share" || savingPreset.value) return;
  askingDeletePreset.value = true;
}

function resetDomainPreset() {
  applyDomainPreset(currentPack().id || "a-share");
}

async function saveDomain() {
  savingDomain.value = true;
  try {
    const saved = await api.saveDomainPack(currentPack());
    applySettingsPack(saved);
    toast.success("领域已保存。预设、名称和规则会用于之后的转写和总结。");
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "保存领域失败");
  } finally {
    savingDomain.value = false;
  }
}

function joinLines(items: string[] | undefined): string {
  return (items || []).join("\n");
}

function splitLines(value: string): string[] {
  return value
    .split(/\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

const exampleQuestionsText = computed({
  get: () => joinLines(currentPack().example_questions),
  set: (value: string) => {
    currentPack().example_questions = splitLines(value);
    markDomainCustom();
  },
});
const contentKeywordsText = computed({
  get: () => joinLines(currentPack().content_keywords),
  set: (value: string) => {
    currentPack().content_keywords = splitLines(value);
    markDomainCustom();
  },
});
const highlightPhrasesText = computed({
  get: () => joinLines(currentPack().highlight_phrases),
  set: (value: string) => {
    currentPack().highlight_phrases = splitLines(value);
    markDomainCustom();
  },
});
</script>

<template>
  <div>
    <div class="section-title page-heading">
      <h1>设置</h1>
    </div>

    <div class="settings-tablist" role="tablist" aria-label="设置分组">
      <button
        v-for="item in settingsTabs"
        :id="`settings-tab-${item.id}`"
        :key="item.id"
        type="button"
        role="tab"
        class="settings-tab"
        :aria-selected="settingsTab === item.id"
        :aria-controls="`settings-panel-${item.id}`"
        :tabindex="settingsTab === item.id ? 0 : -1"
        @click="selectSettingsTab(item.id)"
      >
        {{ item.label }}
      </button>
    </div>

    <section
      v-show="settingsTab === 'models'"
      id="settings-panel-models"
      class="card settings-panel"
      role="tabpanel"
      aria-labelledby="settings-tab-models"
    >
      <div class="model-block">
        <div class="section-title">
          <h3>转写</h3>
          <InfoTip label="转写说明">
            默认走本机 SenseVoice，不需要 Base URL 和 API Key，也可改选本机
            Whisper。选「云端 / 自定义」后，对方必须提供 OpenAI
            兼容的音频转写接口
            <code>/v1/audio/transcriptions</code>，并返回带时间戳的
            <code>verbose_json</code> 分段，时间轴才准。
            DeepSeek、GPT-4o、通义、Kimi
            这类<strong>聊天模型不能用来转写</strong>。
          </InfoTip>
        </div>
        <div class="grid two">
          <div class="field field-md">
            <div class="flex items-center gap-1">
              <Label>转写模型</Label>
              <InfoTip v-if="!localTranscribe" label="自定义转写说明">
                三项都要填。Base URL 一般带到
                <code>/v1</code>，模型名填对方控制台的精确 ID（如
                whisper-1）。没填 API Key 不会走云端，会退回默认的本机
                SenseVoice。不要填 tiny / small / large
                等本地型号，否则仍走对应的本机 SenseVoice。
              </InfoTip>
            </div>
            <Select v-model="transcribeSelect">
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem
                  v-for="item in LOCAL_TRANSCRIBE_MODELS"
                  :key="item.value"
                  :value="item.value"
                >
                  {{ item.label }}
                </SelectItem>
                <SelectItem :value="CUSTOM_MODEL">云端 / 自定义</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div v-if="!localTranscribe" class="field field-md">
            <Label>自定义转写模型名</Label>
            <Input v-model="form.transcribe_model" placeholder="whisper-1" />
          </div>
          <div v-if="!localTranscribe" class="field field-lg">
            <Label>转写 Base URL</Label>
            <Input
              v-model="form.transcribe_base_url"
              placeholder="https://api.openai.com/v1"
            />
          </div>
          <div v-if="!localTranscribe" class="field field-lg">
            <Label>转写 API Key</Label>
            <Input v-model="form.transcribe_api_key" type="password" />
          </div>
          <div class="field field-sm">
            <div class="flex items-center gap-1">
              <Label>转写线程</Label>
            </div>
            <Select v-model="threadSelect">
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem
                  v-for="item in threadOptions"
                  :key="item"
                  :value="item"
                  >{{ item }} 路</SelectItem
                >
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      <div class="model-block">
        <div class="section-title">
          <h3>总结</h3>
          <InfoTip label="总结说明">
            填模型名、Base URL、API Key 即可接入 OpenAI 兼容的 Chat
            Completions。
            DeepSeek、OpenAI、通义兼容模式、Kimi、智谱、OpenRouter、本地 Ollama
            / vLLM 一般能用。 Claude、Gemini、Azure
            的<strong>原生接口不支持</strong>。同一套配置也会用于 AI
            校对和知识库对话。Base URL 通常要带到 <code>/v1</code>。
          </InfoTip>
        </div>
        <Label>一键套用总结模型</Label>
        <div class="row mb-3.5">
          <Button
            variant="outline"
            type="button"
            @click="applyPreset('deepseek-flash')"
            >DeepSeek V4 Flash（推荐）</Button
          >
          <Button
            variant="outline"
            type="button"
            @click="applyPreset('deepseek-pro')"
            >DeepSeek V4 Pro</Button
          >
        </div>
        <div class="grid two">
          <div class="field field-md">
            <Label>总结模型</Label>
            <Input
              v-model="form.summarize_model"
              placeholder="deepseek-v4-flash"
            />
          </div>
          <div class="field field-lg">
            <Label>总结 Base URL</Label>
            <Input
              v-model="form.summarize_base_url"
              placeholder="https://api.deepseek.com/v1"
            />
          </div>
          <div class="field field-lg">
            <Label>总结 API Key</Label>
            <Input v-model="form.summarize_api_key" type="password" />
          </div>
          <div class="field field-sm">
            <Label>抽音时长（秒，直播/长回放截取）</Label>
            <Input v-model="form.capture_seconds" />
          </div>
          <div class="field field-sm">
            <div class="flex items-center gap-1">
              <Label>分段并发数</Label>
              <InfoTip label="分段并发说明">
                长视频会按时间切开后同时打总结模型。1 路即串行；默认 3
                路。调太高可能触发接口限流。
              </InfoTip>
            </div>
            <Select v-model="concurrencySelect">
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem
                  v-for="item in concurrencyOptions"
                  :key="item"
                  :value="item"
                  >{{ item }} 路</SelectItem
                >
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
      <div class="check-block">
        <label class="check">
          <Checkbox v-model="form.transcribe_fast" />
          <span class="flex items-center gap-1">
            快速转写（跳过过长片段的二次切开）
          </span>
        </label>
        <label class="check">
          <Checkbox v-model="form.ai_proofread" />
          <span class="flex items-center gap-1">
            自动任务使用 AI 校对转写（使用总结模型进行校对）
            <InfoTip label="AI 校对说明">
              只把拼音接近词表的片段送给云端，没有候选则跳过。关掉后只保留本地词表。仍可在任务详情点「重新校对转写」。
            </InfoTip>
          </span>
        </label>
        <label class="check">
          <Checkbox v-model="form.show_transcript" />
          <span class="flex items-center gap-1"> 任务详情显示转写原文 </span>
        </label>
      </div>
      <div class="row mt-3.5">
        <Button type="button" @click="save">保存设置</Button>
      </div>
    </section>

    <section
      v-show="settingsTab === 'domain'"
      id="settings-panel-domain"
      class="card settings-panel"
      role="tabpanel"
      aria-labelledby="settings-tab-domain"
    >
      <div class="section-title">
        <h3>内容领域</h3>
      </div>
      <div class="grid two">
        <div class="field field-md">
          <div class="flex items-center gap-1">
            <Label>预设</Label>
            <Button
              variant="ghost"
              size="icon-xs"
              class="icon-btn disabled:pointer-events-auto disabled:cursor-not-allowed"
              type="button"
              aria-label="添加预设"
              title="添加预设"
              :disabled="savingPreset"
              @click="addDomainPreset"
            >
              <Plus class="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon-xs"
              class="icon-btn text-destructive disabled:pointer-events-auto disabled:cursor-not-allowed"
              type="button"
              aria-label="删除当前预设"
              title="删除当前预设"
              :disabled="savingPreset || domainPack.id === 'a-share'"
              @click="askDeletePreset"
            >
              <Trash2 class="size-4" />
            </Button>
          </div>
          <Select v-model="domainSelect">
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem
                v-for="item in form.domain_presets || []"
                :key="item.id"
                :value="item.id"
              >
                {{ item.name }}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div class="field field-md">
          <Label>领域名称</Label>
          <Input v-model="domainPack.name" @input="markDomainCustom" />
        </div>
      </div>
      <div class="row mt-3.5">
        <Button
          variant="ghost"
          type="button"
          class="h-auto px-0 text-muted-foreground hover:bg-transparent hover:text-foreground"
          @click="showDomainDetails = !showDomainDetails"
        >
          <ChevronRight
            class="size-4 transition-transform"
            :class="{ 'rotate-90': showDomainDetails }"
          />
          {{ showDomainDetails ? "收起领域规则" : "展开领域规则" }}
        </Button>
      </div>
      <div v-show="showDomainDetails" class="domain-details">
        <Label class="mt-3.5">转写提示</Label>
        <Input
          v-model="domainPack.asr_hint"
          placeholder="以下是简体中文A股盘面课。"
          @input="markDomainCustom"
        />
        <Label class="mt-3.5">总结关注点</Label>
        <Textarea
          v-model="domainPack.chapter_focus"
          class="domain-area"
          @input="markDomainCustom"
        />
        <Label class="mt-3.5">术语与简称</Label>
        <Textarea
          v-model="domainPack.term_aliases"
          class="domain-area"
          @input="markDomainCustom"
        />
        <Label class="mt-3.5">综述角色</Label>
        <Textarea
          v-model="domainPack.overview_role"
          class="domain-area"
          @input="markDomainCustom"
        />
        <Label class="mt-3.5">辨立场与免责</Label>
        <Textarea
          v-model="domainPack.overview_stance"
          class="domain-area"
          @input="markDomainCustom"
        />
        <Label class="mt-3.5">综述免责声明</Label>
        <Textarea
          v-model="domainPack.disclaimer"
          class="domain-area"
          @input="markDomainCustom"
        />
        <Label class="mt-3.5">知识库护栏</Label>
        <Textarea
          v-model="domainPack.knowledge_guardrails"
          class="domain-area"
          @input="markDomainCustom"
        />
        <Label class="mt-3.5">知识库示例问题（每行一个）</Label>
        <Textarea v-model="exampleQuestionsText" class="domain-area" />
        <Label class="mt-3.5">开讲关键词（每行一个，用于裁掉片头寒暄）</Label>
        <Textarea v-model="contentKeywordsText" class="domain-area" />
        <Label class="mt-3.5">综述高亮短语（每行一个）</Label>
        <Textarea v-model="highlightPhrasesText" class="domain-area" />
        <div class="check-block">
          <label class="check">
            <Checkbox
              :model-value="domainPack.highlight_stock_codes"
              @update:model-value="
                (value) => {
                  domainPack.highlight_stock_codes = Boolean(value);
                  markDomainCustom();
                }
              "
            />
            <span class="flex items-center gap-1">
              综述里加粗股票代码、板块和公司名
              <InfoTip label="综述高亮说明">
                关掉后不再把 6 位数字或「某某板块」当成标的。
              </InfoTip>
            </span>
          </label>
        </div>
        <Label class="mt-3.5">校对提示</Label>
        <Textarea
          v-model="domainPack.proofread_hint"
          class="domain-area"
          @input="markDomainCustom"
        />
      </div>
      <div class="row mt-3.5">
        <Button type="button" :disabled="savingDomain" @click="saveDomain"
          >保存领域</Button
        >
      </div>
      <div class="lexicon-block">
        <div class="section-title">
          <h3>转写词汇表</h3>
          <InfoTip label="转写词汇表说明">
            正确词用于拼音对齐和校对提示，替换规则用于整词替换。A
            股预设带默认行话，通用课程默认空表。
          </InfoTip>
        </div>
        <p class="msg mb-3">
          当前 {{ termCount }} 个正确词、{{ fixCount }} 条替换{{
            lexiconCustomized ? "，已按你的修改保存" : "，仍是该领域的默认词表"
          }}。
        </p>
        <Label>正确词（每行一个）</Label>
        <Textarea
          v-model="termsText"
          class="lex-terms"
          spellcheck="false"
          :placeholder="
            domainPack.base_preset === 'a-share'
              ? '打板\n龙头\n弱转强'
              : '概念\n方法\n步骤'
          "
        />
        <Label class="mt-3.5">听写替换</Label>
        <div class="lex-table-wrap">
          <table class="lex-table">
            <thead>
              <tr>
                <th>听错</th>
                <th>改成</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, index) in fixes" :key="index">
                <td>
                  <Input
                    v-model="item.wrong"
                    :placeholder="
                      domainPack.base_preset === 'a-share' ? '打版' : '听错'
                    "
                  />
                </td>
                <td>
                  <Input
                    v-model="item.right"
                    :placeholder="
                      domainPack.base_preset === 'a-share' ? '打板' : '改成'
                    "
                  />
                </td>
                <td>
                  <Button
                    variant="outline"
                    class="text-destructive"
                    type="button"
                    @click="removeFix(index)"
                    >删除</Button
                  >
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="row mt-3.5">
          <Button variant="outline" type="button" @click="addFix"
            >添加替换</Button
          >
          <Button type="button" :disabled="savingLexicon" @click="saveLexicon"
            >保存词汇表</Button
          >
          <Button
            variant="outline"
            type="button"
            :disabled="savingLexicon"
            @click="resetLexicon"
            >恢复该领域默认</Button
          >
        </div>
      </div>
      <div class="row mt-3.5">
        <Button
          variant="ghost"
          type="button"
          class="h-auto px-0 text-muted-foreground hover:bg-transparent hover:text-foreground"
          @click="showDomainAdvanced = !showDomainAdvanced"
        >
          <ChevronRight
            class="size-4 transition-transform"
            :class="{ 'rotate-90': showDomainAdvanced }"
          />
          {{ showDomainAdvanced ? "收起高级 prompt" : "高级：覆盖完整 prompt" }}
        </Button>
        <Button variant="outline" type="button" @click="resetDomainPreset"
          >恢复当前预设</Button
        >
      </div>
      <div v-show="showDomainAdvanced">
        <p class="msg mt-3">
          留空则使用引擎骨架加上面的领域规则。写满则整段替换，可能破坏 JSON
          和时间轴协议。
        </p>
        <Label class="mt-3.5">章节 prompt 覆盖</Label>
        <Textarea
          v-model="domainPack.chapter_prompt_override"
          class="lex-terms"
          @input="markDomainCustom"
        />
        <Label class="mt-3.5">综述 prompt 覆盖</Label>
        <Textarea
          v-model="domainPack.overview_prompt_override"
          class="lex-terms"
          @input="markDomainCustom"
        />
        <Label class="mt-3.5">知识库 prompt 覆盖</Label>
        <Textarea
          v-model="domainPack.knowledge_prompt_override"
          class="lex-terms"
          @input="markDomainCustom"
        />
      </div>
    </section>

    <section
      v-show="settingsTab === 'schedule'"
      id="settings-panel-schedule"
      class="card settings-panel"
      role="tabpanel"
      aria-labelledby="settings-tab-schedule"
    >
      <div class="section-title">
        <h3>定时任务</h3>
        <InfoTip label="定时任务说明">
          B 站多个 UP、小鹅通多个店铺：可在内容源里用逗号或换行填写多个 mid /
          app_id；也可以到「站点」页再添加一条同类型站点，分别命名、单独开关。需要立刻扫一轮时用「立即执行」。
        </InfoTip>
      </div>
      <label class="check !mb-3">
        <Checkbox v-model="schedule.enabled" />
        <span>启用每天定时任务</span>
      </label>
      <div class="grid two">
        <div class="field field-sm">
          <Label>每天几点</Label>
          <Input v-model="schedule.time" type="time" />
        </div>
        <div class="field field-sm">
          <Label>从哪天开始</Label>
          <Input v-model="schedule.since" type="date" />
        </div>
        <div class="field field-sm">
          <Label>每次最多新建</Label>
          <Select v-model="maxJobsSelect">
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem
                v-for="item in maxJobOptions"
                :key="item"
                :value="item"
                >{{ item }} 个任务</SelectItem
              >
            </SelectContent>
          </Select>
        </div>
      </div>
      <div v-if="schedule.sites.length" class="schedule-sites">
        <div
          v-for="site in schedule.sites"
          :key="site.site_id"
          class="schedule-site"
        >
          <label class="check">
            <Checkbox v-model="site.enabled" />
            <span>{{ site.name }}</span>
          </label>
          <Textarea
            v-model="site.catalog_id"
            :placeholder="site.catalog_hint"
            :aria-label="`${site.name}内容源`"
            class="schedule-catalog"
          />
        </div>
      </div>
      <p v-else class="msg mt-3">暂无可定时的站点。</p>
      <div class="row mt-3.5">
        <Button
          type="button"
          :disabled="savingSchedule || runningSchedule"
          @click="saveSchedule"
          >保存定时</Button
        >
        <Button
          variant="outline"
          type="button"
          :disabled="runningSchedule"
          :aria-busy="runningSchedule"
          @click="runScheduleNow"
        >
          <Loader2 v-if="runningSchedule" class="size-4 animate-spin" />
          {{ runningSchedule ? "正在扫描…" : "立即执行" }}
        </Button>
      </div>
      <div class="schedule-logs">
        <div class="schedule-logs-head">
          <h4>最近运行</h4>
          <Button
            variant="outline"
            type="button"
            :disabled="!scheduleLogs.length || clearingLogs || runningSchedule"
            @click="askClearLogs"
            >清除日志</Button
          >
        </div>
        <div class="schedule-log-list" aria-live="polite">
          <p v-if="!scheduleLogs.length" class="msg">还没有运行记录。</p>
          <ul v-else>
            <li
              v-for="item in scheduleLogs"
              :key="item.id"
              :class="{ 'is-running': item.status === 'running' }"
            >
              <div class="schedule-log-head">
                <strong>{{ formatDateTime(item.started_at) }}</strong>
                <span
                  >{{ scheduleTriggerLabel(item.trigger) }} ·
                  {{ scheduleStatusLabel(item.status) }}</span
                >
              </div>
              <p>{{ item.summary }}</p>
            </li>
          </ul>
        </div>
      </div>
    </section>

    <section
      v-show="settingsTab === 'plugins'"
      id="settings-panel-plugins"
      class="card settings-panel"
      role="tabpanel"
      aria-labelledby="settings-tab-plugins"
    >
      <div class="section-title">
        <h3>插件</h3>
      </div>
      <div v-if="!plugins.length" class="msg">正在读取插件状态…</div>
      <div v-else class="plugin-grid">
        <article v-for="item in plugins" :key="item.id" class="plugin-card">
          <div class="plugin-card-head">
            <strong>{{ item.title }}</strong>
            <Badge
              variant="outline"
              class="tag"
              :class="{
                ok: item.status === 'ready',
                bad: item.status === 'failed',
                warn: item.status === 'installing',
              }"
              >{{ pluginStatusLabel(item.status) }}</Badge
            >
          </div>
          <p class="msg">{{ item.description }}</p>
          <p class="msg">{{ item.size_hint }}</p>
          <p v-if="item.error" class="error">{{ item.error }}</p>
          <div class="row plugin-card-actions">
            <Button
              type="button"
              :disabled="
                pluginBusyId === item.id || item.status === 'installing'
              "
              @click="installDocPlugin(item.id)"
              >{{ item.status === "ready" ? "重新安装" : "安装" }}</Button
            >
            <Button
              v-if="item.status === 'installing'"
              variant="outline"
              type="button"
              :disabled="pluginBusyId === item.id"
              @click="cancelDocPlugin(item.id)"
              >取消</Button
            >
            <Button
              v-else
              variant="outline"
              type="button"
              :disabled="pluginBusyId === item.id || item.status === 'missing'"
              @click="askUninstallPlugin(item)"
              >卸载</Button
            >
          </div>
        </article>
      </div>
    </section>

    <section
      v-show="settingsTab === 'appearance'"
      id="settings-panel-appearance"
      class="card settings-panel"
      role="tabpanel"
      aria-labelledby="settings-tab-appearance"
    >
      <div class="section-title">
        <h3>外观</h3>
      </div>
      <div class="theme-grid">
        <Button
          v-for="item in THEMES"
          :key="item.id"
          variant="outline"
          class="theme-card"
          :class="{ on: themeId === item.id }"
          type="button"
          @click="pickTheme(item.id)"
        >
          <span class="theme-preview">
            <span
              v-for="(color, index) in item.swatches"
              :key="index"
              :style="{ background: color }"
            />
          </span>
          <strong>{{ item.name }}</strong>
          <small>{{ item.desc }}</small>
        </Button>
      </div>
    </section>

    <section
      v-show="settingsTab === 'about'"
      id="settings-panel-about"
      class="card settings-panel"
      role="tabpanel"
      aria-labelledby="settings-tab-about"
    >
      <h3>关于</h3>
      <div class="about-list">
        <div class="field">
          <Label>版本</Label>
          <p class="about-version">{{ appVersion }}</p>
        </div>
        <div class="field">
          <Label>免责声明</Label>
          <p>若内容来自付费渠道，仅供个人使用，切勿用于商业用途。</p>
        </div>
        <div class="field">
          <Label>更新日志</Label>
          <Button
            variant="ghost"
            class="about-nav h-auto justify-start px-0 text-muted-foreground hover:bg-transparent hover:text-foreground"
            as-child
          >
            <router-link to="/settings/changelog">
              <span>查看本版本更新</span>
              <SquareArrowOutUpRight
                class="about-nav-icon"
                aria-hidden="true"
              />
            </router-link>
          </Button>
        </div>
      </div>
    </section>

    <Dialog
      :open="askingDeletePreset"
      @update:open="
        (next: boolean) => {
          if (!next) askingDeletePreset = false;
        }
      "
    >
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>确认删除</DialogTitle>
          <DialogDescription>
            确定删除领域「{{
              domainPack.name || "未命名领域"
            }}」？词表也会删掉。已有任务仍保留该领域标记。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            type="button"
            :disabled="savingPreset"
            @click="askingDeletePreset = false"
            >取消</Button
          >
          <Button
            variant="destructive"
            type="button"
            :disabled="savingPreset"
            @click="deleteDomainPreset"
            >确认删除</Button
          >
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog
      :open="askingUninstall"
      @update:open="
        (next: boolean) => {
          if (!next) closeUninstallPlugin();
        }
      "
    >
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>卸载插件</DialogTitle>
          <DialogDescription>
            确定卸载「{{
              uninstallTarget?.title || "该插件"
            }}」？卸载后需要重新安装才能使用。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            type="button"
            :disabled="Boolean(pluginBusyId)"
            @click="closeUninstallPlugin"
            >取消</Button
          >
          <Button
            variant="destructive"
            type="button"
            :disabled="Boolean(pluginBusyId)"
            @click="uninstallDocPlugin"
            >确认卸载</Button
          >
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog
      :open="askingClearLogs"
      @update:open="
        (next: boolean) => {
          if (!next) askingClearLogs = false;
        }
      "
    >
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>清除日志</DialogTitle>
          <DialogDescription>
            确定清除全部定时运行记录？不影响已创建的任务。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            type="button"
            :disabled="clearingLogs"
            @click="askingClearLogs = false"
            >取消</Button
          >
          <Button
            variant="destructive"
            type="button"
            :disabled="clearingLogs"
            @click="clearScheduleLogs"
            >确认清除</Button
          >
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
