from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 默认启动命令
    upstream_command: str = "python"
    upstream_args: list[str] = ["examples/demo_server.py"]

    # 生产环境中可能需要改成 streamable_http
    transport: str = "stdio"

    class Config:
        env_prefix = "GOVERN_"


settings = Settings()