from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
PROJECT_ROOT = Path(__file__).parent.parent
print(PROJECT_ROOT)
ENV_FILE=PROJECT_ROOT/".env"
print(ENV_FILE)


class Settings(BaseSettings):
    model_config=SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore"
    )
    AIROBOT_LLM_BASE_URL: str
    AIROBOT_LLM_API_KEY: str
    AIROBOT_LLM_MODEL: str
    AIROBOT_EMBEDDING_BASE_URL: str
    AIROBOT_EMBEDDING_API_KEY: str
    AIROBOT_EMBEDDING_MODEL: str
    provider: str = "openai"
    # Embedding
    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str
    USE_CREW: bool = False
    top_k: int
    chunk_size: int
    chunk_overlap: int
    memory_max_turns: int = 20
    retry_max_wait: int = 10
    POSTGRES_URI: str
    DEBUG: bool = False
    APP_VERSION: str = "0.1.0"
    MILVUS_URI: str = "http://localhost:19530"
    COLLECTION_NAME: str = "customer_milvus_collection"
    DIM: int = 1024

@lru_cache
def get_settings()->Settings:
    return Settings()

settings=get_settings()