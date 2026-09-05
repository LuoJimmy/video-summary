import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import KnowledgeView from "./views/KnowledgeView.vue";
import JobsView from "./views/JobsView.vue";
import JobDetailView from "./views/JobDetailView.vue";
import SitesView from "./views/SitesView.vue";
import SettingsView from "./views/SettingsView.vue";
import ChangelogView from "./views/ChangelogView.vue";
import { applyTheme, readTheme } from "./utils/theme";
import "./styles.css";

applyTheme(readTheme());

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: JobsView },
    { path: "/knowledge", component: KnowledgeView },
    { path: "/jobs/:id", component: JobDetailView },
    { path: "/sites", component: SitesView },
    { path: "/settings", component: SettingsView },
    { path: "/settings/changelog", component: ChangelogView },
  ],
});

createApp(App).use(router).mount("#app");
