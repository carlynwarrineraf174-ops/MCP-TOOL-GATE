"""标准错误体：让客户端能识别"限流"和"上游错误"，而不是一个泛泛的 Exception。

说明：
- MCP 协议里工具失败就是 CallToolResult(isError=True)，没有"HTTP 429"这一层。
- 所以结构化错误放在 content[0].text 里（JSON 字符串），客户端解析后按 retry_after_ms 退避。
- 本文件也保留 JSON-RPC error 格式，作为"以后换 HTTP 网关"的扩展点。
"""

from __future__ import annotations

import json


class GovernError(Exception):
    """治理层所有可映射到结构化错误的基类。"""
    code: int = -32000
    error_type: str = "govern_error"

    def __init__(self, message: str, data: dict | None = None):
        self.message = message
        self.data = data or {}
        super().__init__(message)

    def to_structured(self) -> str:
        """序列化成 content[0].text 里放的 JSON 字符串。"""
        return json.dumps(
            {"error": self.error_type, "code": self.code, **self.data},
            ensure_ascii=False,
        )


class RateLimited(GovernError):
    code = -32001
    error_type = "rate_limited"

    def __init__(self, retry_after_ms: int, tenant: str, tool: str):
        super().__init__(
            "rate limited",
            {"retry_after_ms": retry_after_ms, "tenant": tenant, "tool": tool},
        )
        self.retry_after_ms = retry_after_ms


class UpstreamError(GovernError):
    code = -32003
    error_type = "upstream_error"

    def __init__(self, tool: str, reason: str):
        super().__init__("upstream error", {"tool": tool, "reason": reason})