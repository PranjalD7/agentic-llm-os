from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    daemon_host: str = "127.0.0.1"
    daemon_port: int = 7777
    database_url: str = "sqlite:///./llmos.db"
    workspace_dir: Path = Path("./workspace")
    step_timeout_seconds: int = 3000
    approval_timeout_seconds: int = 360000

    # LLM planner (Ollama)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen3-coder:30b"
    llm_planner_enabled: bool = True
    llm_max_retries: int = 3


settings = Settings()
