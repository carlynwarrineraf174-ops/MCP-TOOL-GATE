"""探针：确认 P0-5（响应侧 const/enum）与 P0-7（已知关键字不比较）的现状。

跑法：
    python examples/probe_p05_p07.py
"""
from gate.diff import diff_snapshots


def t(inp_schema, out_schema=None):
    return {
        "description": "d",
        "input_schema": inp_schema,
        "output_schema": out_schema,
    }


def show(label, old_tool, new_tool):
    fs = diff_snapshots({"t": old_tool}, {"t": new_tool})
    result = [(f.kind, f.severity) for f in fs] or "[]"
    print(f"{label:34} -> {result}")


def main():
    obj = {"type": "object", "properties": {}}

    # ---------- P0-5：响应侧 const / enum ----------
    print("=== P0-5 响应侧 ===")

    # 响应侧 const 消失：老客户端读不到固定值 → 应该报 BREAKING（现在静默）
    show(
        "response const 消失",
        t(obj, {"type": "object", "properties": {"v": {"type": "string", "const": "ok"}}}),
        t(obj, {"type": "object", "properties": {"v": {"type": "string"}}}),
    )

    # 响应侧 enum 从无到有：老客户端什么值都见过，现在被限定 → 应该报 RISKY（现在静默）
    show(
        "response enum 从无到有",
        t(obj, {"type": "object", "properties": {"v": {"type": "string"}}}),
        t(obj, {"type": "object", "properties": {"v": {"type": "string", "enum": ["a", "b"]}}}),
    )

    # ---------- P0-7：已知关键字不比较 ----------
    print("\n=== P0-7 已知关键字 ===")

    show(
        "multipleOf 3 -> 7",
        t({"type": "object", "properties": {"n": {"type": "integer", "multipleOf": 3}}}),
        t({"type": "object", "properties": {"n": {"type": "integer", "multipleOf": 7}}}),
    )

    show(
        "not 分支变化",
        t({"type": "object", "properties": {"v": {"not": {"type": "string"}}}}),
        t({"type": "object", "properties": {"v": {"not": {"type": "integer"}}}}),
    )

    show(
        "if/then 变化",
        t({"type": "object", "properties": {"v": {"type": "string", "if": {"minLength": 1}, "then": {"maxLength": 10}}}}),
        t({"type": "object", "properties": {"v": {"type": "string", "if": {"minLength": 1}, "then": {"maxLength": 5}}}}),
    )

    show(
        "contains 变化",
        t({"type": "array", "contains": {"type": "string"}}),
        t({"type": "array", "contains": {"type": "integer"}}),
    )

    show(
        "propertyNames 变化",
        t({"type": "object", "propertyNames": {"pattern": "^[a-z]+$"}}),
        t({"type": "object", "propertyNames": {"pattern": "^[a-z0-9]+$"}}),
    )


if __name__ == "__main__":
    main()