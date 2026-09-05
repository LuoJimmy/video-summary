<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import { BookOpen, Globe, ListVideo, Settings } from "@lucide/vue";
import { Toaster } from "@/components/ui/sonner";
import "vue-sonner/style.css";

const route = useRoute();
const jobsNavActive = computed(
  () => route.path === "/" || route.path.startsWith("/jobs/")
);
const settingsNavActive = computed(() => route.path.startsWith("/settings"));
</script>

<template>
  <div class="shell">
    <aside class="nav">
      <div class="brand">Video Summary</div>
      <nav class="nav-links">
        <router-link to="/" :class="{ 'router-link-active': jobsNavActive }">
          <ListVideo class="nav-icon" aria-hidden="true" />
          <span>任务</span>
        </router-link>
        <router-link to="/knowledge">
          <BookOpen class="nav-icon" aria-hidden="true" />
          <span>知识库</span>
        </router-link>
        <router-link to="/sites">
          <Globe class="nav-icon" aria-hidden="true" />
          <span>站点</span>
        </router-link>
        <router-link
          to="/settings"
          :class="{ 'router-link-active': settingsNavActive }"
        >
          <Settings class="nav-icon" aria-hidden="true" />
          <span>设置</span>
        </router-link>
      </nav>
    </aside>
    <main class="main">
      <router-view />
    </main>
    <Toaster />
  </div>
</template>
