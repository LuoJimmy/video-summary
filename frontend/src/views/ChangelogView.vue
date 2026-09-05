<script setup lang="ts">
import { ChevronLeft } from "@lucide/vue";
import { Button } from "@/components/ui/button";
import { loadChangelog } from "../utils/changelog";

const releases = loadChangelog();
</script>

<template>
  <div>
    <div class="page-title">
      <Button variant="ghost" size="icon" class="icon-btn" as-child>
        <router-link to="/settings" aria-label="返回设置" title="返回设置">
          <ChevronLeft />
        </router-link>
      </Button>
      <h1>更新日志</h1>
    </div>
    <p class="sub">按版本记录功能变化，最新版本在最前。</p>

    <section
      v-for="release in releases"
      :key="release.version"
      class="card changelog-release"
    >
      <div class="changelog-head">
        <h3>{{ release.version }}</h3>
        <p class="changelog-date">{{ release.date }}</p>
      </div>
      <p v-if="release.summary" class="changelog-summary">
        {{ release.summary }}
      </p>
      <div
        v-for="section in release.sections"
        :key="section.title"
        class="changelog-section"
      >
        <h4>{{ section.title }}</h4>
        <ul>
          <li v-for="item in section.items" :key="item">{{ item }}</li>
        </ul>
      </div>
    </section>
  </div>
</template>
