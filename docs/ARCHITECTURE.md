# 架构说明

```mermaid
flowchart LR
  UI[Vue 配置与任务台] --> API[FastAPI]
  API --> Sites[站点 / 登录档案]
  API --> Jobs[任务管线]
  Jobs --> Adapter[站点适配器]
  Adapter --> Media[FFmpeg 抽音]
  Adapter --> Docs[文档正文提取]
  Media --> ASR[OpenAI 兼容转写]
  ASR --> LLM[按分段索引总结]
  Docs --> LLM
  Docs --> KB[知识库原文]
  LLM --> Map[程序回填时间码或 locator]
  Map --> UI
  KB --> UI
```

## 分层

1. 接入层：`generic` / `xiaoe` / `yueniu` / `bilibili` 识别 URL。音视频提取或接收媒体地址；generic 下的普通网页和 PDF/Word 等走文档分支。B 站走公开稿件接口取 DASH 音轨。
2. 媒体层：FFmpeg 把文件或 HLS 抽成 16kHz 单声道 WAV。转写完成后同一份 WAV 会压成 opus 归档（`app/services/audio_store.py`，约 WAV 的十分之一），任务目录里只留归档；「重新转写」时先解回 WAV 再交给转写器，因此不依赖原始地址是否仍然有效。设置页「关于」可以查看归档占用并手动清理。播放时另会在任务目录缓存 `play.mp4`，缓存总量超上限时按「最久没播放」淘汰（`app/services/storage.py` 的 `enforce_play_quota`），上限存在设置表 `play_quota_mb` 里，为 0 表示不限制。
3. 文档层：`pymupdf` / `python-docx` / `trafilatura` 抽正文。扫描 PDF、旧版 `.doc` 为 `DATA_DIR/plugins` 里的按需插件（RapidOCR、LibreOffice）。
4. 转写层：兼容 `/v1/audio/transcriptions` 的 `verbose_json` 分段。文档把段落写成同样的 `TranscriptSegment`，带 `locator`。
5. 总结层：音视频默认总结；文档默认直接入库原文，勾选后才调用模型。模型只输出分段编号；`timeline.attach_timestamps` 映射秒数或页/段 locator。
6. 展示层：任务详情把章节、要点做成可点击定位；知识库基于本机转写和文档做检索增强对话，问答写入本地会话表，可搜索和删除。

默认 Docker 镜像只安装 FFmpeg 和 `libgomp1`，不装 Tesseract / LibreOffice。OCR 与旧版 `.doc` 在任务需要时（或设置页预装）下载到 `DATA_DIR/plugins`，容器重建后仍然保留。

容器同样看不到宿主机文件系统。要处理宿主机上的文件，把宿主机目录挂到容器（compose 变量 `VIDEO_SUMMARY_MEDIA` → `/media`，即 `MEDIA_DIR`）：`app/services/localfs.py` 会列出该根目录下的文件夹与受支持文件，界面在「本地任务」里多选或整目录加入，勾选后按容器内路径建任务，再交给 `generic` 适配器按本地媒体处理。浏览被限制在根目录内，容器只读挂载。

## 登录态打通

`AuthProfile` 保存一套 Cookie。`Site.domain_patterns` 决定哪些主机名使用该档案。小鹅通短链域与店铺域、约牛页面域与直播域都可以挂到同一档案，无需重复粘贴。

## 数据与索引

数据库是 `DATA_DIR` 下的 SQLite。新库由 `Base.metadata.create_all` 按模型建表；老库在启动时走 `app/database.py` 的 `migrate_job_columns()`：用 `PRAGMA table_info` 补齐缺的列，再用 `CREATE INDEX IF NOT EXISTS` 补建索引（`JOB_INDEXES`）。

`jobs` 上的索引都对应真实查询：`status`（任务列表按状态筛选）、`coalesce(source_created_at, created_at)` + `created_at` + `id`（任务列表默认按原片发布时间倒序、日期区间筛选：列顺序要和 SQL 里的 `ORDER BY` 完全对齐，否则 SQLite 会退回「扫表 + 临时排序」）、`created_at` + `id`、`updated_at`（知识库分页）、`domain_id` + `updated_at`（知识库按领域收窄）、`schedule_log_id`（定时汇总反查同批任务）。同一索引名定义变了会在启动时自动 `DROP` 重建，所以调整索引不需要手写数据迁移。加新的过滤或排序条件时，同步在 `JOB_INDEXES` 与 `Job.__table_args__` 两处补索引，别让查询退回全表扫描。

## 知识库检索

检索与问答都在进程内完成，没有向量库：`app/services/knowledge.py` 把每个任务切成标题 / 转写窗口 / 综述 / 章节 / 要点等切片，在「繁简归一化 + 小写」后的文本上做子串打分（整句命中 8 分，词命中 2.5 或 1.2 分），取分最高的若干条当依据。

贵的是归一化（`zhconv` 转换），不是匹配本身：本机 83 个任务、325 万字转写的真实库上，一次检索 0.39s 里有 0.32s 花在归一化，纯匹配只要 0.003s。所以 `chunk_index()` 把切片连同归一化文本缓存起来（`MAX_INDEX_JOBS` 为上限、最久未用淘汰、键是 `updated_at` + 正文长度 + 标题），首次检索照旧，之后同一任务的检索只做子串匹配：同库上从 0.39s 降到 0.01~0.02s。转写 / 综述 / 标题一变，缓存键就变，自动重建。

归一化统一走 `textnorm.match_key()`（繁简收敛 + 统一「幺/么」+ 小写）。两个坑都在 `zhconv` 上：它单趟转换不幂等（「為什麼」→「为什么」→「为什幺」），必须迭代到稳定，否则繁体提问「為什麼半年」匹配不到正文里的「为什么半年」；它的短语表还会把「么半」这类词误转成「幺半」（「那么半年」→「那幺半年」），写入路径因此按位把「么→幺」还原回去，检索键则把「幺/么」统一，老库里已经被写坏的文本不必清洗。

写入路径 `normalize_transcript()` = `apply_lexicon(to_simplified())`，转写与文档正文入库时就已经是简体；但 LLM 生成的综述 / 章节 / 要点、以及视频与网页标题没有这一步，检索侧的归一化同时给它们兜底（实测本机库里 `overview` 有 33/80 篇含非简体，转写窗口只有 1/11063）。

带关键词的搜索只对命中的任务构造 `KnowledgeDoc`（此前先把所有任务都建一遍文档再筛）；列表页不带关键词时仍走 SQL 分页（`updated_at` 索引），不加载全文。
