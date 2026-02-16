"""Application configuration."""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


def _data_dir() -> Path:
    base = Path(__file__).resolve().parent.parent
    data = base / "data"
    data.mkdir(parents=True, exist_ok=True)
    return data


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MUZIC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8484
    debug: bool = False

    data_dir: Path = _data_dir()
    backgrounds_dir: Path | None = None
    logs_dir: Path | None = None

    def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)
        self.backgrounds_dir = self.backgrounds_dir or self.data_dir / "backgrounds"
        self.logs_dir = self.logs_dir or self.data_dir / "logs"
        self.backgrounds_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
