"""严重度定义 + 规则目录。

规则目录（RULES）是纯数据：diff.py 负责"怎么判定"，这张表负责"为什么这么判"。
面试问「你凭什么把 X 判成 BREAKING」，答案就在这张表的理由列里。

三档的来源（可写进 README）：
    oasdiff      ERR   → BREAKING（确定破坏）
                 WARN  → RISKY   （定义不足、无法程序化确认）
                 INFO  → SAFE    （非破坏性）
    openapi-diff 45 条 incompatible 枚举 → 我们这张表的骨架
"""

from __future__ import annotations

BREAKING = "BREAKING"
RISKY = "RISKY"
SAFE = "SAFE"

# 数值越大越严重，用来做阈值比较（--fail-on）
ORDER = {SAFE: 0, RISKY: 1, BREAKING: 2}

# id, 触发条件, 影响侧, 严重度, 一句话理由
RULES: list[tuple[str, str, str, str, str]] = [
    ("tool_removed", "工具被删除", "both", BREAKING, "调用方必崩"),
    ("tool_added", "新增工具", "both", SAFE, "老调用不受影响，但会引入选择干扰（要进评测看）"),
    ("description_changed", "工具/参数 description 变化", "both", RISKY, "不影响代码，但会改变模型选工具的结果"),
    ("prop_removed", "入参被删除", "request", BREAKING, "传了就非法（请求侧收紧）"),
    ("prop_added_optional", "新增可选入参", "request", SAFE, "老调用不受影响"),
    ("prop_added_required", "新增必填入参", "request", BREAKING, "老调用缺参"),
    ("required_added", "可选入参变必填", "request", BREAKING, "老调用缺参（**即使有 default 也一样**）"),
    ("required_removed", "必填变可选", "request", SAFE, "向后兼容"),
    ("type_changed", "类型变更（str→int）", "both", BREAKING, "填不对就静默失败"),
    ("enum_shrunk", "入参 enum 缩小", "request", BREAKING, "老取值可能非法"),
    ("enum_expanded", "入参 enum 扩大", "request", SAFE, "兼容"),
    ("range_tightened", "入参数值/长度范围收紧", "request", BREAKING, "老取值越界"),
    ("default_changed", "default 变化", "both", RISKY, "不报错但行为变了"),
    ("additional_props_closed", "additionalProperties 改为 false", "request", BREAKING, "老调用多传的字段会被拒"),
    ("response_prop_removed", "返回字段减少", "response", BREAKING, "老调用读不到"),
    ("response_required_removed", "返回字段不再保证存在", "response", BREAKING, "老调用可能拿到 null"),
    ("response_required_added", "返回字段变为必有", "response", SAFE, "老客户端多了一个可读字段"),
    ("response_enum_expanded", "返回 enum 扩大", "response", BREAKING, "老客户端不认识新值"),
    ("union_changed", "oneOf/anyOf/allOf 分支内容变化", "both", RISKY, "顺序不同不算；内容变了无法程序化确认兼容性"),
    ("output_schema_removed", "不再声明返回 schema", "response", RISKY, "客户端无法校验返回值"),
    ("const_changed", "const 值变化 / 新增", "both", BREAKING, "取值被钉死，老调用可能传别的值"),
    ("pattern_changed", "正则 pattern 变化", "request", RISKY, "正则包含关系无法程序化判定 → 转人工 review"),
    ("unsupported_keyword", "未支持的关键字发生变化", "both", RISKY, "静默放过 = 虚假的通过信号；漏报比误报贵"),
    ("dependent_required_added", "字段间依赖变严", "request", BREAKING, "等于给老调用加了一条隐性必填"),
]


def worst(findings: list) -> str:
    """返回这批 finding 里最严重的档位；空列表 = SAFE。"""
    level = SAFE
    for f in findings:
        if ORDER[f.severity] > ORDER[level]:
            level = f.severity
    return level


def rule_catalog_markdown() -> str:
    lines = ["| 规则 | 触发条件 | 侧 | 严重度 | 理由 |", "|---|---|---|---|---|"]
    for rid, cond, side, sev, why in RULES:
        lines.append(f"| `{rid}` | {cond} | {side} | **{sev}** | {why} |")
    return "\n".join(lines)
