from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://hungry:hungry@localhost:5432/hungry"
    tei_url: str = "http://localhost:8081"

    # The backend switch. Everything downstream reads resolved_* below so the
    # rest of the app never branches on the backend name.
    llm_backend: Literal["llama", "hosted"] = "llama"

    llm_base_url: str = "http://localhost:8000/v1"
    llm_model: str = "qwen2.5-3b-instruct"
    llm_api_key: str = "sk-noauth"

    hosted_base_url: str = ""
    hosted_model: str = ""
    hosted_api_key: str = ""

    @property
    def resolved_base_url(self) -> str:
        return self.hosted_base_url if self.llm_backend == "hosted" else self.llm_base_url

    @property
    def resolved_model(self) -> str:
        return self.hosted_model if self.llm_backend == "hosted" else self.llm_model

    @property
    def resolved_api_key(self) -> str:
        return self.hosted_api_key if self.llm_backend == "hosted" else self.llm_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
