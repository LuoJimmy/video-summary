ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.12-slim

FROM ${NODE_IMAGE} AS frontend
WORKDIR /ui
COPY CHANGELOG.md /CHANGELOG.md
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE}
LABEL org.opencontainers.image.title="Video Summary" \
      org.opencontainers.image.description="本地视频/流媒体转写与 AI 时间轴总结工作台" \
      org.opencontainers.image.source="https://github.com/LuoJimmy/video-summary" \
      org.opencontainers.image.licenses="PolyForm-Noncommercial-1.0.0" \
      org.opencontainers.image.version="1.0.0"
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=frontend /ui/dist ./static

ENV DATA_DIR=/data \
    DOWNLOAD_DIR=/downloads \
    STATIC_DIR=/app/static \
    HF_HOME=/data/hf \
    HF_ENDPOINT=https://hf-mirror.com \
    CORS_ORIGINS=http://127.0.0.1:8765,http://localhost:8765

EXPOSE 8765
VOLUME ["/data", "/downloads"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765"]
