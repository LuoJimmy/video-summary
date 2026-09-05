from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Video Summary"
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    download_dir: str = ""
    static_dir: str = ""
    database_url: str = ""
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8765,http://localhost:8765"
    ffmpeg_bin: str = "ffmpeg"
    default_transcribe_base_url: str = "https://api.openai.com/v1"
    default_transcribe_model: str = "sensevoice-small-q8"
    default_summarize_base_url: str = "https://api.deepseek.com/v1"
    default_summarize_model: str = "deepseek-v4-flash"
    summarize_concurrency: int = 3
    prefetch_sensevoice: bool = True

    def uploads_path(self) -> Path:
        path = Path(self.download_dir).expanduser() if self.download_dir.strip() else (self.data_dir / "uploads")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def job_workdir(self, job_id: str) -> Path:
        path = self.uploads_path() / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolve_job_audio_path(self, job_id: str, stored: str = "") -> Path:
        """容器里的 /downloads 在本机只读；旧路径找不到或不在当前抽音目录时改写到本机目录。"""
        local = self.job_workdir(job_id) / "audio.wav"
        if not (stored or "").strip():
            return local
        stored_path = Path(stored)
        try:
            if stored_path.is_file() and stored_path.stat().st_size > 0:
                stored_path.resolve().relative_to(self.uploads_path().resolve())
                return stored_path
        except (OSError, ValueError):
            pass
        name = stored_path.name if stored_path.name not in {"", ".", ".."} else "audio.wav"
        remapped = self.job_workdir(job_id) / name
        if remapped.is_file() and remapped.stat().st_size > 0:
            return remapped
        return local

    def models_path(self) -> Path:
        path = self.data_dir / "models"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolved_static_dir(self) -> Path | None:
        if not self.static_dir.strip():
            return None
        path = Path(self.static_dir)
        return path if path.exists() else None

    def model_post_init(self, __context) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_path()
        self.models_path()
        if not self.database_url:
            self.database_url = f"sqlite:///{self.data_dir / 'app.db'}"


settings = Settings()
