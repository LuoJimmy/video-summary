# Video Summary

本地视频/流媒体转写与 AI 时间轴总结工作台。支持本地文件、HTTP 视频、HLS、B 站，以及可配置登录态的多站点页面。

## 主要功能

- 本地与在线视频、音频均可转写，并生成带时间轴的 AI 总结
- 点击段落或关键句，即可跳回原片对应位置
- 已处理内容可入库，基于转写做本机知识库问答

## 产品截图

![创建任务](http://my-images-space.oss-cn-shenzhen.aliyuncs.com/video-summay/ScreenShot_2026-09-05_104030_755.png)
![任务详情](http://my-images-space.oss-cn-shenzhen.aliyuncs.com/video-summay/localhost_5173_knowledge.png)
![知识库](http://my-images-space.oss-cn-shenzhen.aliyuncs.com/video-summay/ScreenShot_2026-09-05_104445_168.png)

## 环境

- Python 3.11+（推荐 3.12）
- Node.js 18+
- FFmpeg（抽音，未安装时任务会在抽音阶段失败并给出提示）

## 启动

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8765
```

另开终端：

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 Vite 提示的地址（默认 `http://127.0.0.1:5173`）。

## 使用顺序

1. 转写默认本机 SenseVoice Small Q8，也可改选 Whisper。进程启动后会后台预拉 SenseVoice。总结在「设置」填写 OpenAI 兼容接口。可按需打开自动 AI 校对。
2. 在「站点与登录」把浏览器 Cookie 粘进对应登录档案。
3. 在「任务」粘贴页面/媒体地址，或上传本地文件。
4. 若站点页解析不出流地址，把 Network 里的 m3u8/mp4 填进「媒体地址覆盖」。
5. 在任务详情点击总结时间轴，定位原片位置。
6. 在「知识库」用已配置的总结模型，基于本机转写对话生成答案。

## Docker

数据目录和下载目录都可改宿主机路径，容器内分别挂到 `/data` 与 `/downloads`。

```bash
# 默认：./data 存库和模型，./downloads 存抽音/上传文件
docker compose up --build

# 自定义下载目录和端口
VIDEO_SUMMARY_DOWNLOADS=/mnt/video-cache \
VIDEO_SUMMARY_DATA=/mnt/video-summary-data \
PORT=8765 \
docker compose up --build
```

浏览器打开 `http://127.0.0.1:8765`。只构建镜像：

```bash
docker build -t video-summary:latest .
docker run --rm -p 8765:8765 \
  -e DATA_DIR=/data \
  -e DOWNLOAD_DIR=/downloads \
  -v "$PWD/data:/data" \
  -v "$PWD/downloads:/downloads" \
  video-summary:latest
```

### GitHub Packages

正式镜像发布在 GitHub Container Registry，标签与仓库 tag 对齐：

```bash
docker pull ghcr.io/luojimmy/video-summary:1.0.0
docker run --rm -p 8765:8765 \
  -e DATA_DIR=/data \
  -e DOWNLOAD_DIR=/downloads \
  -v "$PWD/data:/data" \
  -v "$PWD/downloads:/downloads" \
  ghcr.io/luojimmy/video-summary:1.0.0
```

也可使用 `ghcr.io/luojimmy/video-summary:latest`。私有仓库拉取前先 `docker login ghcr.io`。

环境变量：`DATA_DIR`（数据库、Whisper 模型、Hugging Face 缓存），`DOWNLOAD_DIR`（任务音频和上传文件），`VIDEO_SUMMARY_DATA` / `VIDEO_SUMMARY_DOWNLOADS`（compose 宿主机路径），`PORT`，`PREFETCH_SENSEVOICE`（默认开启；设为 `0` 可关闭启动时后台预拉 SenseVoice）。

### 离线镜像包（极空间等）

需要 Docker Desktop 或已启用 `buildx` 的 Docker Engine。macOS / Linux 直接运行；Windows 用 Git Bash 或 WSL。打非本机架构（例如 Apple Silicon 打 amd64）时，Docker Desktop 一般已带 QEMU。

```bash
# 同时打 linux/amd64 与 linux/arm64
./script/build-docker.sh

# 只打其中一个
./script/build-docker.sh amd64
./script/build-docker.sh arm64
```

产物在 `dist/`：

- `video-summary-linux-amd64.tar`：Intel / AMD NAS
- `video-summary-linux-arm64.tar`：ARM NAS

这是 `docker save` 单架构包（含 `manifest.json`），给极空间「导入镜像」或 `docker load -i` 使用。导入后镜像名为 `video-summary:latest`。多架构 OCI 包极空间通常导入失败，不要用 `docker buildx --output type=oci` 的结果去导。

默认基础镜像走 DaoCloud。能直连 Docker Hub 时可覆盖：

```bash
NODE_IMAGE=node:22-alpine PYTHON_IMAGE=python:3.12-slim ./script/build-docker.sh
```

可选环境变量：`IMAGE_NAME`（默认 `video-summary:latest`）、`DIST_DIR`、`BUILDER`（本机有 `mybuilder` 时会自动用）。构建还要访问 npm、Debian apt、PyPI；Docker 若配置了失效代理，需先修好网络。一次打两个架构大约十几分钟，并占用数 GB 磁盘。

## 测试

```bash
cd backend
source .venv/bin/activate
pytest -q
```

```bash
cd frontend
npm test
```

## 更新日志

各版本变化见 [CHANGELOG.md](CHANGELOG.md)。应用内「设置 → 关于 → 更新日志」也会展示同一份内容。

## 协议

本项目采用 [PolyForm Noncommercial License 1.0.0](LICENSE)。

除版权人（原作者 Jimmy Luo）外，不得将本软件用于商业目的。个人学习、研究、业余使用可以按协议使用、修改与分发。商业使用须事先取得版权人书面许可。

## 合规

只处理你有权访问的内容。系统只会使用你手动配置的 Cookie/Header，不会绕过付费或解密 DRM。
