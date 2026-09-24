<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import {
  ChevronRight,
  EllipsisVertical,
  PanelLeft,
  Pencil,
  Plus,
  Trash2,
} from "@lucide/vue";
import { Badge } from "@/components/ui/badge";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  api,
  type KnowledgeChatOut,
  type KnowledgeConversationSummary,
  type KnowledgeDoc,
  type KnowledgeHit,
} from "../api";
import type { DomainPack } from "../utils/domain";
import { emptyDomainPack } from "../utils/domain";
import { formatChatHtml } from "../utils/highlight";
import Pagination from "../components/Pagination.vue";
import { pageAfterSizeChange } from "../utils/pager";
import { formatTimestamp } from "../utils/time";
import { toast } from "vue-sonner";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  citations?: KnowledgeHit[];
  citationsOpen?: boolean;
};

const DEFAULT_PAGE_SIZE = 10;
const HISTORY_PAGE_SIZE = 30;
const input = ref("");
const loading = ref(false);
const documents = ref<KnowledgeDoc[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(DEFAULT_PAGE_SIZE);
const messages = ref<ChatMessage[]>([]);
const thread = ref<HTMLElement | null>(null);
const domainId = ref("a-share");
const domainPresets = ref<DomainPack[]>([emptyDomainPack()]);
const exampleQuestions = ref(["这节课的核心方法是什么", "有哪些关键步骤"]);
const conversationId = ref("");
const historyQuery = ref("");
const historyItems = ref<KnowledgeConversationSummary[]>([]);
const historyTotal = ref(0);
const historyPage = ref(1);
const historyLoading = ref(false);
const historyOpen = ref(true);
const conversationTitle = ref("");
const historyMenuId = ref("");
const deleting = ref<KnowledgeConversationSummary | null>(null);
const deletingBusy = ref(false);
const renaming = ref<KnowledgeConversationSummary | null>(null);
const renameDraft = ref("");
const renamingBusy = ref(false);
let searchTimer: number | undefined;

const totalPages = computed(() =>
  Math.max(1, Math.ceil(total.value / pageSize.value))
);
const historyHasMore = computed(
  () => historyItems.value.length < historyTotal.value
);
const canStartNewChat = computed(() =>
  Boolean(conversationId.value || messages.value.length)
);
const chatTitle = computed(() => {
  if (conversationId.value) {
    const item = historyItems.value.find(
      (row) => row.id === conversationId.value
    );
    return item?.title || conversationTitle.value || "未命名对话";
  }
  return "新对话";
});

function applyExampleQuestions(pack?: DomainPack | null) {
  const questions = pack?.example_questions?.filter(Boolean);
  exampleQuestions.value = questions?.length
    ? questions
    : ["这节课的核心方法是什么", "有哪些关键步骤"];
}

function currentPack(): DomainPack | undefined {
  return domainPresets.value.find((item) => item.id === domainId.value);
}

async function loadDocuments() {
  const listed = await api.knowledge(
    "",
    domainId.value,
    page.value,
    pageSize.value
  );
  const pages = Math.max(1, Math.ceil(listed.job_count / listed.page_size));
  if (page.value > pages) {
    page.value = pages;
    const again = await api.knowledge(
      "",
      domainId.value,
      page.value,
      pageSize.value
    );
    documents.value = again.documents;
    total.value = again.job_count;
    return;
  }
  documents.value = listed.documents;
  total.value = listed.job_count;
}

async function loadHistory(append = false) {
  historyLoading.value = true;
  try {
    const nextPage = append ? historyPage.value + 1 : 1;
    const listed = await api.knowledgeConversations(
      historyQuery.value.trim(),
      domainId.value,
      nextPage,
      HISTORY_PAGE_SIZE
    );
    historyPage.value = listed.page;
    historyTotal.value = listed.total;
    historyItems.value = append
      ? [...historyItems.value, ...listed.items]
      : listed.items;
  } finally {
    historyLoading.value = false;
  }
}

function onHistorySearch() {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    void loadHistory().catch((err) => {
      toast.error(err instanceof Error ? err.message : "无法加载历史记录");
    });
  }, 250);
}

watch(historyQuery, onHistorySearch);

function goPage(next: number) {
  if (next < 1 || next > totalPages.value || next === page.value) return;
  page.value = next;
  void loadDocuments().catch((err) => {
    toast.error(err instanceof Error ? err.message : "无法加载知识库");
  });
}

function changePageSize(next: number) {
  if (next === pageSize.value) return;
  page.value = pageAfterSizeChange(page.value, pageSize.value, next);
  pageSize.value = next;
  void loadDocuments().catch((err) => {
    toast.error(err instanceof Error ? err.message : "无法加载知识库");
  });
}

