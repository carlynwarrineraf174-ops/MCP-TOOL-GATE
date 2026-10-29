from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 上游配置
    upstream_command: str = "python"
    upstream_args: list[str] = ["examples/demo_server.py"]

    # Redis 与限流配置
    redis_url: str = "redis://localhost:6379/0"
    ratelimit_enabled: bool = True
    ratelimit_fail_mode: str = "open"  # open 或 closed
    ratelimit_burst: int = 5  # 桶最大容量（也就是瞬间并发上限）
    ratelimit_rate: int = 1  # 每次补充几个令牌
    ratelimit_interval: int = 1000  # 多少毫秒补充一次（1000ms = 1秒补1个）

    # 新增：SQLite 异步数据库配置
    db_url: str = "sqlite+aiosqlite:///./govern_v2.db"

    class Config:
        env_prefix = "GOVERN_"


settings = Settings()