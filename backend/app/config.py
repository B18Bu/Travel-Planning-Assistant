from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import urlparse

# 固定指向 backend/.env，避免 .env 读取依赖当前工作目录（README 从仓库根目录启动）。
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    """服务端运行配置；外部密钥只允许由后端环境变量读取。"""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    app_env: str = "development"
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # 和风天气逐日预报 API 的服务端密钥，默认空值；仅在后端使用，不得暴露。
    heweather_api_key: str = ""
    # 和风天气固定 HTTPS API 域名，默认值：https://pb5ctx5qqr.re.qweatherapi.com；仅由后端控制，不接受客户端覆盖。
    heweather_base_url: str = "https://pb5ctx5qqr.re.qweatherapi.com"
    # 高德地理编码、驾车路线和 POI 文本搜索 API 的服务端密钥，默认空值；仅在后端使用，不得暴露。
    amap_api_key: str = ""
    # 高德地图固定 HTTPS API 域名，默认值：https://restapi.amap.com；仅由后端控制，不接受客户端覆盖。
    amap_base_url: str = "https://restapi.amap.com"

    # MinerU 云端 PDF 解析服务密钥，默认空值；仅在后端使用，不得暴露。
    mineru_api_key: str = ""
    # MinerU 固定 HTTPS API 域名，默认值：https://mineru.net；仅由后端控制，不接受客户端覆盖。
    mineru_base_url: str = "https://mineru.net"
    # Qwen-VL 图表 OCR 服务密钥，默认空值；仅在后端使用，不得暴露。
    qwen_vl_api_key: str = ""
    # Qwen-VL 固定 HTTPS API 域名，默认值：https://dashscope.aliyuncs.com/compatible-mode/v1；仅由后端控制，不接受客户端覆盖。
    qwen_vl_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # Qwen-VL 图表 OCR 模型，默认值：qwen-vl-max；仅由后端控制，不接受客户端覆盖。
    qwen_vl_model: str = "qwen-vl-max"
    # DeepSeek 大模型润色的服务端密钥，默认空值；仅在后端使用，不得暴露。
    deepseek_api_key: str = ""
    # DeepSeek 固定 HTTPS API 域名，默认值：https://api.deepseek.com；仅由后端控制，不接受客户端覆盖。
    deepseek_base_url: str = "https://api.deepseek.com"
    # DeepSeek 润色模型，默认值：deepseek-chat；仅由后端控制，不接受客户端覆盖。
    deepseek_model: str = "deepseek-chat"
    # DeepSeek 单次生成最大 token 数，默认值：2000，范围：256—8192；仅由后端控制，不接受客户端覆盖。
    deepseek_max_tokens: int = Field(default=2000, ge=256, le=8192)
    # DeepSeek 单次生成请求总超时，单位为秒，默认值：60.0；仅由后端控制，不接受客户端覆盖。
    deepseek_timeout_seconds: float = Field(default=60.0, gt=0)
    # 本地 BGE embedding 模型路径，默认值：D:\作业\model\bge-small-zh-v1.5；仅在后端读取。
    bge_model_path: str = r"D:\作业\model\bge-small-zh-v1.5"
    # 文档文件、解析产物和向量索引目录，默认值：backend/data；仅在后端读取。
    document_data_dir: str = str(Path(__file__).resolve().parents[1] / "data")
    # Chroma 文档集合名称，默认值：travel_documents；仅由后端控制，不接受客户端覆盖。
    chroma_collection_name: str = "travel_documents"
    # 单个文档最大上传字节数，默认值：20 MiB；仅由后端控制，不接受客户端覆盖。
    document_max_upload_bytes: int = Field(
        default=20 * 1024 * 1024, gt=0, le=100 * 1024 * 1024
    )
    # 单次文档批量上传最大文件数，默认值：10，范围：1—20；仅由后端控制，不接受客户端覆盖。
    document_batch_max_files: int = Field(default=10, ge=1, le=20)
    # 知识检索最终返回结果数，默认值：12，范围：1—50；仅由后端控制，不接受客户端覆盖。
    knowledge_search_result_limit: int = Field(default=12, ge=1, le=50)

    # 所有外部 API HTTP 连接建立超时，单位为秒，默认值：3.0；仅由后端控制，不接受客户端覆盖。
    external_connect_timeout_seconds: float = 3.0
    # 所有外部 API HTTP 响应读取超时，单位为秒，默认值：8.0；仅由后端控制，不接受客户端覆盖。
    external_read_timeout_seconds: float = 8.0
    # 所有外部 API 单次请求总超时，单位为秒，默认值：10.0；仅由后端控制，不接受客户端覆盖。
    external_total_timeout_seconds: float = 10.0
    # 和风天气及高德 API 的最大请求尝试次数，单位为次，默认值：3；仅重试受控瞬时错误；仅由后端控制，不接受客户端覆盖。
    external_max_attempts: int = Field(default=3, ge=1, le=3)
    # 和风天气或高德 API 连续失败的熔断阈值，单位为次，默认值：3；仅由后端控制，不接受客户端覆盖。
    circuit_breaker_failure_threshold: int = Field(default=3, gt=0)
    # 和风天气或高德 API 熔断保持时长，单位为秒，默认值：60；仅由后端控制，不接受客户端覆盖。
    circuit_breaker_open_seconds: int = Field(default=60, gt=0)

    # 和风天气逐日预报结果的进程内缓存 TTL，单位为秒，默认值：1800；仅由后端控制，不接受客户端覆盖。
    weather_cache_ttl_seconds: int = Field(default=1800, gt=0)
    # 高德地理编码结果的进程内缓存 TTL，单位为秒，默认值：604800；仅由后端控制，不接受客户端覆盖。
    amap_geocode_cache_ttl_seconds: int = Field(default=604800, gt=0)
    # 高德驾车路线结果的进程内缓存 TTL，单位为秒，默认值：900；仅由后端控制，不接受客户端覆盖。
    amap_route_cache_ttl_seconds: int = Field(default=900, gt=0)
    # 高德 POI 搜索结果的进程内缓存 TTL，单位为秒，默认值：3600；仅由后端控制，不接受客户端覆盖。
    amap_poi_cache_ttl_seconds: int = Field(default=3600, gt=0)

    @field_validator("mineru_base_url", mode="before")
    @classmethod
    def validate_mineru_base_url(cls, value: str) -> str:
        """仅允许 MinerU 官方 HTTPS 地址。"""

        if value != "https://mineru.net":
            raise ValueError("MinerU Base URL 必须是固定官方 HTTPS 地址")
        return value

    @field_validator("deepseek_base_url", mode="before")
    @classmethod
    def validate_deepseek_base_url(cls, value: str) -> str:
        """仅允许 DeepSeek 官方 HTTPS 地址。"""

        if value != "https://api.deepseek.com":
            raise ValueError("DeepSeek Base URL 必须是固定官方 HTTPS 地址")
        return value

    @field_validator("qwen_vl_base_url", mode="before")
    @classmethod
    def validate_qwen_vl_base_url(cls, value: str) -> str:
        """仅允许 Qwen-VL 官方 HTTPS 地址。"""

        if value != "https://dashscope.aliyuncs.com/compatible-mode/v1":
            raise ValueError("Qwen-VL Base URL 必须是固定官方 HTTPS 地址")
        return value

    @field_validator("document_data_dir", mode="before")
    @classmethod
    def normalize_document_data_dir(cls, value):
        """将文档目录规范为基于仓库根目录的绝对路径。"""

        path = Path(value)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        return str(path.resolve())

    @field_validator(
        "external_max_attempts",
        "circuit_breaker_failure_threshold",
        "circuit_breaker_open_seconds",
        "weather_cache_ttl_seconds",
        "amap_geocode_cache_ttl_seconds",
        "amap_route_cache_ttl_seconds",
        "amap_poi_cache_ttl_seconds",
        "document_max_upload_bytes",
        "document_batch_max_files",
        "knowledge_search_result_limit",
        "deepseek_max_tokens",
        mode="before",
    )
    @classmethod
    def validate_external_integer_settings(cls, value):
        if isinstance(value, bool):
            raise ValueError("配置必须为整数")
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("配置必须为整数")
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped or any(character in stripped for character in ".eE"):
                raise ValueError("配置必须为整数")
            try:
                int(stripped)
            except ValueError as error:
                raise ValueError("配置必须为整数") from error
        return value


@lru_cache
def get_settings() -> Settings:
    """返回进程内共享的服务端配置。"""

    return Settings()