function startNewChat() {
  conversationId.value = "";
  conversationTitle.value = "";
  messages.value = [];
}

function toggleHistory() {
  historyOpen.value = !historyOpen.value;
}

function toggleCitations(index: number) {
  const item = messages.value[index];
  if (item) item.citationsOpen = !item.citationsOpen;
}

async function setDomain(value: string | null) {
  const next = value || "a-share";
  if (next === domainId.value) return;
  domainId.value = next;
  page.value = 1;
  historyQuery.value = "";
  startNewChat();
  applyExampleQuestions(currentPack());
  try {
    await Promise.all([loadDocuments(), loadHistory()]);
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "无法加载知识库");
  }
}

async function openConversation(id: string) {
  if (loading.value || id === conversationId.value) return;
  try {
    const detail = await api.knowledgeConversation(id);
    conversationId.value = detail.id;
    conversationTitle.value = detail.title;
    messages.value = detail.messages.map((item) => ({
      role: item.role,
      content: item.content,
      citations: item.citations,
    }));
    await scrollToEnd();
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "无法打开历史记录");
  }
}

function askDelete(item: KnowledgeConversationSummary) {
  historyMenuId.value = "";
  deleting.value = item;
}

function toggleHistoryMenu(event: MouseEvent, id: string) {
  event.stopPropagation();
  historyMenuId.value = historyMenuId.value === id ? "" : id;
}

function closeHistoryMenu() {
  historyMenuId.value = "";
}

function askRename(item: KnowledgeConversationSummary) {
  historyMenuId.value = "";
  renaming.value = item;
  renameDraft.value = item.title;
}

async function confirmRename() {
  if (!renaming.value || renamingBusy.value) return;
  const title = renameDraft.value.trim();
  if (!title) {
    toast.error("标题不能为空");
    return;
  }
  renamingBusy.value = true;
  try {
    const saved = await api.renameKnowledgeConversation(
      renaming.value.id,
      title
    );
    const index = historyItems.value.findIndex((item) => item.id === saved.id);
    if (index >= 0)
      historyItems.value[index] = { ...historyItems.value[index], ...saved };
    renaming.value = null;
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "重命名失败");
  } finally {
    renamingBusy.value = false;
  }
}

async function confirmDelete() {
  if (!deleting.value || deletingBusy.value) return;
  deletingBusy.value = true;
  const id = deleting.value.id;
  try {
    await api.deleteKnowledgeConversation(id);
    deleting.value = null;
    if (conversationId.value === id) startNewChat();
    await loadHistory();
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "删除失败");
    deleting.value = null;
  } finally {
    deletingBusy.value = false;
  }
}

onMounted(async () => {
  document.addEventListener("click", closeHistoryMenu);
  try {
    const settings = await api.settings();
    if (settings.domain_presets?.length) {
      domainPresets.value = settings.domain_presets;
    }
    domainId.value = "a-share";
    applyExampleQuestions(currentPack() || settings.domain_pack);
  } catch {
    /* 示例问法保持默认 */
  }
  try {
    await Promise.all([loadDocuments(), loadHistory()]);
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "无法加载知识库");
  }
});

onBeforeUnmount(() => {
  window.clearTimeout(searchTimer);
  document.removeEventListener("click", closeHistoryMenu);
});

async function send() {
  const text = input.value.trim();
  if (!text || loading.value) return;
  input.value = "";
  messages.value.push({ role: "user", content: text });
  await scrollToEnd();
  loading.value = true;
  try {
    const payload = messages.value.map((item) => ({
      role: item.role,
      content: item.content,
      citations: item.citations,
    }));
    const result: KnowledgeChatOut = await api.knowledgeChat(
      payload,
      domainId.value,
      conversationId.value
    );
    conversationId.value = result.conversation_id;
    conversationTitle.value = result.title;
    messages.value.push({
      role: "assistant",
      content: result.answer,
      citations: result.citations,
    });
    await loadHistory();
  } catch (err) {
    const message = err instanceof Error ? err.message : "对话失败";
    toast.error(message);
    messages.value.push({
      role: "assistant",
      content: "这次没有生成答案。请检查设置里的总结 API Key，或稍后再问。",
    });
  } finally {
    loading.value = false;
    await scrollToEnd();
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void send();
  }
}

