from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "fixtures" / "v1"
ARTIFACT_DIR = ROOT / "artifacts"
DB_PATH = ROOT / "finpulse.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    finpulse_database_url: str = f"sqlite:///{DB_PATH.as_posix()}"
    finpulse_llm_concurrency: int = 2


def get_settings() -> Settings:
    return Settings()
