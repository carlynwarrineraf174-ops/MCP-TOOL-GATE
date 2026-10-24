"""gate —— MCP 工具质量门禁的最小可用实现。

四个模块，对应一条端到端链路：

    snapshot  连上 MCP Server，把 tools/list 存成快照
    diff      两份快照做语义 diff，判定 BREAKING / RISKY / SAFE
    rules     严重度定义与规则目录（纯数据，方便补到 20 条）
    check     CLI：出报告 + 用退出码卡 CI
"""

__version__ = "0.1.0"