function jobLink(hit: {
  job_id: string;
  start?: number;
  segment_id?: number | null;
  locator?: string;
}) {
  const query = new URLSearchParams({ from: "knowledge" });
  if (hit.locator && hit.segment_id != null)
    query.set("seg", String(hit.segment_id));
  else if (hit.segment_id != null && !(hit.start && hit.start > 0))
    query.set("seg", String(hit.segment_id));
  else if (hit.start !== undefined && hit.start > 0)
    query.set("t", String(Math.floor(hit.start)));
  return `/jobs/${hit.job_id}?${query.toString()}`;
}

function citePlace(hit: { locator?: string; start: number; kind: string }) {
  if (hit.locator) return hit.locator;
  if (hit.start > 0) return formatTimestamp(hit.start);
  return "";
}

async function scrollToEnd() {
  await nextTick();
  if (thread.value) thread.value.scrollTop = thread.value.scrollHeight;
}

function loadMoreHistory() {
  if (!historyHasMore.value || historyLoading.value) return;
  void loadHistory(true).catch((err) => {
    toast.error(err instanceof Error ? err.message : "无法加载历史记录");
  });
}
</script>

<template>
  <h1>知识库</h1>
  <p class="sub">
    基于你本机转写和导入文档的私有资料对话。答案只来自当前领域里已完成的任务，不会去网上搜。问答会保存在本机，可搜索或删除。
  </p>

  <section class="card mb-3">
    <div class="field field-md">
      <Label>内容领域</Label>
      <Select :model-value="domainId" @update:model-value="setDomain">
        <SelectTrigger>
          <SelectValue placeholder="A股盘面课" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem
            v-for="item in domainPresets"
            :key="item.id"
            :value="item.id"
          >
            {{ item.name }}
          </SelectItem>
        </SelectContent>
      </Select>
    </div>
  </section>

  <div class="kb-chat-layout" :class="{ 'is-collapsed': !historyOpen }">
    <section v-show="historyOpen" class="card kb-history">
      <div class="kb-history-toolbar">
        <div class="kb-history-search">
          <Input
            v-model="historyQuery"
            placeholder="搜索历史记录"
            aria-label="搜索历史记录"
          />
        </div>
      </div>
      <div class="kb-history-list">
        <p v-if="!historyItems.length && !historyLoading" class="msg">
          {{ historyQuery.trim() ? "没有匹配的历史记录" : "还没有问答记录" }}
        </p>
        <div
          v-for="item in historyItems"
          :key="item.id"
          class="kb-history-item"
          :class="{ active: item.id === conversationId }"
        >
          <button
            type="button"
            class="kb-history-open"
            @click="openConversation(item.id)"
          >
            <span class="kb-history-title">{{ item.title }}</span>
          </button>
          <div
            class="kb-history-actions"
            :class="{ 'is-open': historyMenuId === item.id }"
          >
            <Button
              variant="ghost"
              size="icon-xs"
              class="icon-btn kb-history-more"
              type="button"
              aria-label="更多操作"
              title="更多"
              :aria-expanded="historyMenuId === item.id"
              @click="toggleHistoryMenu($event, item.id)"
            >
              <EllipsisVertical class="size-4" />
            </Button>
            <div
              v-if="historyMenuId === item.id"
              class="kb-history-menu"
              @click.stop
            >
              <button
                type="button"
                class="kb-history-menu-item"
                @click="askRename(item)"
              >
                <Pencil class="size-3.5" />
                重命名
              </button>
              <button
                type="button"
                class="kb-history-menu-item is-danger"
                @click="askDelete(item)"
              >
                <Trash2 class="size-3.5" />
                删除
              </button>
            </div>
          </div>
        </div>
        <Button
          v-if="historyHasMore"
          variant="outline"
          type="button"
          class="mt-2 w-full"
          :disabled="historyLoading"
          @click="loadMoreHistory"
        >
          加载更多
        </Button>
      </div>
    </section>

    <section class="card chat-card">
      <div class="chat-header">
        <Button
          variant="ghost"
          size="icon"
          class="icon-btn"
          type="button"
          :aria-label="historyOpen ? '收起历史' : '展开历史'"
          :aria-expanded="historyOpen"
          :title="historyOpen ? '收起历史' : '展开历史'"
          @click="toggleHistory"
        >
          <PanelLeft class="size-4" />
        </Button>
        <Button
          v-if="canStartNewChat"
          variant="ghost"
          size="icon"
          class="icon-btn"
          type="button"
          aria-label="新对话"
          title="新对话"
          @click="startNewChat"
        >
          <Plus class="size-4" />
        </Button>
        <h2 class="chat-title">{{ chatTitle }}</h2>
      </div>
      <div ref="thread" class="chat-thread">
        <div v-if="!messages.length" class="msg">
          可以问：「{{
            exampleQuestions.join("」「")
          }}」。有转写或导入文档的任务会作为资料。
        </div>
        <div
          v-for="(item, index) in messages"
          :key="index"
          class="chat-row"
          :class="item.role"
        >
          <div class="chat-bubble">
            <div
              v-if="item.role === 'assistant'"
              class="chat-body"
              v-html="formatChatHtml(item.content)"
            />
            <div v-else class="chat-body">{{ item.content }}</div>
            <div v-if="item.citations?.length" class="chat-cites">
              <Button
                variant="ghost"
                type="button"
                class="cite-toggle h-auto justify-self-start px-0 text-muted-foreground hover:bg-transparent hover:text-foreground"
                :aria-expanded="Boolean(item.citationsOpen)"
                :aria-label="item.citationsOpen ? '收起依据' : '展开依据'"
                :title="item.citationsOpen ? '收起依据' : '展开依据'"
                @click="toggleCitations(index)"
              >
                <ChevronRight
                  class="size-4 transition-transform"
                  :class="{ 'rotate-90': item.citationsOpen }"
                  aria-hidden="true"
                />
                依据（{{ item.citations.length }}）
              </Button>
              <div v-show="item.citationsOpen" class="cite-list">
                <router-link
                  v-for="(hit, cIndex) in item.citations"
                  :key="cIndex"
                  class="cite-link"
                  :to="jobLink(hit)"
                >
                  <Badge variant="secondary">{{ hit.kind_label }}</Badge>
                  <span v-if="citePlace(hit)" class="cite-time">{{
                    citePlace(hit)
                  }}</span>
                  {{ hit.title }} · {{ hit.snippet }}
                </router-link>
              </div>
            </div>
          </div>
        </div>
        <div v-if="loading" class="msg">正在根据知识库生成答案…</div>
      </div>
      <Textarea
        v-model="input"
        rows="3"
        placeholder="问知识库… Shift+Enter 换行，Enter 发送"
        :disabled="loading"
        @keydown="onKeydown"
      />
      <div class="row mt-3">
        <Button type="button" :disabled="loading || !input.trim()" @click="send"
          >发送</Button
        >
      </div>
    </section>
  </div>

  <h3 v-if="total">当前领域已收录 {{ total }} 个任务</h3>
  <p v-else class="msg">当前领域还没有转写任务。切换领域或先完成对应任务。</p>
  <section v-for="doc in documents" :key="doc.job_id" class="card mt-2">
    <div class="list-item border-0 p-0!">
      <div class="list-main">
        <router-link :to="jobLink(doc)"
          ><strong>{{ doc.title }}</strong></router-link
        >
        <div class="msg">
          {{ doc.segment_count }} 段转写 · {{ doc.preview }}
        </div>
      </div>
    </div>
  </section>
  <Pagination
    v-if="total > 0"
    :total="total"
    :page="page"
    :page-size="pageSize"
    @update:page="goPage"
    @update:page-size="changePageSize"
  />
  <div v-if="!total" class="card">
    <p class="msg">还没有转写。完成任务后会自动进入这个私有知识库。</p>
  </div>

  <Dialog
    :open="Boolean(deleting)"
    @update:open="
      (next: boolean) => {
        if (!next) deleting = null;
      }
    "
  >
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>确认删除</DialogTitle>
        <DialogDescription>
          确定删除「{{ deleting?.title || "未命名对话" }}」？删除后无法恢复。
        </DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <Button
          variant="outline"
          type="button"
          :disabled="deletingBusy"
          @click="deleting = null"
          >取消</Button
        >
        <Button
          variant="destructive"
          type="button"
          :disabled="deletingBusy"
          @click="confirmDelete"
          >确认删除</Button
        >
      </DialogFooter>
    </DialogContent>
  </Dialog>

  <Dialog
    :open="Boolean(renaming)"
    @update:open="
      (next: boolean) => {
        if (!next) renaming = null;
      }
    "
  >
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>重命名对话</DialogTitle>
        <DialogDescription
          >修改这条历史记录在列表里显示的标题。</DialogDescription
        >
      </DialogHeader>
      <Input
        v-model="renameDraft"
        maxlength="255"
        aria-label="对话标题"
        :disabled="renamingBusy"
        @keydown.enter="confirmRename"
      />
      <DialogFooter>
        <Button
          variant="outline"
          type="button"
          :disabled="renamingBusy"
          @click="renaming = null"
          >取消</Button
        >
        <Button
          type="button"
          :disabled="renamingBusy || !renameDraft.trim()"
          @click="confirmRename"
          >保存</Button
        >
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
