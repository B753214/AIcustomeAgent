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
    use_crew: bool = False
    top_k: int
    chunk_size: int
    chunk_overlap: int
    hybrid_vector_top_k: int = 15
    hybrid_enabled: bool = True
    hybrid_bm25_top_k: int = 15
    rerank_enabled:bool = False
    rerank_provider: str = "local"
    rerank_model: str = "qwen3-rerank"
    rerank_api_key: str = ""
    hybrid_fusion_top_k: int = 5
    memory_max_turns: int = 5
    retry_attempts: int = 3
    retry_max_wait: int = 3
    POSTGRES_URI: str
    DEBUG: bool = True
    APP_VERSION: str = "0.1.0"
    MILVUS_URI: str = "http://localhost:19530"
    COLLECTION_NAME: str = "customer_milvus_collection"
    DIM: int = 1024
    crew_tools_ready: bool = True
    ratelimit_enabled: bool = True  # 开发期可改 False 关掉
    ratelimit_per_minute: int = 30  # 60 秒内最多 30 次

    # 缓存配置
    cache_enabled: bool = True
    cache_threshold: float = 0.75  # 向量相似度下限
    cache_lexical_threshold: float = 0.5  # 词面重叠下限
    max_entries_cache: int = 1000

    api_key_enabled: bool = False  # 开发默认关
    service_api_key: str = ""  # 服务端要求的 Key

    # 监控告警配置（MCP）
    alarm_mcp_enabled: bool = True
    alarm_mcp_host: str = "pre-mcp.alibaba-inc.com"
    alarm_mcp_path: str = "/info-plate-mcp/mcp"
    alarm_mcp_token: str = ""  # .env: ALARM_MCP_TOKEN=...
    alarm_mcp_timeout_sec: int = 15
    alarm_mcp_verify_ssl: bool = False

    # Day8：浏览器降级（Playwright）；MCP 失败后固定回退浏览器
    alarm_browser_enabled: bool = True
    alarm_browser_profile_dir: str = ".browser_profile"
    alarm_info_plate_user: str = ""
    alarm_info_plate_password: str = ""
    alarm_browser_timeout_sec: int = 120
    alarm_browser_headless: bool = True

    # Day9：报告形态
    alarm_skip_when_zero_count: bool = True
    alarm_report_format: str = "markdown"  # rca | markdown

    #高德mcp
    amap_mcp_enabled: bool = False
    amap_maps_api_key: str = ""
    amap_mcp_url: str = "https://mcp.amap.com/mcp"
    weather_api_key: str = ""

@lru_cache
def get_settings()->Settings:
    return Settings()

settings=get_settings()