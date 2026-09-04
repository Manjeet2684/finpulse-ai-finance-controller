from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "fixtures" / "v1"
ARTIFACT_DIR = ROOT / "artifacts"
DB_PATH = ROOT / "finpulse.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    finpulse_database_url: str = f"sqlite:///{DB_PATH.as_posix()}"
    finpulse_llm_concurrency: int = 5


def get_settings() -> Settings:
    return Settings()
