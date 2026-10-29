from prometheus_client import Counter, Histogram, Gauge

# 1. 调用总数 (Counter)
TOOL_CALLS_TOTAL = Counter(
    "mcp_tool_calls_total",
    "Total calls per tool",
    ["tool", "status"]
)

# 2. 调用耗时 (Histogram)
# 严格按照 lab_06 的教训，分桶必须精细，否则 p95 误差极大
TOOL_DURATION_SECONDS = Histogram(
    "mcp_tool_duration_seconds",
    "Duration of tool calls",
    ["tool"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5)
)

# 3. 当前并发数 (Gauge)
TOOL_INFLIGHT = Gauge(
    "mcp_tool_inflight",
    "Number of inflight calls",
    ["tool"]
)

# 4. 限流拒绝计数 (额外加的)
RATELIMIT_REJECTED_TOTAL = Counter(
    "mcp_ratelimit_rejected_total",
    "Total rate limit rejections",
    ["tenant", "tool"]
)