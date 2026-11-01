from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    upstream_command: str = "python"
    # 改回原样
    upstream_args: list[str] = ["examples/demo_server_rich.py"]

    redis_url: str = "redis://localhost:6379/0"
    ratelimit_enabled: bool = True
    ratelimit_fail_mode: str = "open"
    ratelimit_burst: int = 5
    ratelimit_rate: int = 1
    ratelimit_interval: int = 1000

    # HTTP 传输端口（MCP 在 /mcp）；metrics_port=0 表示不启动 Prometheus
    http_port: int = 8001
    metrics_port: int = 8000

    db_url: str = "sqlite+aiosqlite:///./govern.db"

    class Config:
        env_prefix = "GOVERN_"


settings = Settings()