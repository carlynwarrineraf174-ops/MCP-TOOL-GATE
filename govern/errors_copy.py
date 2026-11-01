from __future__ import annotations

import json

class GovernError(Exception):
    code: int = -32000
    error_type: str = "govern_error"

    def __init__(self, message: str,data: dict | None = None):
        self.message = message
        self.data = data or {}
        super().__init__(message)

    def to_structured(self) -> str:
        return json.dumps(
            {"error": self.error_type, "code": self.code, **self.data},
            ensure_ascii = False
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
    code = -32002
    error_type = "upstream_error"

    def __init__(self, tool: str, reason: str):
        super().__init__("upstream error", {"tool": tool, "reason": reason})