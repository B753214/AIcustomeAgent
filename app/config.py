from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- LLM（必选）----------
    AIROBOT_LLM_BASE_URL: str
    AIROBOT_LLM_API_KEY: str
    AIROBOT_LLM_MODEL: str
    provider: str = "openai"

    # ---------- Embedding（必选；AIROBOT_EMBEDDING_* 为主）----------
    AIROBOT_EMBEDDING_BASE_URL: str
    AIROBOT_EMBEDDING_API_KEY: str
    AIROBOT_EMBEDDING_MODEL: str
    # 兼容别名：未填时自动回落到 AIROBOT_EMBEDDING_*
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""

    # ---------- 数据存储 ----------
    POSTGRES_URI: str
    MILVUS_URI: str = "http://localhost:19530"
    COLLECTION_NAME: str = "customer_milvus_collection"
    DIM: int = 1024

    # ---------- RAG / 分块（top_k / chunk_* 必填）----------
    top_k: int
    chunk_size: int
    chunk_overlap: int
    pdf_chunk_size: int = 800
    pdf_chunk_overlap: int = 80
    pdf_section_max_chars: int = 1000
    pdf_section_min_chars: int = 150
    hybrid_enabled: bool = True
    hybrid_vector_top_k: int = 20
    hybrid_bm25_top_k: int = 20
    hybrid_fusion_top_k: int = 20
    rerank_enabled: bool = False
    rerank_provider: str = "local"
    rerank_model: str = "qwen3.7-text-rerank"
    rerank_api_key: str = ""

    # ---------- Crew / 会话 / 稳定性 ----------
    use_crew: bool = False
    crew_tools_ready: bool = True
    memory_max_turns: int = 5
    retry_attempts: int = 3
    retry_max_wait: int = 3
    tool_timeout_sec: float = 30
    # Mock 订单查询失败概率（0~1）；默认 0 保证离线测试可复现
    order_mock_fail_rate: float = 0.0
    ratelimit_enabled: bool = True
    ratelimit_per_minute: int = 30
    cache_enabled: bool = True
    cache_threshold: float = 0.75
    cache_lexical_threshold: float = 0.5
    max_entries_cache: int = 1000
    api_key_enabled: bool = False
    service_api_key: str = ""
    DEBUG: bool = True
    APP_VERSION: str = "0.1.0"

    # ---------- 告警 Agent ----------
    alarm_mcp_enabled: bool = True
    alarm_mcp_host: str = "pre-mcp.alibaba-inc.com"
    alarm_mcp_path: str = "/info-plate-mcp/mcp"
    alarm_mcp_token: str = ""
    alarm_mcp_timeout_sec: int = 15
    alarm_mcp_verify_ssl: bool = False
    alarm_browser_enabled: bool = True
    alarm_browser_profile_dir: str = ".browser_profile"
    alarm_info_plate_user: str = ""
    alarm_info_plate_password: str = ""
    alarm_browser_timeout_sec: int = 120
    alarm_browser_headless: bool = True
    alarm_info_plate_base_url: str = "https://info-plate.fc.alibaba-inc.com"
    alarm_skip_when_zero_count: bool = True
    alarm_report_format: str = "markdown"
    alarm_mock_enabled: bool = False
    alarm_replan_enabled: bool = False
    alarm_detail_page_size: int = 20
    alarm_replan_max_pages: int = 2
    alarm_replan_max_playbook_switch: int = 1

    # ---------- Harness ----------
    harness_runtime: bool = False

    # ---------- 闲聊工具 ----------
    amap_mcp_enabled: bool = False
    amap_maps_api_key: str = ""
    amap_mcp_url: str = "https://mcp.amap.com/mcp"
    weather_api_key: str = ""

    @model_validator(mode="after")
    def fill_embedding_aliases(self) -> "Settings":
        """embedding_* 未配置时，回落到 AIROBOT_EMBEDDING_*，避免双份必填。"""
        if not self.embedding_base_url:
            object.__setattr__(self, "embedding_base_url", self.AIROBOT_EMBEDDING_BASE_URL)
        if not self.embedding_api_key:
            object.__setattr__(self, "embedding_api_key", self.AIROBOT_EMBEDDING_API_KEY)
        if not self.embedding_model:
            object.__setattr__(self, "embedding_model", self.AIROBOT_EMBEDDING_MODEL)
        return self


def _format_settings_error(exc: ValidationError) -> str:
    lines = [
        "配置加载失败：请复制 .env.example 为 .env，并填写下列必选项。",
        "完整字段说明见 docs/config.md。",
        "",
    ]
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()))
        msg = err.get("msg", "")
        lines.append(f"  - {loc}: {msg}")
    lines.append("")
    lines.append("必填示例字段：AIROBOT_LLM_*、AIROBOT_EMBEDDING_*、POSTGRES_URI、TOP_K、CHUNK_SIZE、CHUNK_OVERLAP")
    return "\n".join(lines)


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise RuntimeError(_format_settings_error(exc)) from exc


settings = get_settings()
