<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api, type AppSettings, type LexiconFix } from "../api";
import { emptyDomainPack, type DomainPack } from "../utils/domain";
import { ChevronRight, Plus, Trash2 } from "@lucide/vue";
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
import { toast } from "vue-sonner";

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
    <h1>设置</h1>
    <p class="sub">
      转写默认本机 SenseVoice。总结推荐 DeepSeek V4
      Flash。自定义接口的协议不一样，请看下面的限制。
    </p>

    <section class="card">
      <h3>外观</h3>
      <p class="msg mb-3">主题保存在本机浏览器，切换后立即生效。</p>
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

    <section class="card">
      <div class="model-block">
        <h3>转写</h3>
        <blockquote class="note">
          默认走本机 SenseVoice，不需要 Base URL 和 API Key，也可改选本机
          Whisper。选「云端 / 自定义」后，对方必须提供 OpenAI 兼容的音频转写接口
          <code>/v1/audio/transcriptions</code>，并返回带时间戳的
          <code>verbose_json</code> 分段，时间轴才准。
          DeepSeek、GPT-4o、通义、Kimi
          这类<strong>聊天模型不能用来转写</strong>。
        </blockquote>
        <div class="grid two">
          <div class="field">
            <Label>转写模型</Label>
            <Select v-model="transcribeSelect">
              <SelectTrigger class="w-full">
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
          <div v-if="!localTranscribe" class="field">
            <Label>自定义转写模型名</Label>
            <Input v-model="form.transcribe_model" placeholder="whisper-1" />
          </div>
          <div v-if="!localTranscribe" class="field">
            <Label>转写 Base URL</Label>
            <Input
              v-model="form.transcribe_base_url"
              placeholder="https://api.openai.com/v1"
            />
          </div>
          <div v-if="!localTranscribe" class="field">
            <Label>转写 API Key</Label>
            <Input v-model="form.transcribe_api_key" type="password" />
          </div>
          <div class="field">
            <Label>转写线程</Label>
            <Select v-model="threadSelect">
              <SelectTrigger class="w-full">
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
        <p v-if="localTranscribe" class="msg mt-3">
          本地转写不使用 Base URL 和 API
          Key，保存时会清空这两项。启动后会后台预拉 SenseVoice；Whisper
          则在首次转写时按型号下载。本机 {{ cpuCount }} 核，默认用 80%（{{
            defaultThreadHint
          }}
          路），调低风扇会小、转写变慢。
        </p>
        <p v-else class="msg mt-3">
          三项都要填。Base URL 一般带到
          <code>/v1</code>，模型名填对方控制台的精确 ID（如 whisper-1）。没填
          API Key 不会走云端，会退回默认的本机 SenseVoice。不要填 tiny / small /
          large 等本地型号，否则仍走对应的本机 SenseVoice。
        </p>
      </div>

      <div class="model-block">
        <h3>总结</h3>
        <blockquote class="note">
          填模型名、Base URL、API Key 即可接入 OpenAI 兼容的 Chat Completions。
          DeepSeek、OpenAI、通义兼容模式、Kimi、智谱、OpenRouter、本地 Ollama /
          vLLM 一般能用。 Claude、Gemini、Azure
          的<strong>原生接口不支持</strong>。同一套配置也会用于 AI
          校对和知识库对话。Base URL 通常要带到 <code>/v1</code>。
        </blockquote>
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
          <div class="field">
            <Label>总结模型</Label>
            <Input
              v-model="form.summarize_model"
              placeholder="deepseek-v4-flash"
            />
          </div>
          <div class="field">
            <Label>总结 Base URL</Label>
            <Input
              v-model="form.summarize_base_url"
              placeholder="https://api.deepseek.com/v1"
            />
          </div>
          <div class="field">
            <Label>总结 API Key</Label>
            <Input v-model="form.summarize_api_key" type="password" />
          </div>
          <div class="field">
            <Label>抽音时长（秒，直播/长回放截取）</Label>
            <Input v-model="form.capture_seconds" />
          </div>
          <div class="field">
            <Label>分段并发数</Label>
            <Select v-model="concurrencySelect">
              <SelectTrigger class="w-full">
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
        <p class="msg mt-3">
          长视频会按时间切开后同时打总结模型。1 路即串行；默认 3
          路。调太高可能触发接口限流。
        </p>
      </div>
      <div class="check-block">
        <label class="check">
          <Checkbox v-model="form.transcribe_fast" />
          <span>
            快速转写（跳过过长片段的二次切开）
            <small
              >本机 SenseVoice
              只跑一遍。更快更安静，长段时间轴可能更粗。关掉则过长或过稀的片段会再切再转。</small
            >
          </span>
        </label>
        <label class="check">
          <Checkbox v-model="form.ai_proofread" />
          <span>
            自动任务使用 AI 校对转写（使用总结模型进行校对）
            <small
              >只把拼音接近词表的片段送给云端，没有候选则跳过。关掉后只保留本地词表。仍可在任务详情点「重新校对转写」。</small
            >
          </span>
        </label>
        <label class="check">
          <Checkbox v-model="form.show_transcript" />
          <span>
            任务详情显示转写原文
            <small>关掉后详情页只保留总结和时间轴，界面更干净。</small>
          </span>
        </label>
      </div>
      <div class="row mt-3.5">
        <Button type="button" @click="save">保存设置</Button>
      </div>
    </section>

    <section class="card">
      <h3>内容领域</h3>
      <p class="msg mb-3">
        决定转写提示、总结口径、知识库人设、综述高亮和转写词汇表。默认是 A
        股盘面课；词表跟领域走，切换后两边互不影响。
      </p>
      <div class="grid two">
        <div class="field">
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
            <SelectTrigger class="w-full">
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
        <div class="field">
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
            <span>
              综述里加粗股票代码、板块和公司名
              <small>关掉后不再把 6 位数字或「某某板块」当成标的。</small>
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
        <h3>转写词汇表</h3>
        <p class="msg mb-3">
          属于「{{
            domainPack.name || "当前领域"
          }}」。正确词用于拼音对齐和校对提示，替换规则用于整词替换。A
          股预设带默认行话，通用课程默认空表。当前 {{ termCount }} 个正确词、{{
            fixCount
          }}
          条替换{{
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
          variant="outline"
          type="button"
          @click="showDomainAdvanced = !showDomainAdvanced"
        >
          {{ showDomainAdvanced ? "收起高级 prompt" : "高级：覆盖完整 prompt" }}
        </Button>
        <Button variant="outline" type="button" @click="resetDomainPreset"
          >恢复当前预设</Button
        >
      </div>
      <template v-if="showDomainAdvanced">
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
      </template>
    </section>

    <section class="card">
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
          <Button variant="outline" class="about-nav" as-child>
            <router-link to="/settings/changelog">
              <span>查看本版本更新</span>
              <ChevronRight class="about-nav-icon" aria-hidden="true" />
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
  </div>
</template>
