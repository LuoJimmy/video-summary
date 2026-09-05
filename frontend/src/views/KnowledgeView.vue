<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  type KnowledgeDoc,
  type KnowledgeHit,
} from "../api";
import type { DomainPack } from "../utils/domain";
import { emptyDomainPack } from "../utils/domain";
import { formatChatHtml } from "../utils/highlight";
import { formatTimestamp } from "../utils/time";
import { toast } from "vue-sonner";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  citations?: KnowledgeHit[];
};

const PAGE_SIZE = 10;
const input = ref("");
const loading = ref(false);
const documents = ref<KnowledgeDoc[]>([]);
const total = ref(0);
const page = ref(1);
const messages = ref<ChatMessage[]>([]);
const thread = ref<HTMLElement | null>(null);
const domainId = ref("a-share");
const domainPresets = ref<DomainPack[]>([emptyDomainPack()]);
const exampleQuestions = ref(["这节课的核心方法是什么", "有哪些关键步骤"]);

const totalPages = computed(() =>
  Math.max(1, Math.ceil(total.value / PAGE_SIZE))
);

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
  const listed = await api.knowledge("", domainId.value, page.value, PAGE_SIZE);
  const pages = Math.max(1, Math.ceil(listed.job_count / listed.page_size));
  if (page.value > pages) {
    page.value = pages;
    const again = await api.knowledge(
      "",
      domainId.value,
      page.value,
      PAGE_SIZE
    );
    documents.value = again.documents;
    total.value = again.job_count;
    return;
  }
  documents.value = listed.documents;
  total.value = listed.job_count;
}

function goPage(next: number) {
  if (next < 1 || next > totalPages.value || next === page.value) return;
  page.value = next;
  void loadDocuments().catch((err) => {
    toast.error(err instanceof Error ? err.message : "无法加载知识库");
  });
}

async function setDomain(value: string | null) {
  const next = value || "a-share";
  if (next === domainId.value) return;
  domainId.value = next;
  page.value = 1;
  messages.value = [];
  applyExampleQuestions(currentPack());
  try {
    await loadDocuments();
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "无法加载知识库");
  }
}

onMounted(async () => {
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
    await loadDocuments();
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "无法加载知识库");
  }
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
    }));
    const result: KnowledgeChatOut = await api.knowledgeChat(
      payload,
      domainId.value
    );
    messages.value.push({
      role: "assistant",
      content: result.answer,
      citations: result.citations,
    });
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

function clearChat() {
  messages.value = [];
}

function jobLink(jobId: string, start?: number) {
  if (start !== undefined && start >= 0)
    return `/jobs/${jobId}?t=${Math.floor(start)}`;
  return `/jobs/${jobId}`;
}

async function scrollToEnd() {
  await nextTick();
  if (thread.value) thread.value.scrollTop = thread.value.scrollHeight;
}
</script>

<template>
  <h1>知识库</h1>
  <p class="sub">
    基于你本机转写的私有资料对话。答案只来自当前领域里已完成的任务，不会去网上搜。
  </p>

  <section class="card mb-3">
    <div class="field">
      <Label>内容领域</Label>
      <Select :model-value="domainId" @update:model-value="setDomain">
        <SelectTrigger class="w-full">
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

  <section class="card chat-card">
    <div ref="thread" class="chat-thread">
      <div v-if="!messages.length" class="msg">
        可以问：「{{
          exampleQuestions.join("」「")
        }}」。有转写的任务会作为资料。
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
            <div class="msg mb-1.5">依据</div>
            <router-link
              v-for="(hit, cIndex) in item.citations"
              :key="cIndex"
              class="cite-link"
              :to="jobLink(hit.job_id, hit.start)"
            >
              <Badge variant="secondary">{{ hit.kind_label }}</Badge>
              <span
                v-if="hit.kind === 'transcript' || hit.start > 0"
                class="cite-time"
                >{{ formatTimestamp(hit.start) }}</span
              >
              {{ hit.title }} · {{ hit.snippet }}
            </router-link>
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
      <Button
        variant="outline"
        type="button"
        :disabled="!messages.length"
        @click="clearChat"
        >清空对话</Button
      >
    </div>
  </section>

  <h3 v-if="total">当前领域已收录 {{ total }} 个任务</h3>
  <p v-else class="msg">当前领域还没有转写任务。切换领域或先完成对应任务。</p>
  <section v-for="doc in documents" :key="doc.job_id" class="card mt-2">
    <div class="list-item border-0 p-0!">
      <div class="list-main">
        <router-link :to="jobLink(doc.job_id)"
          ><strong>{{ doc.title }}</strong></router-link
        >
        <div class="msg">
          {{ doc.segment_count }} 段转写 · {{ doc.preview }}
        </div>
      </div>
    </div>
  </section>
  <div v-if="total > 0" class="pager">
    <span class="msg"
      >共 {{ total }} 条<template v-if="totalPages > 1"
        >，第 {{ page }} / {{ totalPages }} 页</template
      ></span
    >
    <template v-if="totalPages > 1">
      <Button
        variant="outline"
        type="button"
        :disabled="page <= 1"
        @click="goPage(page - 1)"
        >上一页</Button
      >
      <Button
        variant="outline"
        type="button"
        :disabled="page >= totalPages"
        @click="goPage(page + 1)"
        >下一页</Button
      >
    </template>
  </div>
  <div v-if="!total" class="card">
    <p class="msg">还没有转写。完成任务后会自动进入这个私有知识库。</p>
  </div>
</template>
